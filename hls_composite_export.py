"""
hls_composite_export.py

Export HLS imagery as clipped, composited Cloud-Optimized GeoTIFFs (COGs).

This script processes search results from hls_imagery_search_earthaccess.py and creates
multi-band spectral composites clipped to site polygons. Each granule produces two COG files:
- A multi-band spectral composite with all available bands
- A separate single-band Fmask quality file

Workflow:
  1. Read search results CSV (from hls_imagery_search_earthaccess.py)
  2. Filter to rows with valid granule_id
  3. For each row:
     - Re-query NASA CMR to get band URLs
     - Open each spectral band via cloud COG access
     - Clip to site polygon (+ optional buffer)
     - Stack bands and write as COG
     - Clip and write Fmask as separate COG

Output Files:
  - {site_id}_{year}_{product}_composite.tif - Multi-band spectral COG
  - {site_id}_{year}_{product}_fmask.tif - Single-band Fmask COG

Command-line Parameters:
  --input-csv PATH       Path to search results CSV (required)
  --output-dir PATH      Directory for output COGs (required)
  --buffer-meters N      Buffer around site polygon in meters (default: 0)
  --sites IDS            Comma-separated site IDs to process (optional)
  --log-level LEVEL      DEBUG|INFO|WARNING|ERROR (default: INFO)

Requirements:
  - NASA Earthdata credentials in ~/.netrc or ~/_netrc
  - Sites shapefile at configured path
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import geopandas as gpd
from osgeo import gdal  # Must import before rasterio on this system
import rasterio
import rioxarray as rxr
import xarray as xr
from shapely.geometry import mapping
from tqdm import tqdm

import earthaccess

# Import shared utilities
import hls_utils

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


# Note: Configuration constants moved to hls_utils module


# Note: Site geometry loading, CMR query functions moved to hls_utils module


# ============================================================================
# Raster Processing Functions
# ============================================================================


def clip_band_to_site(
    band_url: str,
    site_geom,
    site_geom_crs,
    buffer_meters: float = 0,
) -> xr.DataArray:
    """
    Open a band via cloud COG access and clip to site geometry.

    Args:
        band_url: URL to the band COG
        site_geom: Shapely geometry (polygon or multipolygon)
        site_geom_crs: CRS of site geometry
        buffer_meters: Buffer to add around site (default 0)

    Returns:
        Clipped xarray DataArray (int16, NOT scaled)
    """
    # Chunking for efficient cloud access
    chunk_size = {"band": 1, "x": 512, "y": 512}

    # Open band with rioxarray (cloud COG access)
    band_da = rxr.open_rasterio(band_url, chunks=chunk_size, masked=True)
    band_da = band_da.squeeze("band", drop=True)

    # Transform site geometry to raster CRS
    site_gdf = gpd.GeoSeries([site_geom], crs=site_geom_crs)
    site_utm = site_gdf.to_crs(band_da.rio.crs)
    geom_utm = site_utm.iloc[0]

    # Apply buffer if specified
    if buffer_meters > 0:
        geom_utm = geom_utm.buffer(buffer_meters)

    # Clip to geometry
    clipped = band_da.rio.clip([geom_utm], band_da.rio.crs, all_touched=True)

    return clipped


def stack_bands_to_cog(
    clipped_bands: Dict[str, xr.DataArray],
    output_path: Path,
    band_order: List[str],
    band_name_lookup: Dict[str, str],
) -> None:
    """
    Stack clipped bands into a multi-band COG with named bands.

    Args:
        clipped_bands: Dict mapping band code to clipped DataArray
        output_path: Path for output COG file
        band_order: List of band codes in desired order
        band_name_lookup: Dict mapping band codes to descriptive names
    """
    # Get available bands in order (skip missing)
    available_bands = [b for b in band_order if b in clipped_bands]

    if not available_bands:
        raise ValueError("No bands to stack")

    # Build xarray.Dataset with descriptive band names as variable names
    # This pattern ensures band names are preserved in the output COG
    ds = xr.Dataset()
    for band_code in available_bands:
        descriptive_name = band_name_lookup.get(band_code, band_code)
        da = clipped_bands[band_code].copy()
        # Clear inherited attributes that might cause issues
        da.attrs.pop("long_name", None)
        ds[descriptive_name] = da

    # Copy CRS and spatial info from first band
    first_band = clipped_bands[available_bands[0]]
    ds = ds.rio.write_crs(first_band.rio.crs)
    ds = ds.rio.set_spatial_dims(x_dim="x", y_dim="y")
    if first_band.rio.transform() is not None:
        ds = ds.rio.write_transform(first_band.rio.transform())

    # Set common attributes (HLS reflectance scaling)
    ds.attrs["scale_factor"] = hls_utils.HLS_SCALE_FACTOR
    ds.attrs["add_offset"] = 0.0

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write Dataset as multi-band COG (variable names become band descriptions)
    logger.debug(
        f"Writing {len(available_bands)}-band COG to {output_path.name}"
    )
    ds.rio.to_raster(str(output_path), driver="COG")


def write_fmask_cog(
    fmask_da: xr.DataArray,
    output_path: Path,
) -> None:
    """
    Write Fmask as a single-band COG.

    Args:
        fmask_da: Clipped Fmask DataArray
        output_path: Path for output COG file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Writing Fmask COG to {output_path.name}")
    fmask_da.rio.to_raster(str(output_path), driver="COG")


# ============================================================================
# Main Processing Function
# ============================================================================


def process_granule(
    row: pd.Series,
    geom_by_id: Dict,
    geom_crs,
    output_dir: Path,
    buffer_meters: float,
) -> Tuple[bool, str]:
    """
    Process a single granule: query, clip, stack, and export.

    Args:
        row: DataFrame row with site_id, year, product, granule_id, sensing_time_utc
        geom_by_id: Dict mapping site_id to geometry
        geom_crs: CRS of geometries
        output_dir: Output directory
        buffer_meters: Buffer around site polygon

    Returns:
        Tuple of (success: bool, message: str)
    """
    site_id = row["site_id"]
    year = row["year"]
    product = row["product"]
    granule_id = row["granule_id"]

    # Extract date in yyyymmdd format from sensing_time_utc
    sensing_time = row.get("sensing_time_utc")
    if sensing_time:
        # Parse ISO format timestamp and extract date
        date_str = str(sensing_time).split("T")[0].replace("-", "")
    else:
        date_str = str(year)  # Fallback to year if sensing_time_utc is missing

    # Define output paths
    product_short = "L30" if product == "Landsat" else "S30"
    composite_path = (
        output_dir / f"{site_id}_{date_str}_{product_short}_composite.tif"
    )
    fmask_path = output_dir / f"{site_id}_{date_str}_{product_short}_fmask.tif"

    # Skip if already exists
    if composite_path.exists() and fmask_path.exists():
        return True, "Already exists"

    # Get site geometry
    site_geom = geom_by_id.get(site_id)
    if site_geom is None:
        return False, f"No geometry for site {site_id}"

    # Re-query CMR for band URLs
    granule = hls_utils.find_granule_by_id(granule_id)
    if granule is None:
        return False, f"Granule not found in CMR: {granule_id}"

    band_urls, fmask_url = hls_utils.get_all_band_urls(granule, product)
    if not band_urls:
        return False, f"No band URLs found for {granule_id}"

    # Clip each spectral band
    clipped_bands = {}
    band_order = hls_utils.PRODUCT_BANDS[product]
    band_name_lookup = hls_utils.PRODUCT_BAND_NAMES[product]

    for band_name in band_order:
        if band_name not in band_urls:
            logger.warning(f"Missing band {band_name} for {granule_id}")
            continue

        try:
            clipped = clip_band_to_site(
                band_urls[band_name], site_geom, geom_crs, buffer_meters
            )
            clipped_bands[band_name] = clipped
        except Exception as e:
            logger.warning(
                f"Failed to clip {band_name}: {type(e).__name__}: {e}"
            )

    if not clipped_bands:
        return False, "No bands successfully clipped"

    # Stack and write spectral composite COG
    try:
        stack_bands_to_cog(
            clipped_bands, composite_path, band_order, band_name_lookup
        )
    except Exception as e:
        return False, f"Failed to write composite: {type(e).__name__}: {e}"

    # Clip and write Fmask COG
    if fmask_url:
        try:
            fmask_clipped = clip_band_to_site(
                fmask_url, site_geom, geom_crs, buffer_meters
            )
            write_fmask_cog(fmask_clipped, fmask_path)
        except Exception as e:
            logger.warning(f"Failed to process Fmask: {type(e).__name__}: {e}")
            # Don't fail the whole granule for Fmask issues
    else:
        logger.warning(f"No Fmask URL found for {granule_id}")

    return True, f"Exported {len(clipped_bands)} bands"


# ============================================================================
# CLI Interface
# ============================================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export HLS imagery as clipped, composited COG GeoTIFFs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python hls_composite_export.py --input-csv hls_site_results.csv --output-dir output/composites

  # With buffer around sites
  python hls_composite_export.py --input-csv results.csv --output-dir composites --buffer-meters 100

  # Filter to specific sites
  python hls_composite_export.py --input-csv results.csv --output-dir composites --sites 22,23,28
        """,
    )

    parser.add_argument(
        "--input-csv",
        type=Path,
        required=True,
        help="Path to search results CSV from hls_imagery_search_earthaccess.py",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for output COG GeoTIFFs",
    )
    parser.add_argument(
        "--buffer-meters",
        type=float,
        default=0,
        help="Buffer distance (meters) around site polygon (default: 0)",
    )
    parser.add_argument(
        "--sites",
        type=str,
        default=None,
        help="Comma-separated site IDs to process (default: all)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )

    return parser.parse_args()


def main() -> None:
    """
    Main function to export HLS composites.
    """
    args = parse_args()

    # Configure logging level
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logger.setLevel(log_level)
    for handler in logger.handlers:
        handler.setLevel(log_level)

    input_csv = args.input_csv
    output_dir = args.output_dir
    buffer_meters = args.buffer_meters

    # Validate inputs
    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")
    if not hls_utils.SITES_SHAPEFILE.exists():
        raise FileNotFoundError(f"Sites shapefile not found: {hls_utils.SITES_SHAPEFILE}")

    # Parse site filter
    site_filter = None
    if args.sites:
        site_filter = {
            int(x.strip()) if x.strip().isdigit() else x.strip()
            for x in args.sites.split(",")
            if x.strip()
        }

    # Print configuration
    print("=" * 70)
    print("HLS Composite Export")
    print("=" * 70)
    print(f"Input CSV: {input_csv}")
    print(f"Output directory: {output_dir}")
    print(f"Buffer: {buffer_meters} meters")
    if site_filter:
        print(f"Site filter: {len(site_filter)} sites")
    print()

    # Configure GDAL for cloud access
    hls_utils.configure_gdal_for_nasa()

    # Authenticate with NASA Earthdata
    print("Authenticating with NASA Earthdata...")
    earthaccess.login(strategy="netrc")
    print("[OK] Authentication successful\n")

    # Load site geometries
    geom_gdf = hls_utils.load_site_geometries(hls_utils.SITES_SHAPEFILE, "SITE")
    geom_by_id = dict(
        zip(geom_gdf["SITE"].tolist(), geom_gdf.geometry.tolist())
    )
    geom_crs = geom_gdf.crs

    # Load input CSV
    print(f"\nLoading search results from {input_csv}...")
    df = pd.read_csv(input_csv)
    print(f"[OK] Loaded {len(df)} rows\n")

    # Filter to rows with valid granule_id
    df = df[df["granule_id"].notna() & (df["granule_id"] != "")]
    print(f"Rows with valid granule_id: {len(df)}")

    # Apply site filter if specified
    if site_filter:
        df = df[df["site_id"].isin(site_filter)]
        print(f"After site filter: {len(df)} rows")

    if len(df) == 0:
        print("\n[WARNING] No rows to process")
        return

    print(f"\nProcessing {len(df)} granules...\n")

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process each granule
    success_count = 0
    failed_count = 0
    failed_rows = []

    with tqdm(total=len(df), desc="Exporting", unit="granule") as pbar:
        for idx, row in df.iterrows():
            try:
                success, message = process_granule(
                    row, geom_by_id, geom_crs, output_dir, buffer_meters
                )
                site_id = row["site_id"]
                year = row["year"]
                if success:
                    success_count += 1
                    logger.debug(f"Site {site_id}/{year}: {message}")
                else:
                    failed_count += 1
                    logger.warning(f"Site {site_id}/{year}: {message}")
                    failed_rows.append({**row.to_dict(), "error": message})
            except Exception as e:
                failed_count += 1
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(f"Unexpected error for row {idx}: {error_msg}")
                failed_rows.append({**row.to_dict(), "error": error_msg})

            pbar.update(1)
            pbar.set_postfix(
                {
                    "success": success_count,
                    "failed": failed_count,
                }
            )

    # Export failed rows if any
    if failed_rows:
        failed_csv = output_dir / "failed_exports.csv"
        pd.DataFrame(failed_rows).to_csv(failed_csv, index=False)
        print(f"\n[WARNING] Failed exports logged to: {failed_csv}")

    # Print summary
    print(f"\n{'='*70}")
    print("EXPORT COMPLETE")
    print(f"{'='*70}")
    print(f"Total processed: {len(df)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {failed_count}")
    print(f"Output directory: {output_dir.resolve()}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
