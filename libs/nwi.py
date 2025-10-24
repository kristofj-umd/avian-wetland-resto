from pathlib import Path
import geopandas as gpd
import pandas as pd
import pyogrio as po
from geopandas.array import GeometryArray
import shapely

col_mapping = {
    "WETLAND_TYPE": "type",
    "ATTRIBUTE": "code",
}


def wetlands_within_buffer(buffer: gpd.GeoSeries) -> gpd.GeoDataFrame | None:
    # get geopackages
    gpkg_files = Path(nwi_dir).rglob("*.gpkg")

    # find which files intersect the buffer
    in_gdfs = []
    for gpkg in gpkg_files:
        # print(f"Checking {gpkg}...")
        # layer name will always be state name abbreviation + "_Wetlands"
        layer_name = f"{gpkg.stem.split('_')[0]}_Wetlands"
        # get NWI CRS and bounds
        nwi_info = po.read_info(gpkg, layer=layer_name)
        # reproject buffer to nwi_crs, get bounds
        bbox = tuple(buffer.to_crs(nwi_info["crs"]).total_bounds)
        # check if bbox intersects nwi bounds
        if shapely.box(*bbox).intersects(
            shapely.box(*nwi_info["total_bounds"])
        ):
            # if we're passed bbox intersect, read into geodataframe using bbox
            gdf = po.read_dataframe(gpkg, bbox=bbox, layer=layer_name)
            # if gdf is not empty, add to list
            if gdf is not None and not gdf.empty:
                # print(f"  Found {len(gdf)} wetlands in {gpkg}")
                in_gdfs.append(gdf)

    # exit early if no wetlands found
    if not in_gdfs:
        return None

    # combine all gdfs
    combined_gdf = gpd.GeoDataFrame(
        pd.concat(in_gdfs, ignore_index=True), crs=crs
    )

    # clip combined gdf using buffer
    clipped_gdf = gpd.clip(combined_gdf, buffer.to_crs(crs))
    return clipped_gdf


def process_one_nwi(point: GeometryArray, buffer_size: int, prefix: str):
    # print(f"Processing NWI for buffer size {buffer_size} m")
    # print(f"    Getting bounding box for point...")
    # reproject point to raster CRS - so units match buffer units
    point = point.to_crs(crs)
    # create buffer as GeoSeries from point
    buffer = gpd.GeoSeries(point, crs=crs).buffer(buffer_size)

    # get wetlands within bbox
    # print(f"    Getting wetlands within buffer...")
    gdf = wetlands_within_buffer(buffer)

    # exit early if no wetlands found
    if gdf is None:
        # print("No wetlands found within bounding box.")
        return

    # print(f"    Found {len(gdf)} wetlands within buffer.")

    # print(f"    Generating column statistics...")
    # iterate over columns
    # find unique values and counts of each column in col_mapping
    # and calculate total area and percent of total area occupied by each class
    result = {}

    # calculate total area of all wetlands
    total_area = gdf.geometry.area.sum()

    # iterate over columns in col_mapping
    for col in col_mapping.keys():
        # get count by class
        class_counts = gdf[col].value_counts()
        # calculate area by class
        class_areas = gdf.groupby(col)["geometry"].apply(lambda x: x.area.sum())
        # calculate percent area
        class_pcts = class_areas / total_area

        # add to results
        for val in class_counts.index:
            name = f"{prefix}_buff{buffer_size}_{col_mapping[col]}_{val}"
            result.update(
                {
                    f"{name}_count": class_counts[val],
                    f"{name}_area": class_areas[val],
                    f"{name}_percent": class_pcts[val],
                }
            )

    return result
    # print(f"result: {result}")
