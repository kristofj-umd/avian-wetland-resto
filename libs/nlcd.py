# nlcd.py

# Module for accessing and processing National Land Cover Database (NLCD) data

# ---- IMPORTS -----
import boto3, os, rasterio, shapely, re, requests
import pandas as pd, geopandas as gpd, numpy as np
from rasterio.session import AWSSession
from rasterio.mask import mask
from geopandas.array import GeometryArray
from pathlib import Path
import os
from dotenv import load_dotenv

# ---- CONSTANTS -----
NLCD_CLASS_LUT = {
    # 11: "Open Water",
    12: "Perennial Ice/Snow",
    21: "Developed, Open Space",
    22: "Developed, Low Intensity",
    23: "Developed, Medium Intensity",
    24: "Developed, High Intensity",
    31: "Barren Land (Rock/Sand/Clay)",
    41: "Deciduous Forest",
    42: "Evergreen Forest",
    43: "Mixed Forest",
    52: "Shrub/Scrub",
    71: "Grassland/Herbaceous",
    81: "Pasture/Hay",
    82: "Cultivated Crops",
    90: "Woody Wetlands",
    95: "Emergent Herbaceous Wetlands",
    # Optional (present in metadata legend):
    250: "NoData",
}

# ----- FUNCTIONS -----


def nlcd_setup() -> AWSSession:
    """
    Set up AWS S3 access for NLCD data retrieval.
    """
    # ----- Configure AWS S3 access -----

    # AWS credentials from .env file
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    # set the default region
    os.environ["AWS_DEFAULT_REGION"] = "us-west-2"
    # set no sign in request
    os.environ["AWS_NO_SIGN_REQUEST"] = "NO"

    # ----- Initialize S3 and AWS session -----
    # build a signed AWS session that includes requester-pays
    boto_sesh = boto3.Session(
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name="us-west-2",
    )
    return AWSSession(boto_sesh, requester_pays=True)


def nlcd_buffer_clip(
    point: GeometryArray,
    buffer_size: int,
    year: int,
    aws_sesh: AWSSession,
    nlcd_paths: dict[int, str],
) -> tuple[np.ndarray, float]:
    # get raster values for buffer
    with rasterio.Env(aws_sesh):
        with rasterio.open(nlcd_paths[year]) as src:
            # Calculate area per pixel in square meters
            area_per_pixel = abs(src.res[0] * src.res[1])

            # reproject point to raster CRS - so units match buffer units
            point = point.to_crs(src.crs)
            # create buffer from point, convert to geojson like object
            buffer = point.buffer(buffer_size)

            # read data from raster within poly (window)
            data, transform = mask(
                src, buffer, crop=True, filled=True
            )  # windowed read
            # get values from first band, skipping nodata values
            band = data[0]  # NLCD is single-band categorical
            nodata = src.nodatavals[0]
            mask_valid = (
                (band != nodata)
                if nodata is not None
                else np.ones_like(band, dtype=bool)
            )
            return band[mask_valid].astype(np.int8), area_per_pixel
