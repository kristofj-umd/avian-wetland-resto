from pathlib import Path
import geopandas as gpd
import pandas as pd
import pyogrio as po
from geopandas.array import GeometryArray
import shapely
from functools import lru_cache

col_mapping = {
    "WETLAND_TYPE": "type",
    "ATTRIBUTE": "code",
}


@lru_cache(maxsize=1)
def _scan_nwi(nwi_dir: str):
    """One-time scan of gpkg files → [(path, layer_name, crs_wkt, total_bounds)]."""
    out = []
    for gpkg in Path(nwi_dir).rglob("*.gpkg"):
        layer = f"{gpkg.stem.split('_')[0]}_Wetlands"
        info = po.read_info(gpkg, layer=layer)
        out.append((str(gpkg), layer, info["crs"], tuple(info["total_bounds"])))
    return out


def wetlands_within_buffer(buffer_gs, crs_target: str, nwi_dir: str):
    # buffer in target CRS (already is); compute once
    nwi_index = _scan_nwi(nwi_dir)
    candidates = []
    for path, layer, crs_wkt, tb in nwi_index:
        # bbox test in the file's CRS
        bbox_in_file_crs = tuple(buffer_gs.to_crs(crs_wkt).total_bounds)
        if shapely.box(*bbox_in_file_crs).intersects(shapely.box(*tb)):
            # read only geometry + needed columns
            gdf = po.read_dataframe(
                path,
                layer=layer,
                bbox=bbox_in_file_crs,
                columns=["WETLAND_TYPE", "ATTRIBUTE", "geometry"],
            )
            if gdf is not None and not gdf.empty:
                # keep native file CRS here
                gdf.set_crs(crs_wkt, inplace=True)
                candidates.append(gdf)

    if not candidates:
        return None

    gdf = gpd.GeoDataFrame(pd.concat(candidates, ignore_index=True))
    # Reproject once to analysis CRS, THEN clip
    gdf = gdf.to_crs(crs_target)
    return gpd.clip(gdf, buffer_gs)  # both in crs_target


def process_one_nwi(
    point: GeometryArray, buffer_size: int, prefix: str, crs: str, nwi_dir: str
) -> dict | None:
    # print(f"Processing NWI for buffer size {buffer_size} m")
    # print(f"    Getting bounding box for point...")
    # reproject point to raster CRS - so units match buffer units
    point = point.to_crs(crs)
    # create buffer as GeoSeries from point
    buffer = gpd.GeoSeries(point, crs=crs).buffer(buffer_size)

    # get wetlands within bbox
    # print(f"    Getting wetlands within buffer...")
    gdf = wetlands_within_buffer(buffer, crs, nwi_dir)

    # exit early if no wetlands found
    if gdf is None:
        # print("No wetlands found within bounding box.")
        return None

    # print(f"    Found {len(gdf)} wetlands within buffer.")

    # print(f"    Generating column statistics...")
    # iterate over columns
    # find unique values and counts of each column in col_mapping
    # and calculate total area and percent of total area occupied by each class
    result = {}

    # calculate area once
    gdf["area_m2"] = gdf.geometry.area
    total_area = gdf["area_m2"].sum()
    # value counts + grouped sums w/o per-group lambda:
    for src_col, short in col_mapping.items():
        # Get value counts (frequencies) for each class in the source column
        vc = gdf[src_col].value_counts(sort=False)
        # Calculate total area for each class by grouping and summing
        sums = gdf.groupby(src_col, observed=True)["area_m2"].sum()
        # Calculate percentage of total area for each class
        pct = sums / total_area
        # For each unique value in the source column
        for val in vc.index:
            # Create the output metric name using the prefix, buffer size, column shortname and value
            name = f"{prefix}_buff{buffer_size}_{short}_{val}"
            # Store count of occurrences for this value
            result[f"{name}_count"] = int(vc[val])
            # Store total area for this value
            result[f"{name}_area"] = float(sums[val])
            # Store percentage of total area for this value
            result[f"{name}_percent"] = float(pct[val])

    return result
    # print(f"result: {result}")
