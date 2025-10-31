from pathlib import Path
from functools import lru_cache
import json

import geopandas as gpd
import pandas as pd
import pyogrio as po
from geopandas.array import GeometryArray
import shapely

from .utils import _nice_string_to_name
import time

col_mapping = {
    "WETLAND_TYPE": "type",
    "ATTRIBUTE": "code",
}


def _load_json(path: Path) -> dict:
    with open(path, "r") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _scan_nwi(nwi_path_json: str):
    """One-time scan of gpkg files → [(path, layer_name, crs_wkt, total_bounds)]."""
    # print(f"Loading NWI paths from {nwi_path_json}")
    # Load JSON file containing paths to GPKG files
    gpkg_paths = _load_json(Path(nwi_path_json))
    # print(f"Found {len(gpkg_paths)} GPKG files to process")
    out = []
    # Process each GPKG path
    for i, gpkg_str in enumerate(gpkg_paths, 1):
        # print(f"Processing file {i}/{len(gpkg_paths)}: {gpkg_str}")
        gpkg = Path(gpkg_str)
        # Extract layer name from filename (e.g., "NY_Wetlands" from "NY_xxx.gpkg")
        layer = f"{gpkg.stem.split('_')[0]}_Wetlands"
        # Read metadata (CRS and bounds) from GPKG without loading full data
        info = po.read_info(gpkg, layer=layer)
        # Store tuple of (path, layer, CRS, bounds) for each GPKG
        out.append((str(gpkg), layer, info["crs"], tuple(info["total_bounds"])))
    # print("NWI scan complete")
    return out


def wetlands_within_buffer(buffer_gs, crs_target: str, nwi_path_json: str):
    start_time = time.time()

    # buffer in target CRS (already is); compute once
    # print("Scanning NWI files...")
    nwi_index = _scan_nwi(nwi_path_json)
    # print(f"Scan completed in {time.time() - start_time:.2f} seconds")

    candidates = []
    # print(f"Processing {len(nwi_index)} potential files...")
    for i, (path, layer, crs_wkt, tb) in enumerate(nwi_index, 1):
        file_start = time.time()
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
                # print(
                #     f"File {i}/{len(nwi_index)} processed in {time.time() - file_start:.2f} seconds - found wetlands"
                # )
        # else:
        # print(f"File {i}/{len(nwi_index)} skipped (no intersection)")

    if not candidates:
        # print("No wetlands found in buffer")
        return None

    # print("Merging and reprojecting results...")
    merge_start = time.time()
    gdf = gpd.GeoDataFrame(pd.concat(candidates, ignore_index=True))
    # Reproject once to analysis CRS, THEN clip
    gdf = gdf.to_crs(crs_target)
    result = gpd.clip(gdf, buffer_gs)  # both in crs_target
    # print(
    #     f"Processing completed in {time.time() - start_time:.2f} seconds total"
    # )
    return result


def process_one_nwi(
    point: GeometryArray,
    buffer_size: int,
    source: str,
    crs: str,
    nwi_path_json: str,
) -> dict | None:

    start_time = time.time()
    # print(f"Processing NWI for point with buffer size {buffer_size}m...")

    # reproject point to raster CRS - so units match buffer units
    point = point.to_crs(crs)
    # create buffer as GeoSeries from point
    buffer = gpd.GeoSeries(point, crs=crs).buffer(buffer_size)
    # print(
    #     f"Buffer creation completed in {time.time() - start_time:.2f} seconds"
    # )

    # get wetlands within bbox
    gdf = wetlands_within_buffer(buffer, crs, nwi_path_json)

    # exit early if no wetlands found
    if gdf is None:
        # print("No wetlands found - exiting")
        return None

    # print("Processing wetlands attributes...")
    attr_start = time.time()

    # iterate over columns
    # find unique values and counts of each column in col_mapping
    # and calculate total area and percent of total area occupied by each class
    result = {}

    # calculate area once
    gdf["area_m2"] = gdf.geometry.area
    total_area = gdf["area_m2"].sum()
    # value counts + grouped sums w/o per-group lambda:
    for src_col, short in col_mapping.items():
        col_start = time.time()
        # Get value counts (frequencies) for each class in the source column
        vc = gdf[src_col].value_counts(sort=False)
        # Calculate total area for each class by grouping and summing
        sums = gdf.groupby(src_col, observed=True)["area_m2"].sum()
        # Calculate percentage of total area for each class
        pct = sums / total_area
        # For each unique value in the source column
        for val in vc.index:
            # Create the output metric name using the source, buffer size, column shortname and value
            name = f"{source}_buff{buffer_size}_{short}_{val}"
            # Store count of occurrences for this value
            result[f"{_nice_string_to_name(name)}_count"] = int(vc[val])
            # Store total area for this value
            result[f"{_nice_string_to_name(name)}_area"] = float(sums[val])
            # Store percentage of total area for this value
            result[f"{_nice_string_to_name(name)}_percent"] = float(pct[val])
        # print(
        #     f"Column {src_col} processed in {time.time() - col_start:.2f} seconds"
        # )

    # print(
    #     f"Total processing completed in {time.time() - start_time:.2f} seconds"
    # )
    return result
