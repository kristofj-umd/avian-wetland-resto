"""
stac_imagery_download.py

Search, review, and download satellite imagery from STAC collections.

This script provides a unified workflow for:
  1. Search: Query STAC collections with spatial/temporal/cloud cover filters
  2. Review: Display search results and allow user to export or proceed
  3. Download: Download imagery, optionally mask, clip to AOI, and composite

The script is generic and works with any STAC-compliant API endpoint. It includes
support for interactive user review, CSV/GeoJSON export, temporal compositing, and
pixel quality masking.

Usage:
  python stac_imagery_download.py \\
    --collection <stac_url> \\
    --output-dir <output_path> \\
    --aoi <aoi_file> \\
    --start-date 2020-06-01 \\
    --end-date 2020-08-31 \\
    --cloud-cover 20 \\
    --mask cloud,shadow \\
    --composite
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
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

import stac_utils

# ============================================================================
# Logging Configuration
# ============================================================================
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
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
            item["datetime"] for item in self.items if item.get("datetime") is not None
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
    collection_url: str,
    start_date: Optional[dt.datetime] = None,
    end_date: Optional[dt.datetime] = None,
    cloud_cover_max: Optional[float] = None,
) -> STACSearchResult:
    """
    Search STAC collection for a single AOI feature.

    Parameters
    ----------
    aoi_feature : pd.Series
        Single row from GeoDataFrame with geometry
    aoi_crs : Any
        Coordinate reference system of the AOI geometry
    collection_url : str
        STAC collection URL
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

    # Temporal range
    temporal = None
    if start_date and end_date:
        temporal = (start_date, end_date)

    # Search STAC
    try:
        items = stac_utils.search_stac_collection(
            collection_url=collection_url,
            bbox=bbox,
            temporal=temporal,
            cloud_cover_max=cloud_cover_max,
            max_items=1000,
        )

        # Parse items
        parsed_items = [stac_utils.parse_stac_item(item) for item in items]

        logger.debug(f"Found {len(parsed_items)} items for AOI {aoi_id}")

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
    band_names: Optional[List[str]] = None,
) -> Optional[xr.Dataset]:
    """
    Load STAC item bands and clip to AOI geometry using stackstac.

    Parameters
    ----------
    stac_item : pystac.Item
        STAC item with assets to load
    aoi_geom : Shapely geometry
        AOI polygon
    aoi_crs : str or CRS
        CRS of AOI geometry
    band_names : list of str, optional
        Specific bands to load. If None, loads all available bands.

    Returns
    -------
    xarray.Dataset
        Dataset with clipped bands
    """
    # Convert AOI to GeoDataFrame
    aoi_gdf = gpd.GeoDataFrame([{"geometry": aoi_geom}], crs=aoi_crs)

    # Get the EPSG code from the STAC item (use native projection)
    # Landsat data is typically in UTM projection
    item_epsg = None

    if hasattr(stac_item, "properties") and stac_item.properties:
        # try proj:cdode first, then proj:epsg
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

    # if EPSG code not found, skip this item
    else:
        logger.warning(
            f"Could not determine CRS for item {stac_item.id}, skipping"
        )
        return None

    # Get bounds in native CRS as a 4-element tuple
    minx, miny, maxx, maxy = aoi_native.total_bounds
    bounds = (float(minx), float(miny), float(maxx), float(maxy))

    # Use stackstac to load the STAC item in its native CRS
    # This handles all GDAL configuration and cloud access automatically
    stack = stackstac.stack(
        [stac_item],
        bounds=bounds,
        epsg=item_epsg,  # Use native projection
        assets=band_names,  # Only load specified bands
        chunksize=512,
        dtype=np.dtype("int16"),
        fill_value=-9999,  # Standard nodata value for int16 satellite data
        rescale=False,  # Keep original integer values
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

    return ds


def apply_qa_mask(
    data: xr.DataArray,
    qa_data: xr.DataArray,
    mask_types: List[str],
    nodata_value: int = -9999,
) -> xr.DataArray:
    """
    Apply quality mask to imagery data.

    Parameters
    ----------
    data : xarray.DataArray
        Imagery band data
    qa_data : xarray.DataArray
        Quality assessment band data
    mask_types : list of str
        Bit types to mask (e.g., ['cloud', 'shadow'])
    nodata_value : int
        Value to use for masked pixels (default: -9999)

    Returns
    -------
    xarray.DataArray
        Masked data with masked pixels set to nodata
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
        data_masked = data.where(mask, other=nodata_value)
    else:
        # Mask specified bit types
        for mask_type in mask_types:
            if mask_type in bit_map:
                bit_pos = bit_map[mask_type]
                type_mask = ((qa_uint8 >> bit_pos) & 1) == 1
                mask = mask | type_mask

        data_masked = data.where(~mask, other=nodata_value)

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

    # Set nodata value
    ds = ds.rio.write_nodata(-9999)

    # Set attributes
    ds.attrs["scale_factor"] = 0.0001  # Landsat scale factor
    ds.attrs["add_offset"] = 0.0

    # Create output directory
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write COG
    logger.debug(f"Writing {len(available)}-band COG to {output_path.name}")
    ds.rio.to_raster(str(output_path), driver="COG")


# ============================================================================
# CLI and Main Functions
# ============================================================================


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Search and download imagery from STAC collections",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic search with Landsat
  python stac_imagery_download.py \\
    --collection https://landsatlook.usgs.gov/stac-server \\
    --output-dir ./output \\
    --aoi sites.shp \\
    --start-date 2020-06-01 \\
    --end-date 2020-08-31 \\
    --cloud-cover 20

  # Download and composite
  python stac_imagery_download.py \\
    --collection ... \\
    --output-dir ./output \\
    --aoi sites.shp \\
    --start-date 2020-06-01 \\
    --end-date 2020-08-31 \\
    --mask cloud,shadow \\
    --composite \\
    --log-file
        """,
    )

    # Required arguments
    parser.add_argument(
        "--collection",
        type=str,
        required=True,
        help="STAC collection URL",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for imagery",
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
    print("=" * 70)
    print("STAC Imagery Search and Download")
    print("=" * 70)
    print(f"Collection: {args.collection}")
    print(f"Output directory: {args.output_dir}")

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
                collection_url=args.collection,
                start_date=start_date,
                end_date=end_date,
                cloud_cover_max=args.cloud_cover,
            )
        else:
            # Global search (bounding box of world)
            result = STACSearchResult(
                aoi_id="global",
                aoi_geometry=box(-180, -90, 180, 90),
                aoi_crs="EPSG:4326",
                items=[],
            )
            # Only pass temporal if both dates are provided
            temporal = (start_date, end_date) if start_date and end_date else None
            items = stac_utils.search_stac_collection(
                collection_url=args.collection,
                temporal=temporal,
                cloud_cover_max=args.cloud_cover,
            )
            result.items = [stac_utils.parse_stac_item(item) for item in items]

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

    # Prompt user
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

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Discover bands from first item
    sample_bands = stac_utils.discover_stac_bands(
        args.collection,
        sample_item=None,
    )
    logger.info(f"Available bands: {sample_bands}")

    success_count = 0
    failed_count = 0

    for result in all_results:
        if not result.items or not result.stac_items:
            continue

        # Iterate over both parsed and original STAC items together
        for item_dict, stac_item in tqdm(
            zip(result.items, result.stac_items),
            desc=f"Processing AOI {result.aoi_id}",
            unit="item",
            leave=False,
            total=len(result.items),
        ):
            try:
                item_id = item_dict.get("id")
                item_date = (
                    item_dict.get("datetime").strftime("%Y%m%d")
                    if item_dict.get("datetime")
                    else "unknown"
                )

                # Output filename
                output_file = (
                    args.output_dir
                    / f"{result.aoi_id}_{item_date}_{item_id}_bands.tif"
                )

                # Skip if already exists
                if output_file.exists():
                    logger.debug(f"File already exists: {output_file}")
                    success_count += 1
                    continue

                # Load and clip all bands using stackstac
                try:
                    # Filter sample_bands to only include spectral bands (exclude QA)
                    spectral_bands = [
                        b
                        for b in sample_bands
                        if not any(
                            pattern in b.lower()
                            for pattern in ["qa", "quality", "pixel_qa"]
                        )
                    ]

                    dataset = load_and_clip_item(
                        stac_item=stac_item,
                        aoi_geom=result.aoi_geometry,
                        aoi_crs=result.aoi_crs,
                        band_names=spectral_bands if spectral_bands else None,
                    )

                    # Check if loading failed (returns None when CRS not found)
                    if dataset is None:
                        logger.warning(f"Skipped item {item_id}: CRS not found")
                        failed_count += 1
                        continue

                    # Convert dataset to dictionary of DataArrays for compatibility
                    clipped_bands = {
                        str(var): dataset[var] for var in dataset.data_vars
                    }

                    logger.debug(
                        f"Loaded {len(clipped_bands)} bands for item {item_id}"
                    )

                except Exception as e:
                    logger.warning(f"Failed to load/clip item {item_id}: {e}")
                    failed_count += 1
                    continue

                if not clipped_bands:
                    logger.warning(f"No bands clipped for item {item_id}")
                    failed_count += 1
                    continue

                # Apply QA mask if requested
                if args.mask:
                    try:
                        # Load QA band separately
                        qa_dataset = load_and_clip_item(
                            stac_item=stac_item,
                            aoi_geom=result.aoi_geometry,
                            aoi_crs=result.aoi_crs,
                            band_names=["qa_pixel"],  # Landsat QA band name
                        )

                        # Check if QA loading succeeded
                        if qa_dataset is None:
                            logger.warning(f"Failed to load QA band for {item_id}")
                            continue

                        # Get QA data array
                        qa_data = next(iter(qa_dataset.data_vars.values()))
                        mask_types = [m.strip() for m in args.mask.split(",")]

                        # Apply mask to each band
                        for band_name in clipped_bands:
                            clipped_bands[band_name] = apply_qa_mask(
                                clipped_bands[band_name],
                                qa_data,
                                mask_types,
                            )
                        logger.debug(f"Applied QA mask: {mask_types}")
                    except Exception as e:
                        logger.warning(f"Failed to apply QA mask: {e}")

                # Write stacked COG
                try:
                    stack_and_write_cog(
                        clipped_bands=clipped_bands,
                        output_path=output_file,
                        band_names=list(clipped_bands.keys()),
                    )
                    logger.info(f"✓ Downloaded {item_id} to {output_file.name}")
                    success_count += 1
                except Exception as e:
                    logger.error(f"Failed to write COG for {item_id}: {e}")
                    failed_count += 1

            except Exception as e:
                logger.error(f"Failed to process item: {e}")
                failed_count += 1

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("DOWNLOAD COMPLETE")
    print("=" * 70)
    print(f"Processed: {success_count} successful, {failed_count} failed")
    print("=" * 70)


if __name__ == "__main__":
    main()
