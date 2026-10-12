from pathlib import Path

import geopandas as gpd
import pandas as pd
from geopandas.array import GeometryArray
import shapely

from .utils import _nice_string_to_name
import time

col_mapping = {
    "WETLAND_TYPE": "type",
    "ATTRIBUTE": "code",
}

# METHODS

def _erase_cross_file_overlap(gdf, file_col="_file", min_area=1.0):
    """Remove overlapping portions of polygons

    Args:
        gdf (gpd.Geodataframe): input geodataframe
        file_col (str, optional): group by dataset. Defaults to "_file".
        min_area (float, optional): min. area for feature to be kept. 
        Defaults to 1.0.

    Returns:
        gpd.Geodataframe: cleaned output geodataframe
    """
    kept, covered = [], None
    # iterate over features, grouping by origin dataset
    for _, part in gdf.groupby(file_col, sort=True):
        if covered is not None:
            part = part.copy()
            # extract the remaining portion from the overlap
            part["geometry"] = part.geometry.difference(covered)
            # drop empty results and tiny slivers
            part = part[part.area > min_area]   
        kept.append(part)
        combined_parts = part.union_all()
        covered = combined_parts if covered is None else covered.union(combined_parts)
    return gpd.GeoDataFrame(pd.concat(kept), crs=gdf.crs) 


def wetlands_within_buffer(buffer_gs, crs_target: str, nwi_index: list):

    candidates = []
    for (path, layer, crs_wkt, tb) in nwi_index:

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
            # tag the file that each feature came from
            gdf["_file"] = layer

            if gdf is not None and not gdf.empty:
                # keep native file CRS here
                gdf.set_crs(crs_wkt, inplace=True)
                # reproject and add to candidate list
                candidates.append(gdf.to_crs(crs_target))

    # No wetlands found in buffer
    if not candidates:
        return None

    # Merging and reprojecting results...
    gdf = gpd.GeoDataFrame(pd.concat(candidates, ignore_index=True))
    # clip to buffer
    gdf = gpd.clip(gdf, buffer_gs)  # both in crs_target
    # exit early if clip leaves empty gdf
    if gdf.empty:
        return None
    # remove overlapping portions from geometry
    result = _erase_cross_file_overlap(gdf)
    return result


def process_one_nwi(
    point: GeometryArray,
    buffer_size: int,
    source: str,
    crs: str,
    nwi_index: list,
) -> dict | None:

    # reproject point to raster CRS - so units match buffer units
    point = point.to_crs(crs)
    # create buffer as GeoSeries from point
    buffer = gpd.GeoSeries(point, crs=crs).buffer(buffer_size)
    # print(
    #     f"Buffer creation completed in {time.time() - start_time:.2f} seconds"
    # )

    # get wetlands within bbox
    gdf = wetlands_within_buffer(buffer, crs, nwi_index)

    # exit early if no wetlands found
    if gdf is None:
        # print("No wetlands found - exiting")
        return None

    # iterate over columns
    # find unique values and counts of each column in col_mapping
    # and calculate total area and percent of total area occupied by each class
    result = {}

    # calculate area once
    gdf["area_m2"] = gdf.geometry.area
    total_area = gdf["area_m2"].sum()
    # record total wetland area in the buffer
    # 0 = covered but no wetlands, NaN = not covered
    result[f"{_nice_string_to_name(f'{source}_buff{buffer_size}')}_total_area"] = \
        float(total_area)
    # summarize count, area, and percent of total area for each class
    for src_col, short in col_mapping.items():
        # group polygons by class; count polygons and sum their area in one pass
        stats = gdf.groupby(src_col, observed=True)["area_m2"].agg(
            count="size",  # number of polygons in each class
            area="sum",    # total area (m2) of each class
        )
        # percent of total wetland area occupied by each class
        stats["percent"] = stats["area"] / total_area

        # one row per class: (class value, count, area, percent)
        for val, count, area, percent in stats.itertuples():
            # build the output column name, e.g. nwi_buff500_code_r2ubh
            name = _nice_string_to_name(f"{source}_buff{buffer_size}_{short}_{val}")
            # store the stats; cast numpy types to plain Python for clean CSV output
            result[f"{name}_count"] = int(count)
            result[f"{name}_area"] = float(area)
            result[f"{name}_percent"] = float(percent)

    return result
