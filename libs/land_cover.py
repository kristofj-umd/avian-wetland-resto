# nlcd.py

# Module for accessing and processing National Land Cover Database (NLCD) data

# ---- IMPORTS -----
import os
from pathlib import Path
from functools import lru_cache

import boto3
import rasterio
import numpy as np
from rasterio.session import AWSSession
from rasterio.mask import mask
from geopandas.array import GeometryArray
from dotenv import load_dotenv

from .utils import _nice_string_to_name

# ----- CONSTANTS -----

# nalcms class lookup table
NALCMS_CLASS_LUT = {
    1: "sub-polar needleleaf forest",
    2: "Sub-polar taiga needleleaf forest",
    3: "sub-tropical broadleaf evergreen forest",
    4: "sub-tropical broadleaf deciduous forest",
    5: "sub-polar broadleaf deciduous forest",
    6: "Mixed Forest",
    7: "sub-tropical shrubland",
    8: "sub-polar shrubland",
    9: "sub-tropical grassland",
    10: "sub-polar grassland",
    11: "polar shrubland-lichen-moss",
    12: "polar grassland-lichen-moss",
    13: "polar barren-lichen-moss",
    14: "Wetland",
    15: "Cropland",
    16: "Barren lands",
    17: "Urban",
    # 18: "Water",
    19: "Snow and Ice",
}

# nlcd class lookup table
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


@lru_cache(maxsize=None)
def _open_raster_cached(path: str):
    return rasterio.open(path)


def nlcd_sesh_setup() -> AWSSession:
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


def get_nlcd_paths() -> dict[int, str]:
    # Specify the bucket name and prefix
    bucket_name = "usgs-landcover"
    base_prefix = "annual-nlcd/c1/v0/cu/mosaic/"

    # Define the years of interest and their expected filenames
    nlcd_filenames = {
        2010: "Annual_NLCD_LndCov_2010_CU_C1V0.tif",
        2015: "Annual_NLCD_LndCov_2015_CU_C1V0.tif",
        2020: "Annual_NLCD_LndCov_2020_CU_C1V0.tif",
        2023: "Annual_NLCD_LndCov_2023_CU_C1V0.tif",
    }

    # Initialize the S3 client
    # Using default configuration, relying on AWS environment variables or public bucket policy for access
    s3 = boto3.client("s3", region_name="us-west-2")

    print("Verifying existence of NLCD land cover files in S3:")

    # Check for the existence of each file
    found_objects = False
    nlcd_paths = {}
    for year, filename in nlcd_filenames.items():
        s3_key = base_prefix + filename
        try:
            # Use head_object to check for file existence without downloading
            # Add RequestPayer='requester' as it's a requester pays bucket
            s3.head_object(
                Bucket=bucket_name, Key=s3_key, RequestPayer="requester"
            )
            print(f"File found for {year}: s3://{bucket_name}/{s3_key}")
            # print(response)
            # add to nlcd_path dict
            nlcd_paths[year] = f"s3://{bucket_name}/{s3_key}"
            found_objects = True
        except s3.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                print(f"File NOT found for {year}: s3://{bucket_name}/{s3_key}")
            else:
                print(f"An error occurred checking file for {year}: {e}")
        except Exception as e:
            print(f"An unexpected error occurred for {year}: {e}")

    if not found_objects:
        print(
            "No requested NLCD land cover files were found in the specified location."
        )

    return nlcd_paths


def nlcd_buffer_clip(
    point: GeometryArray,
    buffer_size: int,
    year: int,
    aws_sesh: AWSSession,
    nlcd_paths: dict[int, str],
) -> tuple[np.ndarray, float]:
    # get raster values for buffer
    with rasterio.Env(aws_sesh):
        # Open the NLCD raster using cached function to avoid repeated reads
        src = _open_raster_cached(nlcd_paths[year])
        # Reproject point to match raster CRS
        point = point.to_crs(src.crs)
        # Create buffer around point
        buffer = point.buffer(buffer_size)
        # Extract raster data within geometry mask
        data, _ = mask(src, buffer, crop=True, filled=True)
        # Get first band (NLCD is single-band categorical)
        band = data[0]
        # Get nodata value from raster
        nodata = src.nodatavals[0]
        # Create mask to exclude nodata values
        mask_valid = (
            (band != nodata) if nodata is not None else np.ones_like(band, bool)
        )
        # Return valid data as uint16 and pixel area in square meters
        return band[mask_valid].astype(np.uint16), abs(src.res[0] * src.res[1])


def nalcms_buffer_clip(
    point: GeometryArray,
    buffer_size: int,
    year: int,
    nalcms_paths: dict[int, str],
) -> tuple[np.ndarray, float]:
    # get raster values for buffer
    src = _open_raster_cached(nalcms_paths[year])
    # Calculate area per pixel in square meters
    area_per_pixel = abs(src.res[0] * src.res[1])

    # reproject point to raster CRS - so units match buffer units
    point = point.to_crs(src.crs)
    # create buffer from point, convert to geojson like object
    buffer = point.buffer(buffer_size)

    # read data from raster within poly (window)
    data, transform = mask(src, buffer, crop=True, filled=True)  # windowed read
    # get values from first band, skipping nodata values
    band = data[0]  # NLCD is single-band categorical
    nodata = src.nodatavals[0]
    mask_valid = (
        (band != nodata)
        if nodata is not None
        else np.ones_like(band, dtype=bool)
    )
    return band[mask_valid].astype(np.uint16), area_per_pixel


def process_one_landcover(
    point: GeometryArray,
    buffer_size: int,
    year: int,
    source: str,
    nlcd_paths: dict[int, str] | dict = {},
    nalcms_paths: dict[int, str] | dict = {},
    aws_sesh: AWSSession | None = None,
) -> dict:
    # Initialize empty result dict
    result = {}

    try:
        breakpoint()
        # get raster values for buffer
        if source == "nlcd":
            if year not in nlcd_paths:
                return result
            vals, area_per_pixel = nlcd_buffer_clip(
                point, buffer_size, year, aws_sesh, nlcd_paths
            )
        else:
            if year not in nalcms_paths:
                return result
            vals, area_per_pixel = nalcms_buffer_clip(
                point, buffer_size, year, nalcms_paths
            )

        # Check if we got any valid values
        if vals is None or len(vals) == 0:
            return result

        # get count by class
        unique_values, counts = np.unique(vals, return_counts=True)
        class_counts = dict(zip(unique_values, counts))

        # calculate percent of total area occupied by each class
        total = np.sum(counts)
        if total == 0:
            return result

        class_percents = {k: v / total for k, v in class_counts.items()}

        # Use appropriate lookup table
        lut = NLCD_CLASS_LUT if source == "nlcd" else NALCMS_CLASS_LUT

        # iterate over unique values and update dict with count, percent
        for val in [v for v in unique_values if v in lut.keys()]:
            result.update(
                {
                    f"{source}_buff{buffer_size}_yr{year}_{_nice_string_to_name(lut[val])}_count": class_counts[
                        val
                    ],
                    f"{source}_buff{buffer_size}_yr{year}_{_nice_string_to_name(lut[val])}_area": class_counts[
                        val
                    ]
                    * area_per_pixel,
                    f"{source}_buff{buffer_size}_yr{year}_{_nice_string_to_name(lut[val])}_percent": class_percents[
                        val
                    ],
                }
            )

    except Exception as e:
        print(
            f"Error processing {source} data for year {year}, buffer {buffer_size}m: {e}"
        )

    return result
