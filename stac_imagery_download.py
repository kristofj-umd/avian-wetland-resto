"""
stac_imagery_download.py

Search, review, and download satellite imagery from Microsoft Planetary Computer
using STAC (SpatioTemporal Asset Catalog) APIs.

Overview
--------
This script provides a unified workflow for acquiring satellite imagery:

  1. SEARCH: Query any STAC collection with spatial, temporal, and cloud cover filters
  2. REVIEW: Display search results and optionally export to CSV/GeoJSON
  3. DOWNLOAD: Download imagery, optionally mask clouds, clip to AOI, and composite

The script supports any Planetary Computer collection with spectral bands (Landsat,
Sentinel-2, NAIP, etc.). Band information, scale factors, and nodata values are
derived dynamically from STAC metadata, making the script collection-agnostic.

Parameters
----------
Required:

  --output-dir PATH
      Directory where output imagery will be saved. Created if it doesn't exist.
      Individual scenes are saved as: aoi{id}_{date}_{item_id}.tif
      Composites are saved as: aoi{id}_{start_date}-{end_date}_composite.tif

Collection Configuration:

  --collection ID
      STAC collection identifier to search. Default: landsat-c2-l2
      Common collections on Planetary Computer:
        - landsat-c2-l2     : Landsat Collection 2 Level-2 (30m, 1982-present)
        - sentinel-2-l2a    : Sentinel-2 Level-2A (10-60m, 2015-present)
        - naip              : NAIP aerial imagery (0.6-1m, US only)
        - cop-dem-glo-30    : Copernicus DEM (30m global)

  --bands BAND1,BAND2,...
      Comma-separated list of band names to download. If omitted, all spectral
      bands (assets with eo:bands metadata) are downloaded.

      Landsat examples: coastal,blue,green,red,nir08,swir16,swir22,lwir11
      Sentinel-2 examples: B02,B03,B04,B05,B06,B07,B08,B8A,B11,B12

  --qa-band NAME
      Name of the quality assessment band used for cloud/shadow masking.
      Default: qa_pixel (Landsat). For Sentinel-2, use: SCL

      If --mask is specified but the QA band is not found in the collection,
      the script will exit with an error listing available assets.

Search Filters:

  --aoi PATH
      Path to area of interest file (GeoJSON, Shapefile, GeoPackage, etc.).
      The AOI defines the spatial extent for the STAC search and is used to
      clip output imagery. Supports any format readable by GeoPandas.

      Multi-feature AOIs are processed independently - each feature gets its
      own search results and output files.

  --aoi-filter COLUMN:VALUE1,VALUE2
      Filter AOI features by attribute values before processing.
      Format: column_name:value1,value2,...

      Example: --aoi-filter site_id:A1,A2,B3
      This would only process features where site_id is A1, A2, or B3.

  --start-date YYYY-MM-DD
      Beginning of temporal search window (inclusive). Required for most
      collections to limit search results.

  --end-date YYYY-MM-DD
      End of temporal search window (inclusive). If omitted with --start-date,
      searches from start date to present.

  --cloud-cover PERCENT
      Maximum cloud cover percentage (0-100). Scenes with cloud cover above
      this threshold are excluded from search results.
      Example: --cloud-cover 20 excludes scenes with >20% clouds.

Processing Options:

  --mask SPEC
      Apply quality masking to remove clouds, shadows, or other artifacts.
      Uses the QA band specified by --qa-band.

      Mask specifications:
        clear-only      : Keep only pixels flagged as clear (most restrictive)
        cloud           : Mask cloud pixels
        shadow          : Mask cloud shadow pixels
        cirrus          : Mask cirrus cloud pixels
        cloud,shadow    : Mask both clouds and shadows (comma-separated)

      Masked pixels are set to NaN in the output.

  --composite
      Create a temporal composite instead of individual scene files.
      All scenes for each AOI are stacked and reduced using median aggregation.
      This is effective for removing residual clouds when combined with --mask.

      Output: Single file per AOI spanning the full date range.
      Without --composite: One file per scene per AOI.

  --rescale
      Convert raw digital numbers (DN) to physical units (surface reflectance
      or temperature) using scale/offset values from STAC raster:bands metadata.

      Without --rescale: Output contains raw DN values (integers).
      With --rescale: Output contains scaled float values.

      Note: Scale factors are read per-band from metadata, so thermal and
      reflectance bands are scaled correctly with their respective factors.

Logging and Automation:

  --log-file
      Write log messages to a file in the output directory.
      File: {output-dir}/stac_imagery_download.log

  --log-level LEVEL
      Set logging verbosity. Choices: DEBUG, INFO, WARNING, ERROR
      Default: INFO

      DEBUG includes detailed band-by-band processing information.

  -y, --yes
      Skip the interactive review prompt and proceed directly to download.
      Useful for scripted/automated workflows.

Output Format
-------------
All outputs are Cloud Optimized GeoTIFFs (COG) in the native CRS of the imagery
(typically UTM for Landsat/Sentinel-2). Each output contains all requested
spectral bands as separate layers.

Examples
--------
Basic Landsat search and download:

  python stac_imagery_download.py \\
    --output-dir ./landsat_output \\
    --aoi study_sites.geojson \\
    --start-date 2023-06-01 \\
    --end-date 2023-08-31 \\
    --cloud-cover 20

Cloud-masked temporal composite:

  python stac_imagery_download.py \\
    --output-dir ./composites \\
    --aoi study_sites.geojson \\
    --start-date 2023-06-01 \\
    --end-date 2023-08-31 \\
    --cloud-cover 30 \\
    --mask clear-only \\
    --composite \\
    --rescale \\
    --yes

Sentinel-2 with specific bands:

  python stac_imagery_download.py \\
    --collection sentinel-2-l2a \\
    --bands B02,B03,B04,B08 \\
    --qa-band SCL \\
    --output-dir ./sentinel_output \\
    --aoi study_sites.geojson \\
    --start-date 2023-06-01 \\
    --end-date 2023-08-31 \\
    --cloud-cover 15 \\
    --mask cloud,shadow

Filter AOI to specific sites:

  python stac_imagery_download.py \\
    --output-dir ./output \\
    --aoi all_sites.shp \\
    --aoi-filter region:north,south \\
    --start-date 2023-01-01 \\
    --end-date 2023-12-31 \\
    --cloud-cover 25
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from osgeo import gdal  # noqa: F401 necessary for rioxarray to import correctly
import rioxarray as rxr
import stackstac
import xarray as xr
from shapely.geometry import box
from tqdm import tqdm

import planetary_computer as pc
from pystac_client import Client

# ============================================================================
# Warning Suppression
# ============================================================================
# Suppress noisy warnings from dask/xarray that occur during normal operation.
# These are re-enabled when --log-level DEBUG is used (see main()).
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*Increasing number of chunks.*")
warnings.filterwarnings("ignore", message=".*invalid value encountered.*")
warnings.filterwarnings("ignore", message=".*All-NaN slice.*")

# ============================================================================
# GDAL Configuration for Cloud Access
# ============================================================================
# Configure GDAL to properly access remote files over HTTP
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
gdal.SetConfigOption(
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.TIF,.tiff,.TIFF"
)
gdal.SetConfigOption("GDAL_HTTP_TIMEOUT", "300")
gdal.SetConfigOption("GDAL_HTTP_MAX_RETRY", "3")
gdal.SetConfigOption("CPL_VSIL_CURL_USE_HEAD", "NO")
gdal.SetConfigOption("GDAL_HTTP_CONNECTTIMEOUT", "120")

# ============================================================================
# Planetary Computer Configuration
# ============================================================================
# Minimal constants - most configuration is now derived from STAC metadata
# or provided via CLI parameters.

# Planetary Computer API endpoint
PC_CATALOG_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

# Default collection (can be overridden via --collection)
DEFAULT_COLLECTION_ID = "landsat-c2-l2"

# Default QA band name (can be overridden via --qa-band)
DEFAULT_QA_BAND = "qa_pixel"

# Cloud cover property name in STAC metadata (standard STAC extension)
CLOUD_COVER_PROPERTY = "eo:cloud_cover"

# ============================================================================
# Logging Configuration
# ============================================================================
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Allow all levels; handler controls output

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)  # Default to INFO; DEBUG via --log-level
    formatter = logging.Formatter("[%(levelname)s] %(funcName)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class STACSearchResult:
    """Result from STAC search for a single AOI feature."""

    aoi_id: Any
    aoi_geometry: Any
    aoi_crs: Any
    items: List[Dict[str, Any]]  # Parsed STAC items
    stac_items: Optional[List[Any]] = None  # Original pystac.Item objects

    def count(self) -> int:
        """Total number of items found."""
        return len(self.items)

    def date_range(self) -> tuple[Optional[dt.datetime], Optional[dt.datetime]]:
        """Date range of found items."""
        if not self.items:
            return None, None
        dates: List[dt.datetime] = [
            item["datetime"]
            for item in self.items
            if item.get("datetime") is not None
        ]
        if not dates:
            return None, None
        return min(dates), max(dates)

    def cloud_cover_stats(self) -> Dict[str, Optional[float]]:
        """Cloud cover statistics."""
        cloud_covers: List[float] = [
            item["cloud_cover"]
            for item in self.items
            if item.get("cloud_cover") is not None
        ]
        if not cloud_covers:
            return {"min": None, "mean": None, "max": None}
        return {
            "min": float(np.min(cloud_covers)),
            "mean": float(np.mean(cloud_covers)),
            "max": float(np.max(cloud_covers)),
        }


# ============================================================================
# Collection Metadata Functions
# ============================================================================


@dataclass
class CollectionInfo:
    """Metadata derived from a STAC collection."""

    collection_id: str
    title: str
    spectral_bands: List[str]  # Asset names with eo:bands
    all_assets: List[str]  # All available asset names
    qa_band: Optional[str]  # Validated QA band name (or None if not found)


def get_collection_info(
    collection_id: str,
    qa_band_name: str = DEFAULT_QA_BAND,
    band_subset: Optional[List[str]] = None,
) -> CollectionInfo:
    """
    Fetch collection metadata and derive spectral bands.

    Connects to Planetary Computer catalog and extracts:
    - Collection title
    - Available spectral bands (assets with eo:bands extension)
    - Validates QA band exists

    Parameters
    ----------
    collection_id : str
        STAC collection ID to fetch
    qa_band_name : str
        Name of QA band to look for (default: qa_pixel)
    band_subset : list of str, optional
        If provided, filter spectral bands to only these names

    Returns
    -------
    CollectionInfo
        Dataclass with collection metadata

    Raises
    ------
    ValueError
        If collection not found
    """
    logger.info(f"Fetching collection metadata for '{collection_id}'")

    catalog = Client.open(PC_CATALOG_URL)
    collection = catalog.get_collection(collection_id)

    if collection is None:
        raise ValueError(f"Collection '{collection_id}' not found at {PC_CATALOG_URL}")

    # Get collection title
    title = collection.title or collection_id

    # Extract item_assets from collection metadata
    item_assets = collection.extra_fields.get("item_assets", {})

    if not item_assets:
        logger.warning(
            f"Collection '{collection_id}' has no item_assets defined. "
            "Will attempt to derive bands from first search result."
        )

    # Identify spectral bands (assets with eo:bands extension)
    spectral_bands = []
    all_assets = list(item_assets.keys())

    for asset_name, asset_def in item_assets.items():
        # Assets with eo:bands are spectral/imagery bands
        if "eo:bands" in asset_def:
            spectral_bands.append(asset_name)

    # Apply band subset filter if provided
    if band_subset:
        filtered = [b for b in band_subset if b in spectral_bands]
        if not filtered:
            available = ", ".join(spectral_bands) if spectral_bands else "none found"
            raise ValueError(
                f"None of the requested bands {band_subset} found in collection. "
                f"Available spectral bands: {available}"
            )
        if len(filtered) < len(band_subset):
            missing = set(band_subset) - set(filtered)
            logger.warning(f"Some requested bands not found: {missing}")
        spectral_bands = filtered

    # Validate QA band
    qa_band = qa_band_name if qa_band_name in all_assets else None

    logger.info(
        f"Collection '{title}': {len(spectral_bands)} spectral bands, "
        f"QA band '{qa_band_name}' {'found' if qa_band else 'NOT found'}"
    )
    logger.debug(f"Spectral bands: {spectral_bands}")

    return CollectionInfo(
        collection_id=collection_id,
        title=title,
        spectral_bands=spectral_bands,
        all_assets=all_assets,
        qa_band=qa_band,
    )


def get_asset_scale_offset_nodata(
    stac_item: Any,
    asset_name: str,
) -> tuple[float, float, Optional[float]]:
    """
    Extract scale, offset, and nodata from a STAC item's asset metadata.

    Uses the raster:bands extension to get per-band scaling information.
    Falls back to sensible defaults if metadata not available.

    Parameters
    ----------
    stac_item : pystac.Item
        STAC item (should be signed for Planetary Computer)
    asset_name : str
        Name of the asset to get metadata for

    Returns
    -------
    tuple of (scale, offset, nodata)
        scale : float - Multiplicative scale factor (default: 1.0)
        offset : float - Additive offset (default: 0.0)
        nodata : float or None - Nodata value (default: None)
    """
    # Defaults if metadata not found
    scale = 1.0
    offset = 0.0
    nodata = None

    if asset_name not in stac_item.assets:
        logger.debug(f"Asset '{asset_name}' not found in item {stac_item.id}")
        return scale, offset, nodata

    asset = stac_item.assets[asset_name]

    # Get raster:bands extension data
    raster_bands = asset.extra_fields.get("raster:bands", [])

    if raster_bands and len(raster_bands) > 0:
        band_info = raster_bands[0]  # First (usually only) band in asset
        scale = band_info.get("scale", 1.0)
        offset = band_info.get("offset", 0.0)
        nodata = band_info.get("nodata", None)

    return scale, offset, nodata


# ============================================================================
# Phase 1: Search Functions
# ============================================================================


def load_aoi_geometries(
    aoi_path: Path,
    aoi_filter: Optional[str] = None,
) -> gpd.GeoDataFrame:
    """
    Load area of interest geometries from file.

    Parameters
    ----------
    aoi_path : Path
        Path to spatial dataset (shapefile, geojson, etc.)
    aoi_filter : str, optional
        Filter criteria in format "column:value1,value2"

    Returns
    -------
    GeoDataFrame
        Features with geometry and attributes

    Raises
    ------
    FileNotFoundError
        If AOI file doesn't exist
    ValueError
        If AOI filter is invalid
    """
    if not aoi_path.exists():
        raise FileNotFoundError(f"AOI file not found: {aoi_path}")

    logger.info(f"Loading AOI geometries from {aoi_path}")
    gdf = gpd.read_file(aoi_path)

    if len(gdf) == 0:
        raise ValueError(f"AOI file is empty: {aoi_path}")

    # Apply filter if specified
    if aoi_filter:
        # Parse filter format: "column:value1,value2"
        parts = aoi_filter.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid AOI filter format: {aoi_filter}")

        col, values_str = parts
        values = [v.strip() for v in values_str.split(",")]

        if col not in gdf.columns:
            raise ValueError(
                f"Filter column '{col}' not found. Available: {list(gdf.columns)}"
            )

        initial_count = len(gdf)
        gdf = gdf[gdf[col].isin(values)]
        logger.info(
            f"Applied filter '{col}' in {values}: {len(gdf)} of {initial_count} features"
        )

    # Fix invalid geometries
    gdf["geometry"] = gdf["geometry"].apply(
        lambda g: g.buffer(0) if g and not g.is_valid else g
    )

    logger.info(f"Loaded {len(gdf)} AOI features with CRS {gdf.crs}")
    return gdf


def search_for_aoi(
    aoi_feature: pd.Series,
    aoi_crs: Any,
    collection_id: str,
    start_date: Optional[dt.datetime] = None,
    end_date: Optional[dt.datetime] = None,
    cloud_cover_max: Optional[float] = None,
) -> STACSearchResult:
    """
    Search Planetary Computer STAC collection for a single AOI feature.

    Uses the PC_CATALOG_URL constant defined at module level.

    Parameters
    ----------
    aoi_feature : pd.Series
        Single row from GeoDataFrame with geometry
    aoi_crs : Any
        Coordinate reference system of the AOI geometry
    collection_id : str
        STAC collection ID to search
    start_date : datetime, optional
        Temporal search start
    end_date : datetime, optional
        Temporal search end
    cloud_cover_max : float, optional
        Maximum cloud cover percentage

    Returns
    -------
    STACSearchResult
        Search results for this AOI
    """
    aoi_id = aoi_feature.name if hasattr(aoi_feature, "name") else "unknown"
    geom = aoi_feature.geometry

    # Convert geometry to bbox in EPSG:4326
    gdf_wgs84 = gpd.GeoSeries([geom], crs=aoi_crs).to_crs("EPSG:4326")
    minx, miny, maxx, maxy = gdf_wgs84.total_bounds
    bbox = (float(minx), float(miny), float(maxx), float(maxy))

    logger.debug(f"Searching AOI {aoi_id} with bbox={bbox}")

    # Search STAC via Planetary Computer
    try:
        # Connect to Planetary Computer catalog
        catalog = Client.open(PC_CATALOG_URL)
        logger.debug(f"Connected to {PC_CATALOG_URL}")

        # Build search parameters
        search_params = {
            "collections": [collection_id],
            "bbox": bbox,
            "max_items": 1000,
        }

        # Add temporal filter if specified
        if start_date and end_date:
            search_params["datetime"] = (
                f"{start_date.isoformat()}/{end_date.isoformat()}"
            )
            logger.debug(f"Temporal filter: {start_date.date()} to {end_date.date()}")

        # Add cloud cover filter if specified
        if cloud_cover_max is not None:
            search_params["query"] = {
                CLOUD_COVER_PROPERTY: {"lt": cloud_cover_max}
            }
            logger.debug(f"Cloud cover filter: < {cloud_cover_max}%")

        # Execute search
        search = catalog.search(**search_params)
        items = list(search.items())

        # Parse items (inline the parse_stac_item logic)
        parsed_items = []
        for item in items:
            # Extract cloud cover from properties
            cloud_cover = None
            if item.properties:
                for key in [CLOUD_COVER_PROPERTY, "cloud_cover", "cloudCover"]:
                    if key in item.properties:
                        cloud_cover = item.properties[key]
                        break

            parsed_items.append({
                "id": item.id,
                "datetime": item.datetime,
                "geometry": item.geometry,
                "bbox": item.bbox,
                "cloud_cover": cloud_cover,
                "collection": (
                    item.collection_id if hasattr(item, "collection_id") else None
                ),
                "properties": item.properties if item.properties else {},
            })

        logger.info(f"Found {len(parsed_items)} items for AOI {aoi_id}")

        return STACSearchResult(
            aoi_id=aoi_id,
            aoi_geometry=geom,
            aoi_crs=aoi_crs,
            items=parsed_items,
            stac_items=items,
        )

    except Exception as e:
        logger.error(f"Search failed for AOI {aoi_id}: {e}")
        return STACSearchResult(
            aoi_id=aoi_id,
            aoi_geometry=geom,
            aoi_crs=aoi_crs,
            items=[],
            stac_items=[],
        )


# ============================================================================
# Phase 2: Review Functions
# ============================================================================


def display_search_summary(results: List[STACSearchResult]) -> None:
    """
    Display summary statistics of search results.

    Parameters
    ----------
    results : list of STACSearchResult
        Results from all AOI searches
    """
    print("\n" + "=" * 70)
    print("STAC SEARCH RESULTS")
    print("=" * 70)

    total_items = sum(r.count() for r in results)
    print(f"Total items found: {total_items}")

    if total_items == 0:
        print("No imagery found matching search criteria.")
        print("=" * 70)
        return

    # Date range
    all_dates = []
    for result in results:
        start, end = result.date_range()
        if start:
            all_dates.append(start)
        if end:
            all_dates.append(end)

    if all_dates:
        print(f"Date range: {min(all_dates).date()} to {max(all_dates).date()}")

    # Cloud cover stats (aggregate across all items)
    all_cloud_covers = []
    for result in results:
        for item in result.items:
            if item.get("cloud_cover") is not None:
                all_cloud_covers.append(item["cloud_cover"])

    if all_cloud_covers:
        print(
            f"Cloud cover: min={np.min(all_cloud_covers):.1f}%, "
            f"mean={np.mean(all_cloud_covers):.1f}%, "
            f"max={np.max(all_cloud_covers):.1f}%"
        )

    # Count by AOI
    print("\nItems by AOI:")
    for result in results:
        print(f"  {result.aoi_id}: {result.count()} items")

    print("=" * 70)


def display_search_items(
    results: List[STACSearchResult], max_rows: int = 50
) -> None:
    """
    Display detailed table of found items.

    Parameters
    ----------
    results : list of STACSearchResult
        Results from all AOI searches
    max_rows : int
        Maximum rows to display (truncate if more)
    """
    print("\nSearch Results Table:")
    print("-" * 70)

    # Build dataframe
    rows = []
    for result in results:
        for item in result.items:
            item_datetime = item.get("datetime")
            rows.append(
                {
                    "AOI": result.aoi_id,
                    "Item ID": item.get("id", "N/A"),
                    "Date": (
                        item_datetime.date()
                        if item_datetime is not None
                        else "N/A"
                    ),
                    "Cloud%": (
                        f"{item.get('cloud_cover'):.1f}"
                        if item.get("cloud_cover") is not None
                        else "N/A"
                    ),
                }
            )

    if not rows:
        print("No items to display")
        return

    df = pd.DataFrame(rows)

    # Display with truncation if needed
    if len(df) > max_rows:
        print(df.head(max_rows).to_string(index=False))
        print(f"\n... and {len(df) - max_rows} more items")
    else:
        print(df.to_string(index=False))


def prompt_user_action() -> str:
    """
    Prompt user for action after search results.

    Returns
    -------
    str
        User choice: 'continue', 'csv', 'geojson', or 'quit'
    """
    print("\n" + "=" * 70)
    print("What would you like to do?")
    print("  1. Continue to download and process imagery")
    print("  2. Export search results to CSV")
    print("  3. Export search results to GeoJSON")
    print("  4. Quit")
    print("=" * 70)

    while True:
        choice = input("\nEnter choice (1-4): ").strip()
        if choice in ["1", "2", "3", "4"]:
            return {"1": "continue", "2": "csv", "3": "geojson", "4": "quit"}[
                choice
            ]
        print("Invalid choice. Please enter 1-4.")


def export_results_csv(
    results: List[STACSearchResult],
    output_path: Path,
) -> None:
    """Export search results to CSV."""
    rows = []
    for result in results:
        for item in result.items:
            item_datetime = item.get("datetime")
            rows.append(
                {
                    "aoi_id": result.aoi_id,
                    "item_id": item.get("id"),
                    "datetime": (
                        item_datetime.isoformat()
                        if item_datetime is not None
                        else None
                    ),
                    "cloud_cover": item.get("cloud_cover"),
                    "bbox": str(item.get("bbox")),
                }
            )

    if rows:
        df = pd.DataFrame(rows)
        df.to_csv(output_path, index=False)
        print(f"\n✓ Results exported to: {output_path.resolve()}")
        logger.info(f"Exported {len(rows)} results to {output_path}")
    else:
        print("\nNo results to export")


def export_results_geojson(
    results: List[STACSearchResult],
    output_path: Path,
) -> None:
    """Export search results to GeoJSON."""
    features = []
    for result in results:
        for item in result.items:
            item_datetime = item.get("datetime")
            features.append(
                {
                    "type": "Feature",
                    "geometry": item.get("geometry"),
                    "properties": {
                        "aoi_id": result.aoi_id,
                        "item_id": item.get("id"),
                        "datetime": (
                            item_datetime.isoformat()
                            if item_datetime is not None
                            else None
                        ),
                        "cloud_cover": item.get("cloud_cover"),
                    },
                }
            )

    if features:
        geojson = {
            "type": "FeatureCollection",
            "features": features,
        }

        import json

        with open(output_path, "w") as f:
            json.dump(geojson, f, indent=2)

        print(f"\n✓ Results exported to: {output_path.resolve()}")
        logger.info(f"Exported {len(features)} features to {output_path}")
    else:
        print("\nNo results to export")


# ============================================================================
# Phase 3: Download and Processing Functions
# ============================================================================


def load_and_clip_item(
    stac_item: Any,
    aoi_geom: Any,
    aoi_crs: Any,
    band_names: List[str],
    apply_scale: bool = False,
) -> Optional[xr.Dataset]:
    """
    Load STAC item bands and clip to AOI geometry using stackstac.

    Loads the specified bands and clips to the AOI geometry. Optionally applies
    per-band scale/offset from STAC raster:bands metadata to convert DN to
    surface reflectance.

    Parameters
    ----------
    stac_item : pystac.Item
        STAC item with assets to load
    aoi_geom : Shapely geometry
        AOI polygon
    aoi_crs : str or CRS
        CRS of AOI geometry
    band_names : list of str
        Bands to load (asset names from collection)
    apply_scale : bool, default=False
        If True, apply per-band scale/offset from raster:bands metadata.
        Default is False (output raw DN values).

    Returns
    -------
    xarray.Dataset
        Dataset with clipped bands (raw DN values, or scaled if apply_scale=True)
    """
    # Convert AOI to GeoDataFrame
    aoi_gdf = gpd.GeoDataFrame([{"geometry": aoi_geom}], crs=aoi_crs)

    # Get the EPSG code from the STAC item (use native projection)
    # Landsat data is typically in UTM projection
    item_epsg = None

    if hasattr(stac_item, "properties") and stac_item.properties:
        # try proj:code first, then proj:epsg
        proj_code = stac_item.properties.get("proj:code")
        if proj_code:
            # Extract EPSG code from proj:code (e.g., "EPSG:32633")
            item_epsg = int(proj_code.split(":")[1])
        else:
            proj_epsg = stac_item.properties.get("proj:epsg")
            if proj_epsg:
                item_epsg = int(proj_epsg)

    # Reproject AOI to match imagery CRS
    if item_epsg:
        aoi_native = aoi_gdf.to_crs(f"EPSG:{item_epsg}")
        logger.debug(f"Item CRS: EPSG:{item_epsg}")
    else:
        # if EPSG code not found, skip this item
        logger.warning(
            f"Could not determine CRS for item {stac_item.id}, skipping"
        )
        return None

    # Get bounds in native CRS as a 4-element tuple
    minx, miny, maxx, maxy = aoi_native.total_bounds
    bounds = (float(minx), float(miny), float(maxx), float(maxy))

    # Sign STAC item URLs for Planetary Computer (adds SAS tokens to Azure blob URLs)
    signed_item = pc.sign(stac_item)

    # Filter requested bands to only those that exist in this item's assets.
    # This handles cross-sensor compositing (e.g., Landsat 5 lacks 'coastal' band).
    item_assets = set(stac_item.assets.keys())
    available_bands = [b for b in band_names if b in item_assets]

    if not available_bands:
        logger.warning(
            f"Item {stac_item.id} has none of the requested bands. "
            f"Requested: {band_names}, Available: {sorted(item_assets)}"
        )
        return None

    if len(available_bands) < len(band_names):
        missing = set(band_names) - set(available_bands)
        logger.debug(
            f"Item {stac_item.id} missing bands: {missing} "
            f"(sensor may not have these bands)"
        )

    # Use stackstac to load the STAC item in its native CRS
    # CRITICAL: rescale=False to get raw DN values, we apply scale/offset manually
    # fill_value=np.nan ensures nodata areas are NaN from the start
    stack = stackstac.stack(
        [signed_item],
        bounds=bounds,
        assets=available_bands,  # Only request bands that exist in this item
        epsg=item_epsg,
        rescale=False,  # IMPORTANT: Don't auto-rescale, we handle it manually
        fill_value=np.nan,
    )

    # Stack has dimensions: (time, band, y, x)
    # Squeeze time dimension since we're loading single item
    stack = stack.squeeze("time", drop=True)

    # Get geometry list for clipping
    geom_list = aoi_native["geometry"].tolist()

    # Clip to AOI geometry
    clipped = stack.rio.clip(geom_list, crs=stack.rio.crs, all_touched=True)

    # Convert to dataset with bands as variables
    ds = clipped.to_dataset(dim="band")

    # Apply per-band scale/offset from STAC raster:bands metadata
    if apply_scale:
        for band_name in available_bands:
            if band_name not in ds.data_vars:
                continue

            scale, offset, nodata = get_asset_scale_offset_nodata(
                stac_item, band_name
            )

            band_data = ds[band_name]

            # Mask nodata values before scaling
            if nodata is not None:
                band_data = band_data.where(band_data != nodata)

            # Apply scale/offset: scaled_value = DN * scale + offset
            if scale != 1.0 or offset != 0.0:
                band_data = band_data * scale + offset
                logger.debug(
                    f"Applied scale={scale}, offset={offset} to band '{band_name}'"
                )

            ds[band_name] = band_data

    return ds


def process_single_item(
    stac_item: Any,
    aoi_geom: Any,
    aoi_crs: Any,
    spectral_bands: List[str],
    qa_band: Optional[str] = None,
    mask_spec: Optional[str] = None,
    apply_scale: bool = False,
) -> Optional[xr.Dataset]:
    """
    Load, clip, and optionally mask a single STAC item.

    This is the core processing function used by both individual and composite
    modes. It handles spectral band loading, QA band loading, and mask application.

    Parameters
    ----------
    stac_item : pystac.Item
        STAC item to process
    aoi_geom : Shapely geometry
        AOI polygon for clipping
    aoi_crs : str or CRS
        CRS of AOI geometry
    spectral_bands : list of str
        Names of spectral bands to load (from collection metadata)
    qa_band : str, optional
        Name of QA band for masking
    mask_spec : str, optional
        Mask specification (e.g., 'cloud,shadow' or 'clear-only')
    apply_scale : bool, default=False
        If True, convert DN to surface reflectance using raster:bands metadata

    Returns
    -------
    xarray.Dataset or None
        Processed dataset, or None if processing failed
    """
    item_id = stac_item.id

    # Load spectral bands
    dataset = load_and_clip_item(
        stac_item=stac_item,
        aoi_geom=aoi_geom,
        aoi_crs=aoi_crs,
        band_names=spectral_bands,
        apply_scale=apply_scale,
    )

    if dataset is None:
        logger.warning(f"Skipped item {item_id}: CRS not found")
        return None

    logger.debug(f"Loaded {len(dataset.data_vars)} bands for item {item_id}")

    # Apply QA mask if requested
    if mask_spec and qa_band:
        qa_dataset = load_and_clip_item(
            stac_item=stac_item,
            aoi_geom=aoi_geom,
            aoi_crs=aoi_crs,
            band_names=[qa_band],
            apply_scale=False,
        )

        if qa_dataset is None:
            logger.warning(f"Failed to load QA band for {item_id}, skipping mask")
        else:
            qa_data = next(iter(qa_dataset.data_vars.values()))
            mask_types = [m.strip() for m in mask_spec.split(",")]

            for var_name in dataset.data_vars:
                dataset[var_name] = apply_qa_mask(
                    dataset[var_name], qa_data, mask_types
                )
            logger.debug(f"Applied QA mask: {mask_types}")

    return dataset


def apply_qa_mask(
    data: xr.DataArray,
    qa_data: xr.DataArray,
    mask_types: List[str],
) -> xr.DataArray:
    """
    Apply quality mask to imagery data.

    Parameters
    ----------
    data : xarray.DataArray
        Imagery band data (float values)
    qa_data : xarray.DataArray
        Quality assessment band data
    mask_types : list of str
        Bit types to mask (e.g., ['cloud', 'shadow'])

    Returns
    -------
    xarray.DataArray
        Masked data with masked pixels set to NaN
    """
    # Landsat QA_PIXEL bit definitions
    bit_map = {
        "cloud": 3,  # Cloud
        "shadow": 4,  # Cloud Shadow
        "cirrus": 2,  # Cirrus
        "clear": 6,  # Clear (quality flag)
    }

    # Create mask
    qa_uint8 = qa_data.astype(np.uint8)
    mask = np.zeros(qa_uint8.shape, dtype=bool)

    if "clear-only" in mask_types:
        # Keep only clear pixels (bit 6 == 1)
        mask = ((qa_uint8 >> 6) & 1) == 1
        data_masked = data.where(mask, other=np.nan)
    else:
        # Mask specified bit types
        for mask_type in mask_types:
            if mask_type in bit_map:
                bit_pos = bit_map[mask_type]
                type_mask = ((qa_uint8 >> bit_pos) & 1) == 1
                mask = mask | type_mask

        data_masked = data.where(~mask, other=np.nan)

    return data_masked


def stack_and_write_cog(
    clipped_bands: Dict[str, xr.DataArray],
    output_path: Path,
    band_names: List[str],
) -> None:
    """
    Stack clipped bands and write as COG.

    Parameters
    ----------
    clipped_bands : dict
        Band name -> clipped DataArray
    output_path : Path
        Output COG file path
    band_names : list of str
        Desired band order
    """
    # Get available bands in order
    available = [b for b in band_names if b in clipped_bands]

    if not available:
        raise ValueError("No bands to stack")

    # Build dataset
    ds = xr.Dataset()
    for band_name in available:
        da = clipped_bands[band_name].copy()
        da.attrs.pop("long_name", None)
        ds[band_name] = da

    # Set CRS and spatial info
    first_band = clipped_bands[available[0]]
    ds = ds.rio.write_crs(first_band.rio.crs)
    ds = ds.rio.set_spatial_dims(x_dim="x", y_dim="y")
    if first_band.rio.transform() is not None:
        ds = ds.rio.write_transform(first_band.rio.transform())

    # Create output directory
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write COG (float32 with NaN for nodata)
    logger.debug(f"Writing {len(available)}-band COG to {output_path.name}")
    ds.rio.to_raster(str(output_path), driver="COG")


def create_temporal_composite(
    datasets: List[xr.Dataset],
    method: str = "median",
) -> Optional[xr.Dataset]:
    """
    Create temporal composite from multiple datasets.

    Stacks datasets along time dimension and aggregates using specified method.
    Handles NaN values gracefully (e.g., from cloud masking).

    Parameters
    ----------
    datasets : list of xarray.Dataset
        Clipped datasets, one per date (each has band variables)
    method : str
        Aggregation method ('median', 'mean', 'max', 'min'). Default: 'median'

    Returns
    -------
    xarray.Dataset or None
        Single composite with bands aggregated across time.
        Returns None if no datasets or no common bands found.
    """
    if not datasets:
        logger.warning("No datasets provided for compositing")
        return None

    # Find common bands across all datasets
    all_bands = [set(ds.data_vars.keys()) for ds in datasets]
    common_bands = set.intersection(*all_bands) if all_bands else set()

    if not common_bands:
        logger.warning("No common bands found across datasets")
        return None

    common_bands = sorted(list(common_bands))
    logger.debug(f"Found {len(common_bands)} common bands for composite")

    # Stack each band along time dimension and aggregate
    composite_vars = {}
    for band_name in common_bands:
        # Get this band from each dataset
        band_arrays = [ds[band_name] for ds in datasets]

        # Stack along new time dimension
        # Use join='inner' to take the intersection of all scene extents.
        # This handles scenes with different coverage (e.g., different paths/rows,
        # or AOI near scene edges). Only pixels present in ALL scenes are kept.
        # coords='minimal' only includes coords that vary across arrays.
        stacked = xr.concat(
            band_arrays, dim="time", join="inner", coords="minimal"
        )

        # Apply aggregation method (skipna=True handles masked pixels)
        if method == "median":
            aggregated = stacked.median(dim="time", skipna=True)
        elif method == "mean":
            aggregated = stacked.mean(dim="time", skipna=True)
        elif method == "max":
            aggregated = stacked.max(dim="time", skipna=True)
        elif method == "min":
            aggregated = stacked.min(dim="time", skipna=True)
        else:
            logger.warning(f"Unknown aggregation method {method}, using median")
            aggregated = stacked.median(dim="time", skipna=True)

        composite_vars[band_name] = aggregated

    # Build composite dataset
    composite = xr.Dataset(composite_vars)

    # Preserve CRS and spatial metadata from first dataset
    first_ds = datasets[0]
    composite = composite.rio.write_crs(first_ds.rio.crs)
    composite = composite.rio.set_spatial_dims(x_dim="x", y_dim="y")
    if first_ds.rio.transform() is not None:
        composite = composite.rio.write_transform(first_ds.rio.transform())

    return composite


# ============================================================================
# CLI and Main Functions
# ============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Search and download STAC imagery from Microsoft Planetary Computer. "
            "Supports any collection with spectral bands (Landsat, Sentinel-2, etc.)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Default collection: {DEFAULT_COLLECTION_ID}
Endpoint: {PC_CATALOG_URL}

Spectral bands are auto-detected from collection metadata (assets with eo:bands).
Scale/offset/nodata values are read from each asset's raster:bands metadata.

Examples:
  # Basic search (Landsat default)
  python stac_imagery_download.py \\
    --output-dir ./output \\
    --aoi sites.geojson \\
    --start-date 2020-06-01 \\
    --end-date 2020-08-31 \\
    --cloud-cover 20

  # Sentinel-2 with specific bands
  python stac_imagery_download.py \\
    --collection sentinel-2-l2a \\
    --bands B02,B03,B04,B08 \\
    --output-dir ./output \\
    --aoi sites.geojson \\
    --start-date 2020-06-01 \\
    --end-date 2020-08-31

  # Download with cloud masking and compositing
  python stac_imagery_download.py \\
    --output-dir ./output \\
    --aoi sites.geojson \\
    --start-date 2020-06-01 \\
    --end-date 2020-08-31 \\
    --mask clear-only \\
    --composite \\
    --yes
        """,
    )

    # Required arguments
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for imagery",
    )

    # Collection configuration
    parser.add_argument(
        "--collection",
        type=str,
        default=DEFAULT_COLLECTION_ID,
        help=f"STAC collection ID (default: {DEFAULT_COLLECTION_ID})",
    )
    parser.add_argument(
        "--bands",
        type=str,
        default=None,
        help=(
            "Comma-separated list of bands to download (default: all spectral bands). "
            "Example: --bands coastal,blue,green,red,nir08"
        ),
    )
    parser.add_argument(
        "--qa-band",
        type=str,
        default=DEFAULT_QA_BAND,
        help=f"QA band name for masking (default: {DEFAULT_QA_BAND})",
    )

    # Optional search filters
    parser.add_argument(
        "--aoi",
        type=Path,
        default=None,
        help="Path to AOI spatial dataset (shapefile, geojson, etc.)",
    )
    parser.add_argument(
        "--aoi-filter",
        type=str,
        default=None,
        help="Filter AOI by attribute (format: column:value1,value2)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date for search (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date for search (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--cloud-cover",
        type=float,
        default=None,
        help="Maximum cloud cover percentage (0-100)",
    )

    # Optional processing
    parser.add_argument(
        "--mask",
        type=str,
        default=None,
        help="Pixel types to mask (e.g., 'cloud,shadow' or 'clear-only')",
    )
    parser.add_argument(
        "--composite",
        action="store_true",
        help="Create temporal median composite",
    )
    parser.add_argument(
        "--rescale",
        action="store_true",
        help="Convert DN to surface reflectance (default: output raw DN values)",
    )

    # Other options
    parser.add_argument(
        "--log-file",
        action="store_true",
        help="Enable logging to file in output directory",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Auto-proceed with download (skip user prompt)",
    )

    return parser.parse_args()


def main() -> None:
    """Main workflow: search -> review -> download."""
    args = parse_args()

    # =========================================================================
    # Setup logging
    # =========================================================================
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logger.setLevel(log_level)
    for handler in logger.handlers:
        handler.setLevel(log_level)

    # Re-enable suppressed warnings at DEBUG level
    if log_level == logging.DEBUG:
        warnings.resetwarnings()

    if args.log_file:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        log_path = args.output_dir / "stac_imagery_download.log"
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(log_level)
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(funcName)s: %(message)s"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info(f"Logging to {log_path}")

    # =========================================================================
    # Parse and validate arguments
    # =========================================================================

    # Parse band subset if provided
    band_subset = None
    if args.bands:
        band_subset = [b.strip() for b in args.bands.split(",")]

    # Fetch collection metadata
    print("=" * 70)
    print("STAC Imagery Download")
    print("=" * 70)
    print(f"Fetching collection metadata for '{args.collection}'...")

    try:
        collection_info = get_collection_info(
            collection_id=args.collection,
            qa_band_name=args.qa_band,
            band_subset=band_subset,
        )
    except ValueError as e:
        print(f"\nError: {e}")
        return

    print(f"Collection: {collection_info.title} ({collection_info.collection_id})")
    print(f"Endpoint:   {PC_CATALOG_URL}")
    print(f"Output:     {args.output_dir}")
    print(f"Bands:      {len(collection_info.spectral_bands)} spectral bands")
    if collection_info.spectral_bands:
        print(f"            [{', '.join(collection_info.spectral_bands)}]")

    # Validate QA band if masking is requested
    if args.mask:
        if collection_info.qa_band is None:
            print(f"\nError: Masking requested (--mask {args.mask}) but QA band "
                  f"'{args.qa_band}' was not found in collection '{args.collection}'.")
            print(f"\nAvailable assets in this collection:")
            for asset_name in sorted(collection_info.all_assets):
                print(f"  - {asset_name}")
            print(f"\nTo fix this, either:")
            print(f"  1. Specify the correct QA band name with --qa-band <name>")
            print(f"  2. Remove the --mask option to skip masking")
            return
        else:
            print(f"QA band:    {collection_info.qa_band}")

    # Parse dates
    start_date = None
    end_date = None
    if args.start_date:
        start_date = dt.datetime.fromisoformat(args.start_date).replace(
            tzinfo=dt.timezone.utc
        )
    if args.end_date:
        end_date = dt.datetime.fromisoformat(args.end_date).replace(
            tzinfo=dt.timezone.utc
        )

    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must be before end_date")

    # =========================================================================
    # Phase 1: Search
    # =========================================================================
    print("\nPhase 1: Searching for imagery...")

    # Load AOI if provided
    aoi_crs = None
    if args.aoi:
        gdf = load_aoi_geometries(args.aoi, args.aoi_filter)
        aoi_features = list(gdf.iterrows())
        aoi_crs = gdf.crs
    else:
        # Search without AOI
        aoi_features = [(0, pd.Series({"name": "global"}))]
        aoi_crs = "EPSG:4326"

    # Search for each AOI feature
    all_results = []
    for idx, feature in tqdm(aoi_features, desc="Searching", unit="AOI"):
        if args.aoi:
            result = search_for_aoi(
                aoi_feature=feature,
                aoi_crs=aoi_crs,
                collection_id=collection_info.collection_id,
                start_date=start_date,
                end_date=end_date,
                cloud_cover_max=args.cloud_cover,
            )
        else:
            # Global search requires an AOI - prompt user
            print("\nError: --aoi is required. Global search is not supported.")
            print("Please provide an AOI file with --aoi option.")
            return

        all_results.append(result)

    # =========================================================================
    # Phase 2: Review
    # =========================================================================
    display_search_summary(all_results)

    total_items = sum(r.count() for r in all_results)
    if total_items == 0:
        print("\n[No imagery found matching search criteria]")
        return

    display_search_items(all_results)

    # Prompt user (or auto-proceed if --yes flag is set)
    if args.yes:
        action = "continue"
        print("\n[Auto-proceeding with download (--yes flag)]")
    else:
        action = prompt_user_action()

    if action == "csv":
        csv_path = args.output_dir / "search_results.csv"
        export_results_csv(all_results, csv_path)
        return

    if action == "geojson":
        geojson_path = args.output_dir / "search_results.geojson"
        export_results_geojson(all_results, geojson_path)
        return

    if action == "quit":
        print("\n[Search cancelled by user]")
        return

    # =========================================================================
    # Phase 3: Download and Process
    # =========================================================================
    print("\nPhase 3: Downloading and processing imagery...")
    print("-" * 70)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    success_count = 0
    failed_count = 0
    skipped_count = 0

    # Count total items and AOIs with data
    aois_with_data = [r for r in all_results if r.items and r.stac_items]
    total_aois = len(aois_with_data)

    # =========================================================================
    # Process each AOI
    # =========================================================================
    for aoi_idx, result in enumerate(aois_with_data, 1):
        # Collect datasets and dates for this AOI
        aoi_datasets: List[xr.Dataset] = []
        item_dates: List[str] = []

        # Print AOI header
        mode_label = "composite" if args.composite else "individual files"
        print(f"\n[AOI {aoi_idx}/{total_aois}] Processing AOI {result.aoi_id} "
              f"({len(result.items)} items → {mode_label})")

        # Process each item with progress bar
        for item_dict, stac_item in tqdm(
            zip(result.items, result.stac_items),
            desc="  Downloading",
            unit="scene",
            leave=True,
            total=len(result.items),
            ncols=70,
        ):
            try:
                item_id = item_dict.get("id")
                item_date = (
                    item_dict.get("datetime").strftime("%Y%m%d")
                    if item_dict.get("datetime")
                    else "unknown"
                )
                item_dates.append(item_date)

                # For individual mode, check if output already exists
                if not args.composite:
                    output_file = (
                        args.output_dir
                        / f"aoi{result.aoi_id}_{item_date}_{item_id}.tif"
                    )
                    if output_file.exists():
                        logger.debug(f"File already exists: {output_file}")
                        skipped_count += 1
                        continue

                # Process the item (load, clip, mask)
                try:
                    dataset = process_single_item(
                        stac_item=stac_item,
                        aoi_geom=result.aoi_geometry,
                        aoi_crs=result.aoi_crs,
                        spectral_bands=collection_info.spectral_bands,
                        qa_band=collection_info.qa_band,
                        mask_spec=args.mask,
                        apply_scale=args.rescale,
                    )

                    if dataset is None:
                        failed_count += 1
                        continue

                except Exception as e:
                    logger.warning(f"Failed to process item {item_id}: {e}")
                    failed_count += 1
                    continue

                # Handle output based on mode
                if args.composite:
                    # Collect for later compositing
                    aoi_datasets.append(dataset)
                    success_count += 1
                else:
                    # Write individual file immediately
                    try:
                        clipped_bands = {
                            str(var): dataset[var] for var in dataset.data_vars
                        }
                        stack_and_write_cog(
                            clipped_bands=clipped_bands,
                            output_path=output_file,
                            band_names=list(clipped_bands.keys()),
                        )
                        logger.debug(f"Wrote {output_file.name}")
                        success_count += 1
                    except Exception as e:
                        tqdm.write(f"  ✗ Failed to write {item_id}: {e}")
                        failed_count += 1

            except Exception as e:
                tqdm.write(f"  ✗ Failed to process item: {e}")
                failed_count += 1

        # Create composite if in composite mode
        if args.composite and aoi_datasets:
            print(f"  Creating median composite from {len(aoi_datasets)} scenes...")
            try:
                min_date = min(item_dates) if item_dates else "unknown"
                max_date = max(item_dates) if item_dates else "unknown"

                composite = create_temporal_composite(aoi_datasets, method="median")

                if composite is None:
                    print(f"  ✗ Failed to create composite for AOI {result.aoi_id}")
                    failed_count += 1
                    continue

                output_file = (
                    args.output_dir
                    / f"aoi{result.aoi_id}_{min_date}-{max_date}_composite.tif"
                )

                print(f"  Writing COG: {output_file.name}")
                output_file.parent.mkdir(parents=True, exist_ok=True)
                composite.rio.to_raster(str(output_file), driver="COG")
                print(f"  ✓ Composite saved: {output_file.name}")

            except Exception as e:
                print(f"  ✗ Failed to create/write composite: {e}")
                failed_count += 1

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)
    print(f"  Successful: {success_count}")
    if skipped_count > 0:
        print(f"  Skipped (already exist): {skipped_count}")
    if failed_count > 0:
        print(f"  Failed: {failed_count}")
    print(f"  Output directory: {args.output_dir.resolve()}")
    print("=" * 70)


if __name__ == "__main__":
    main()
