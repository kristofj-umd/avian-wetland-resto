#!/usr/bin/env python3
"""
Part 1: class summary by buffer

Calculate total area and percent occupied by class for buffers of CWMP and GLFWRA
bird count locations.

Buffers: 200m, 500m, 1km, 2km
Data: land cover (NLCD + NALCMS) and wetlands (NWI)
Years: 2010, 2015, 2020, 2023
Deliverable: CSV file for each bird count dataset containing class summaries
             for each buffer for each location.

Output columns follow the pattern:
<dataset>_buff<size>_yr<year>_<class>_(count|area|percent)

NWI columns don't include year:
nwi_buff500_code_R2UBH_percent

This script is a standalone version of the original notebook.
It can be run directly with Python.
"""

from __future__ import annotations

# standard lib
import os
from pathlib import Path
from functools import lru_cache
import json

# external deps
import geopandas as gpd
import pandas as pd
from tqdm.auto import tqdm
import pyogrio as po

# local project imports
from libs.land_cover import (
    nlcd_sesh_setup,
    process_one_landcover,
    get_nlcd_paths,
)
from libs.nwi import process_one_nwi


# -----------------------------------------------------------------------------
# CONFIG / CONSTANTS
# -----------------------------------------------------------------------------

# buffers in meters
BUFFERS = [200, 500, 1000, 2000]

# land cover years
YEARS = [2010, 2015, 2020, 2023]

# project CRS used for buffering/intersection with NWI, etc.
PROJECT_CRS = "EPSG:5070"

# input bird location files
CWMP_PATH = "data/CWMP_PCL_all.xlsx - CWMP_bird_point_count_locations.csv"
GLFWRA_PATH = "data/GLFWRA_PCL_all.csv"

# NALCMS land cover rasters (static paths on disk)
NALCMS_PATHS = {
    2010: "M:/isabel_bird/data/nalcms/land_cover_2010v3_30m_tif/NA_NALCMS_landcover_2010v3_30m/data/NA_NALCMS_landcover_2010v3_30m.tif",
    2015: "M:/isabel_bird/data/nalcms/land_cover_2015v4_30m_tif/NA_NALCMS_landcover_2015v4_30m/data/NA_NALCMS_landcover_2015v4_30m.tif",
    2020: "M:/isabel_bird/data/nalcms/land_cover_2020v2_30m_tif/NA_NALCMS_landcover_2020v2_30m/data/NA_NALCMS_landcover_2020v2_30m.tif",
}

# path to json file that lists all NWI geopackages
NWI_PATH_JSON = "data/nwi_filelist.json"

# output directory
OUTPUT_DIR = Path("data/output")

# which columns in each dataset are the lat/lon
BIRD_LOCS_FIELD_MAPPING = {
    "CWMP": {
        "lat": "latitude",
        "lon": "longitude",
    },
    "GLFWRA": {
        "lat": "Lat",
        "lon": "Lon",
    },
}

# -----------------------------------------------------------------------------
# Wetland Setup
# -----------------------------------------------------------------------------

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

# build_nwi_coverage.py  (run once, or when NWI data is updated)
def _build_nwi_coverage(nwi_paths: list[str]):
    # get parts list
    parts = []
    # iterate over geopackages
    for gpkg_str in nwi_paths:
        # get path to geopackage
        gpkg = Path(gpkg_str)
        # Extract layer name from filename (e.g., "NY_Wetlands" from "NY_xxx.gpkg")
        state = gpkg.stem.split('_')[0]
        layer = f"{state}_Wetlands_Project_Metadata"
        meta = gpd.read_file(gpkg, layer=layer)        # + filter on status field, if any (step 0)
        parts.append(meta.to_crs(PROJECT_CRS).make_valid())
    coverage = gpd.GeoDataFrame(geometry=pd.concat(parts).geometry, crs=PROJECT_CRS).dissolve()
    coverage = coverage.explode(index_parts=False)     # separate parts -> spatial index works well
    coverage.to_file(OUTPUT_DIR / "nwi_coverage.gpkg", layer="coverage")

def wetland_setup():
    # index NWI geopackages
    nwi_index = _scan_nwi(NWI_PATH_JSON)
    # build NWI coverage for quick spatial indexing
    _build_nwi_coverage(nwi_index)
    return nwi_index    


# -----------------------------------------------------------------------------
# CORE LOGIC
# -----------------------------------------------------------------------------
def process_source_locations(
    source_name: str,
    df: pd.DataFrame,
    nlcd_paths: dict,
    nlcd_sesh,
    nwi_index: list,
) -> pd.DataFrame:
    """
    For each row in df:
      - build a point geometry from its lat/lon
      - for each buffer size and each year:
          * run process_one_landcover(...) twice:
              - NLCD
              - NALCMS
        then once per buffer run process_one_nwi(...)

    Collect all of those little dicts, merge them, and join back
    to the original df (wide format).

    Returns:
        results_df (pd.DataFrame): original df plus new columns.
    """

    print(f"Processing {source_name}: {len(df)} bird count locations")

    # figure out lat/lon columns once
    lat_field = BIRD_LOCS_FIELD_MAPPING[source_name]["lat"]
    lon_field = BIRD_LOCS_FIELD_MAPPING[source_name]["lon"]

    # when using itertuples(index=True, name=None),
    # row[0] is the original index,
    # row[1] is first df column, etc.
    # so we compute offsets:
    lat_idx = 1 + df.columns.get_loc(lat_field)
    lon_idx = 1 + df.columns.get_loc(lon_field)

    rows_out = []

    for row in tqdm(
        df.itertuples(index=True, name=None),
        total=len(df),
        desc="Locations",
        dynamic_ncols=True,
    ):
        orig_idx = row[0]
        lon = float(row[lon_idx])
        lat = float(row[lat_idx])

        # create point geometry (lon, lat) in WGS84
        point = gpd.points_from_xy([lon], [lat], crs="EPSG:4326")

        row_dicts = []

        # loop over each buffer + each year
        for buffer_size in BUFFERS:
            for year in YEARS:
                # NLCD
                nlcd_result = process_one_landcover(
                    point=point,
                    buffer_size=buffer_size,
                    year=year,
                    source="nlcd",
                    nlcd_paths=nlcd_paths,
                    aws_sesh=nlcd_sesh,
                )
                if nlcd_result is not None:
                    row_dicts.append(nlcd_result)

                # NALCMS
                nalcms_result = process_one_landcover(
                    point=point,
                    buffer_size=buffer_size,
                    year=year,
                    source="nalcms",
                    nalcms_paths=NALCMS_PATHS,
                )
                if nalcms_result is not None:
                    row_dicts.append(nalcms_result)

            # NWI (note: no per-year breakdown)
            nwi_result = process_one_nwi(
                point=point,
                buffer_size=buffer_size,
                source="nwi",
                crs=PROJECT_CRS,
                nwi_index=nwi_index,
            )
            if nwi_result is not None:
                row_dicts.append(nwi_result)

        # merge all dicts for this location into one record
        if row_dicts:
            merged = {k: v for d in row_dicts for k, v in d.items()}
            merged["_source_index"] = orig_idx
            rows_out.append(merged)
        else:
            # if we couldn't compute anything, still keep index mapping
            rows_out.append({"_source_index": orig_idx})

    # Convert collected dicts -> df keyed by original index, then join wide
    new_cols_df = (
        pd.DataFrame(rows_out).set_index("_source_index").reindex(df.index)
    )
    results_df = df.join(new_cols_df)

    return results_df


def main():

    # Step 1. I/O setup
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 2. Read bird location CSVs
    cwmp_df = pd.read_csv(CWMP_PATH)
    glfwra_df = pd.read_csv(GLFWRA_PATH)

    # Step 3. Prep NLCD session + path lookup
    nlcd_sesh = nlcd_sesh_setup()
    nlcd_paths = get_nlcd_paths()
    nwi_index = wetland_setup()

    # Step 4. Process GLFWRA
    glfwra_results = process_source_locations(
        source_name="GLFWRA",
        df=glfwra_df,
        nlcd_paths=nlcd_paths,
        nlcd_sesh=nlcd_sesh,
        nwi_index=nwi_index,
    )
    print("Completed processing for GLFWRA. Writing CSV...")
    glfwra_outpath = OUTPUT_DIR / "glfwra_class_summary_by_buffer.csv"
    glfwra_results.to_csv(glfwra_outpath, index=False)

    # Step 5. Process CWMP
    cwmp_results = process_source_locations(
        source_name="CWMP",
        df=cwmp_df,
        nlcd_paths=nlcd_paths,
        nlcd_sesh=nlcd_sesh,
        nwi_index=nwi_index,
    )
    print("Completed processing for CWMP. Writing CSV...")
    cwmp_outpath = OUTPUT_DIR / "cwmp_class_summary_by_buffer.csv"
    cwmp_results.to_csv(cwmp_outpath, index=False)

    # Done
    print("All processing complete.")
    print(f"GLFWRA output: {glfwra_outpath}")
    print(f"CWMP output:   {cwmp_outpath}")


if __name__ == "__main__":
    main()
