"""
hls_imagery_search_earthaccess.py

Search for HLS v2 imagery matching site polygons and evaluate cloud cover.

This script queries NASA's Common Metadata Repository (CMR) for Harmonized Landsat-Sentinel-2
(HLS) granules within a temporal search window around June 20 (peak growing season). For each
candidate granule, it downloads the Fmask quality band and computes per-site cloud statistics
using bitwise decoding of quality flags.

Workflow:
  1. Query CMR for L30 (Landsat) and S30 (Sentinel-2) granules within ±N days of June 20
  2. Sort candidates by temporal proximity to target date
  3. Download Fmask GeoTIFF for each candidate
  4. Clip to site polygon and compute individual quality metrics:
     - Cloud percentage (Bit 1)
     - Adjacent to cloud/shadow percentage (Bit 2)
     - Shadow percentage (Bit 3)
     - Combined cloudy percentage (union of above)
  5. Filter candidates: discard any with cloud_pct > 90%
  6. Apply hard-cap temporal filtering if specified
  7. Export results to CSV with status labels

Output CSV Files (by status):
  - "found": Site/years with 0% cloudy imagery (single best match per site/year)
  - "not-found": Site/years with candidates but none within hard-cap window (if --hard-cap used)
  - "none-found": Site/years with no suitable candidates passing quality filters

Command-line Parameters:
  --years YEARS              Comma-separated years (default: 2013,2015,2020,2025)
  --window-days N            ±days around June 20 to search (default: 45)
  --out-csv PATH             Output CSV path (default: hls_site_results.csv)
  --test-sites IDS           Comma-separated site IDs to limit search (optional)
  --hard-cap N               Max days from June 20 for "found" status (optional)
  --log-level LEVEL          Logging verbosity: DEBUG|INFO|WARNING|ERROR|CRITICAL (default: DEBUG)

Requirements:
  - NASA Earthdata credentials in ~/.netrc (Windows) or _netrc (Unix)
  - Sites spreadsheet: data/sites_2025.11.20.xlsx
  - Sites shapefile: data/sites_v2024-08-02-*/sites_v2024-08-02/sites_all_polygons.shp
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd
import geopandas as gpd
from osgeo import gdal  # Must import before rasterio on this system
import rasterio
from rasterio.mask import mask
from shapely.geometry import mapping, box
from tqdm import tqdm
import requests

import earthaccess

# Import shared utilities
import hls_utils

# ============================================================================
# Logging Configuration
# ============================================================================
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Only add handlers if not already configured (prevents duplicate logs)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("[%(levelname)s] %(funcName)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# ============================================================================
# Configuration Constants
# ============================================================================

# Target date for imagery search (peak growing season in northern hemisphere)
TARGET_MONTH = 6  # June
TARGET_DAY = 20  # Approximate peak greenness

# Maximum number of granules to retrieve per CMR query
# Prevents overloading the API and excessive processing time
MAX_GRANULES = 200


@dataclass(frozen=True)
class Candidate:
    """A candidate HLS granule for a site/year."""

    product: str  # "L30" or "S30"
    granule_id: str  # human-readable ID / UR
    start_time_utc: dt.datetime  # acquisition time start
    abs_days_from_target: int  # |days| from target date
    data_links: List[str]  # candidate file links


def fmask_cloud_stats(
    fmask_path: Path,
    geom: Any,
    geom_crs: Any,
) -> dict:
    """
    Compute individual quality bit percentages within site polygon using Fmask bitmask.

    HLS Fmask uses bit flags to encode multiple quality attributes in a single byte:
    - Bit 1: Cloud
    - Bit 2: Adjacent to cloud/shadow
    - Bit 3: Cloud shadow

    This function decodes each bit separately and returns individual percentages.

    Also validates that the site polygon is fully covered by the tile. If the site
    extends beyond the tile boundary, the cloud statistics would be misleading.

    Args:
      fmask_path: Path to Fmask GeoTIFF
      geom: Site geometry (polygon or multipolygon)
      geom_crs: CRS of the site geometry

    Returns:
      dict with keys: cloud_pct, adjacent_pct, shadow_pct, cloudy_pct (sum), sufficient_coverage
    """
    try:
        with rasterio.open(fmask_path) as src:
            # Reproject site geometry to match Fmask raster CRS (typically UTM)
            geom_gdf = gpd.GeoSeries([geom], crs=geom_crs).to_crs(src.crs)
            geom_utm = geom_gdf.values[0]  # Get shapely geometry object

            # -------------------------------------------------------------------------
            # Coverage validation: ensure the entire site polygon is within the tile
            # -------------------------------------------------------------------------
            # Use spatial predicate to check if raster bounds fully cover the site
            # This is more robust than area-based calculations
            raster_bounds = box(
                *src.bounds
            )  # Create polygon from raster bounds
            sufficient_coverage = raster_bounds.covers(geom_utm)

            # Skip processing if site extends beyond tile boundary
            if not sufficient_coverage:
                logger.debug(f"Insufficient coverage for {fmask_path.name}")
                return {
                    "cloud_pct": np.nan,
                    "adjacent_pct": np.nan,
                    "shadow_pct": np.nan,
                    "cloudy_pct": np.nan,
                    "sufficient_coverage": False,
                }

            # Clip Fmask to site geometry and read as masked array
            geoms = [mapping(geom_utm)]
            out, _ = mask(src, geoms, crop=True, filled=False)
            arr = out[0]  # MaskedArray with .data and .mask attributes

            # Count valid (non-masked) pixels within the site
            valid = ~arr.mask
            n_valid = int(valid.sum())
            if n_valid == 0:
                logger.debug(f"No valid pixels in {fmask_path.name}")
                return {
                    "cloud_pct": np.nan,
                    "adjacent_pct": np.nan,
                    "shadow_pct": np.nan,
                    "cloudy_pct": np.nan,
                    "sufficient_coverage": False,
                }

            # Convert to uint8 for bitwise operations
            data = arr.data.astype(np.uint8)

            # -------------------------------------------------------------------------
            # Decode individual bit flags
            # -------------------------------------------------------------------------
            # Bit 1: Cloud
            cloud_mask = ((data >> 1) & 1) == 1
            cloud_pct = (
                float((cloud_mask & valid).sum()) * 100.0 / float(n_valid)
            )

            # Bit 2: Adjacent to cloud/shadow
            adjacent_mask = ((data >> 2) & 1) == 1
            adjacent_pct = (
                float((adjacent_mask & valid).sum()) * 100.0 / float(n_valid)
            )

            # Bit 3: Cloud shadow
            shadow_mask = ((data >> 3) & 1) == 1
            shadow_pct = (
                float((shadow_mask & valid).sum()) * 100.0 / float(n_valid)
            )

            # Combined: any of the three quality issues
            cloudy_mask = cloud_mask | adjacent_mask | shadow_mask
            cloudy_pct = (
                float((cloudy_mask & valid).sum()) * 100.0 / float(n_valid)
            )

            return {
                "cloud_pct": cloud_pct,
                "adjacent_pct": adjacent_pct,
                "shadow_pct": shadow_pct,
                "cloudy_pct": cloudy_pct,
                "sufficient_coverage": sufficient_coverage,
            }
    except Exception as e:
        logger.error(
            f"Error processing Fmask {fmask_path.name}: {type(e).__name__}: {e}"
        )
        return {
            "cloud_pct": np.nan,
            "adjacent_pct": np.nan,
            "shadow_pct": np.nan,
            "cloudy_pct": np.nan,
            "sufficient_coverage": False,
        }


def download_with_session(
    req_session,
    url: str,
    dst: Path,
    chunk_size: int = 1024 * 1024,
    retries: int = 3,
    backoff_s: float = 2.0,
) -> Path:
    """
    Download a URL using an authenticated requests session with pause-and-retry logic.

    Explicitly handles timeouts with pause-and-retry (3 attempts).
    Other errors are also retried with exponential backoff.

    Args:
        req_session: authenticated requests session
        url: URL to download
        dst: destination file path
        chunk_size: bytes per chunk (default 1MB)
        retries: number of retry attempts (default 3)
        backoff_s: base backoff seconds, multiplied by attempt number

    Raises:
        RuntimeError: if download fails after all retry attempts
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            logger.debug(f"Download attempt {attempt}/{retries}: {url}")
            with req_session.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
            tmp.replace(dst)
            logger.debug(f"Successfully downloaded {dst.name}")
            return dst

        except requests.exceptions.Timeout as e:
            last_err = e
            logger.warning(
                f"Download timeout (attempt {attempt}/{retries}): {url}\n"
                f"  Pausing {backoff_s * attempt}s before retry..."
            )
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            time.sleep(backoff_s * attempt)

        except requests.exceptions.HTTPError as e:
            last_err = e
            error_code = (
                e.response.status_code if hasattr(e, "response") else "unknown"
            )
            logger.error(
                f"HTTP error {error_code} (attempt {attempt}/{retries}): {url}"
            )
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            # Don't retry on 4xx errors (client error), only on transient issues
            if 400 <= error_code < 500:
                raise RuntimeError(f"HTTP {error_code}: {url}") from e
            time.sleep(backoff_s * attempt)

        except Exception as e:
            last_err = e
            error_type = type(e).__name__
            logger.error(
                f"{error_type} during download (attempt {attempt}/{retries}): {url}\n"
                f"  Error: {e}"
            )
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            time.sleep(backoff_s * attempt)

    raise RuntimeError(
        f"Failed to download after {retries} attempts: {url}"
    ) from last_err


def search_candidates(
    *,
    concept_id: str,
    product: str,
    bbox4326: tuple,
    temporal: tuple,
    max_granules: int,
) -> List[Candidate]:
    """
    Search NASA CMR for HLS granules.

    Args:
        concept_id: CMR concept ID for the collection
        product: Product code ("L30" or "S30")
        bbox4326: Bounding box in WGS84 (lon_min, lat_min, lon_max, lat_max)
        temporal: (start_datetime, end_datetime) tuple
        max_granules: Maximum number of results to return

    Returns:
        List of Candidate objects with metadata
    """
    if temporal[1] < hls_utils.DATASET_START_UTC[product]:
        logger.debug(f"Search end date before {product} dataset start")
        return []

    try:
        logger.debug(
            f"Querying CMR for {product}: {temporal[0].date()} to {temporal[1].date()}"
        )
        granules = (
            earthaccess.search_data(
                concept_id=concept_id,
                temporal=(temporal[0].isoformat(), temporal[1].isoformat()),
                bounding_box=bbox4326,
                count=max_granules,
            )
            or []
        )
        logger.debug(f"Found {len(granules)} {product} granules")
    except Exception as e:
        logger.error(
            f"CMR search failed for {product}: {type(e).__name__}: {e}"
        )
        return []

    out: List[Candidate] = []
    for gr in granules:
        gid = hls_utils.granule_id(gr)
        gtime = hls_utils.granule_start_time_utc(gr)
        if gtime is None:
            logger.warning(f"Could not extract start time for granule {gid}")
            continue

        links = hls_utils.granule_data_links(gr)
        out.append(
            Candidate(
                product=product,
                granule_id=gid,
                start_time_utc=gtime,
                abs_days_from_target=0,  # filled later
                data_links=links,
            )
        )
    return out


def choose_best_for_site_year(
    *,
    site_id: Any,
    site_geom,
    site_geom_crs,
    year: int,
    window_days: int,
    req_session,
    hard_cap: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Search for best HLS imagery for a given site and year.

    For a given site/year, this function:
    1) Queries CMR for all available L30 and S30 granules within the search window
    2) Sorts candidates by temporal proximity to June 20
    3) Downloads Fmask and evaluates candidates until finding first 0% cloud image
    4) Returns all evaluated candidates, sorted by cloud %, then temporal proximity

    Early stopping: Stops evaluating when finding an image with 0% cloudy_pct,
    since that's the best possible result.

    Hard cap: If specified, only candidates within hard_cap days of target are considered.
    If no candidates pass the hard cap, returns a "not-found" marker row.

    Returns:
      List of dicts with: site_id, year, product, granule_id, sensing_time_utc,
                         abs_days_from_target, cloud_pct, adjacent_pct,
                         shadow_pct, cloudy_pct, status
    """
    # -------------------------------------------------------------------------
    # Step 1: Define temporal search window (centered on June 20)
    # -------------------------------------------------------------------------
    target = dt.datetime(year, TARGET_MONTH, TARGET_DAY, tzinfo=dt.timezone.utc)
    start = target - dt.timedelta(days=window_days)
    end = target + dt.timedelta(days=window_days)

    # -------------------------------------------------------------------------
    # Step 2: Convert site geometry to WGS84 for CMR spatial queries
    # -------------------------------------------------------------------------
    # NASA CMR expects bounding boxes in lat/lon (EPSG:4326)
    site4326 = gpd.GeoSeries([site_geom], crs=site_geom_crs).to_crs("EPSG:4326")
    minx, miny, maxx, maxy = site4326.total_bounds
    bbox4326 = (float(minx), float(miny), float(maxx), float(maxy))

    # -------------------------------------------------------------------------
    # Step 3: Query NASA CMR for both Landsat and Sentinel-2 granules
    # -------------------------------------------------------------------------
    candidates: List[Candidate] = []
    for prod in hls_utils.PRODUCTS:
        concept_id = hls_utils.DEFAULT_CONCEPT_IDS[prod]
        cands = search_candidates(
            concept_id=concept_id,
            product=prod,
            bbox4326=bbox4326,
            temporal=(start, end),
            max_granules=MAX_GRANULES,
        )

        # Calculate absolute days from target date for each candidate
        # This is used for initial sorting before cloud evaluation
        fixed = []
        for c in cands:
            abs_days = abs((c.start_time_utc.date() - target.date()).days)
            fixed.append(
                Candidate(**{**c.__dict__, "abs_days_from_target": abs_days})
            )
        candidates.extend(fixed)

    if not candidates:
        return []

    # -------------------------------------------------------------------------
    # Step 4: Sort candidates by temporal proximity to June 20
    # -------------------------------------------------------------------------
    # This initial sort ensures we evaluate the most temporally relevant images first
    candidates.sort(key=lambda c: (c.abs_days_from_target, c.start_time_utc))

    # -------------------------------------------------------------------------
    # Step 5: Download Fmask and compute cloud %
    # -------------------------------------------------------------------------
    # Strategy:
    # - Always evaluate ALL candidates (no early stopping when hard_cap is set)
    # - Track if we find 0% cloudy within the hard-cap window
    # - Hard-cap affects how results are reported, not which candidates are evaluated
    # - Without hard_cap: early stop when finding 0% cloudy (optimization)
    results = []
    best_within_hardcap = (
        None  # Track if we found 0% cloudy within hard-cap window
    )

    for cand in candidates:
        # Extract Fmask file URL from granule's data links
        fmask_url = hls_utils.pick_fmask_url(cand.data_links)
        if not fmask_url:
            continue

        # Create a filesystem-safe filename for caching
        safe_gid = re.sub(r"[^A-Za-z0-9._-]+", "_", cand.granule_id)
        fmask_path = (
            hls_utils.CACHE_DIR
            / "fmask"
            / cand.product
            / f"{safe_gid}_Fmask.tif"
        )

        try:
            # Download Fmask GeoTIFF if not already cached
            # This is the only file we download - RGB bands are not needed
            if not fmask_path.exists():
                download_with_session(req_session, fmask_url, fmask_path)

            # Compute site-specific quality metrics and validate coverage by:
            # 1) Clipping Fmask to site polygon
            # 2) Checking that the site is fully within the tile (>90% coverage)
            # 3) Decoding individual quality bit flags
            # 4) Computing % of pixels marked as cloud, adjacent, or shadow
            stats = fmask_cloud_stats(
                fmask_path=fmask_path,
                geom=site_geom,
                geom_crs=site_geom_crs,
            )

            # Skip images where the site extends beyond tile boundary
            # Partial coverage would give misleading cloud statistics
            if not stats["sufficient_coverage"]:
                continue

            # Skip candidates with high cloud percentage (quality threshold)
            # Only keep images with < 90% direct cloud coverage
            if stats["cloud_pct"] > 90.0:
                logger.debug(
                    f"Skipping {cand.granule_id}: cloud_pct={stats['cloud_pct']:.1f}% exceeds 90% threshold"
                )
                continue

            # Convert product code (L30/S30) to human-readable name
            product_name = "Landsat" if cand.product == "L30" else "Sentinel-2"

            # Create result row for this candidate
            result_row = {
                "site_id": site_id,
                "year": year,
                "product": product_name,
                "granule_id": cand.granule_id,
                "sensing_time_utc": cand.start_time_utc.isoformat(),
                "abs_days_from_target": cand.abs_days_from_target,
                "cloud_pct": stats["cloud_pct"],
                "adjacent_pct": stats["adjacent_pct"],
                "shadow_pct": stats["shadow_pct"],
                "cloudy_pct": stats["cloudy_pct"],
                "status": "found",
            }

            results.append(result_row)

            # Check if this is a perfect image (0% cloudy) within the hard-cap window
            # Use np.isclose() instead of exact equality to handle floating point precision
            if np.isclose(stats["cloudy_pct"], 0.0, atol=0.01):
                within_cap = (
                    hard_cap is None or cand.abs_days_from_target <= hard_cap
                )
                if within_cap:
                    best_within_hardcap = result_row
                    logger.debug(
                        f"Found 0% cloudy match: {cand.granule_id} "
                        f"({cand.abs_days_from_target} days from target)"
                    )

                break  # Can't do better than 0% cloud

        except requests.exceptions.Timeout as e:
            logger.warning(
                f"Timeout downloading Fmask for {cand.granule_id}: {url}"
            )
            continue

        except requests.exceptions.HTTPError as e:
            error_code = (
                e.response.status_code if hasattr(e, "response") else "unknown"
            )
            logger.warning(
                f"HTTP {error_code} error downloading {cand.granule_id}: {url}"
            )
            continue

        except Exception as e:
            # Log the error with context for debugging
            error_type = type(e).__name__
            logger.warning(f"{error_type} processing {cand.granule_id}: {e}")
            continue

    # -------------------------------------------------------------------------
    # Report results based on hard-cap setting and candidate availability
    # -------------------------------------------------------------------------
    # If no candidates passed the quality filters (cloud_pct <= 90%), mark as "none-found"
    if not results:
        logger.debug(f"No suitable candidates for site {site_id} year {year}")
        return [
            {
                "site_id": site_id,
                "year": year,
                "product": None,
                "granule_id": None,
                "sensing_time_utc": None,
                "abs_days_from_target": None,
                "cloud_pct": None,
                "adjacent_pct": None,
                "shadow_pct": None,
                "cloudy_pct": None,
                "status": "none-found",
            }
        ]

    # Candidates exist - apply hard-cap logic if specified
    if hard_cap is not None:
        if best_within_hardcap is not None:
            # Found a match within hard-cap: return only that single best candidate
            return [best_within_hardcap]
        else:
            # No match within hard-cap: return all candidates evaluated (for review)
            # This lets the user see all available options and choose manually if needed
            for row in results:
                row["status"] = "not-found"
            return results
    else:
        # No hard-cap: return all evaluated candidates (stopped at first 0% cloudy)
        return results


def load_sites_excel(path: Path, id_col: str) -> pd.DataFrame:
    """Load site table from Excel."""
    df = pd.read_excel(path, sheet_name=0)
    if id_col not in df.columns:
        raise ValueError(
            f"Excel is missing required id column '{id_col}'. Columns: {list(df.columns)}"
        )
    return df


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Search HLS v2 data via earthaccess and compute site-specific cloud% from Fmask."
    )
    p.add_argument(
        "--years",
        type=str,
        default="2013,2015,2020,2025",
        help="Comma-separated years to query.",
    )
    p.add_argument(
        "--window-days",
        type=int,
        default=45,
        help="+/- days around June 20 to search.",
    )
    p.add_argument(
        "--out-csv",
        type=Path,
        default=Path("hls_site_results.csv"),
        help="Output CSV path.",
    )
    p.add_argument(
        "--test-sites",
        type=str,
        default=None,
        help="Optional comma-separated list of site IDs to limit to.",
    )
    p.add_argument(
        "--hard-cap",
        type=int,
        default=None,
        help="Maximum days from target date (June 20). Site/year combos with no candidates within this cap are marked as 'not-found'.",
    )
    p.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity level (default: INFO).",
    )
    return p.parse_args()


def main() -> None:
    """
    Main function to search HLS imagery across sites and years.

    Workflow:
    1. Authenticate with NASA Earthdata using netrc credentials
    2. Load site locations from Excel and geometries from shapefile
    3. For each site × year combination:
       - Query NASA CMR for HLS granules within ±N days of June 20
       - Download Fmask for top candidates (sorted by temporal proximity)
       - Compute site-specific cloud % from Fmask
       - Rank by cloud %, then by days from target
    4. Export results to CSV
    """
    args = parse_args()

    # =========================================================================
    # Configure logging level
    # =========================================================================
    log_level = getattr(logging, args.log_level.upper(), logging.DEBUG)
    logger.setLevel(log_level)
    for handler in logger.handlers:
        handler.setLevel(log_level)

    # =========================================================================
    # Parse and validate command-line arguments
    # =========================================================================
    try:
        years = [int(y.strip()) for y in args.years.split(",") if y.strip()]
    except ValueError as e:
        raise ValueError(f"Invalid year format: {args.years}") from e

    window_days = args.window_days
    hard_cap = args.hard_cap
    out_csv = args.out_csv

    # Validate parameter ranges
    if not years:
        raise ValueError("No years specified")
    if window_days <= 0:
        raise ValueError(f"window_days must be positive, got {window_days}")
    if hard_cap is not None and hard_cap <= 0:
        raise ValueError(f"hard_cap must be positive, got {hard_cap}")
    if hard_cap is not None and hard_cap > window_days:
        logger.warning(
            f"hard_cap ({hard_cap}) exceeds window_days ({window_days}). "
            "Many site/years may be marked as not-found."
        )

    # Optional filter: limit to specific site IDs for testing/debugging
    test_sites: Optional[set] = None
    if args.test_sites:
        test_sites = {
            int(x.strip()) if x.strip().isdigit() else x.strip()
            for x in args.test_sites.split(",")
            if x.strip()
        }

    # =========================================================================
    # Validate input files before starting
    # =========================================================================
    logger.info("Validating input files...")
    if not hls_utils.SITES_EXCEL.exists():
        raise FileNotFoundError(
            f"Sites Excel file not found: {hls_utils.SITES_EXCEL.resolve()}"
        )
    if not hls_utils.SITES_SHAPEFILE.exists():
        raise FileNotFoundError(
            f"Sites shapefile not found: {hls_utils.SITES_SHAPEFILE.resolve()}"
        )

    # Check for netrc file (required for NASA Earthdata authentication)
    # Windows uses _netrc, Unix uses .netrc
    netrc_paths = [Path.home() / "_netrc", Path.home() / ".netrc"]
    netrc_exists = any(p.exists() for p in netrc_paths)
    if not netrc_exists:
        raise FileNotFoundError(
            f"NASA Earthdata credentials file not found.\n"
            f"Expected location: {netrc_paths[0]} (Windows) or {netrc_paths[1]} (Unix)\n"
            "Please create credentials file with your Earthdata login.\n"
            "See: https://earthaccess.readthedocs.io/en/latest/"
        )
    logger.info("[OK] Input files validated\n")

    # =========================================================================
    # Print run configuration
    # =========================================================================
    print("=" * 70)
    print("HLS Imagery Search via Earthaccess")
    print("=" * 70)
    print(f"Target date: June 20 (+/- {window_days} days)")
    print(f"Years: {years}")
    print(
        "Early stopping: stops when finding first 0% cloud image per site/year"
    )
    if hard_cap is not None:
        print(
            f"Hard cap: {hard_cap} days (site/years beyond this will be marked 'not-found')"
        )
    if test_sites:
        print(f"Testing mode: {len(test_sites)} sites only")
    print()

    # =========================================================================
    # Step 1: Authenticate with NASA Earthdata
    # =========================================================================
    # Requires ~/.netrc file with NASA Earthdata Login credentials
    print("Step 1: Authenticating with NASA Earthdata...")
    try:
        earthaccess.login(strategy="netrc")
        req_session = earthaccess.get_requests_https_session()
        print("[OK] Authentication successful\n")
        logger.info("Successfully authenticated with NASA Earthdata")
    except Exception as e:
        raise RuntimeError(
            f"Failed to authenticate with NASA Earthdata: {e}\n"
            "Check that ~/.netrc contains valid Earthdata credentials."
        ) from e

    # =========================================================================
    # Step 2: Load site data and geometries
    # =========================================================================
    print("Step 2: Loading site data and geometries...")
    sites_df = load_sites_excel(hls_utils.SITES_EXCEL, "site_id")
    geom_gdf = hls_utils.load_site_geometries(hls_utils.SITES_SHAPEFILE, "SITE")
    print(f"[OK] Loaded {len(sites_df)} sites from Excel")
    print(f"[OK] Loaded {len(geom_gdf)} site geometries from shapefile\n")

    # Create lookup dictionary: site_id -> geometry
    geom_by_id = dict(
        zip(geom_gdf["SITE"].tolist(), geom_gdf.geometry.tolist())
    )
    geom_crs = geom_gdf.crs
    if geom_crs is None:
        raise ValueError("Geometry file has no CRS.")

    # Apply test site filter if specified
    if test_sites:
        sites_to_search = sites_df[sites_df["site_id"].isin(test_sites)]
    else:
        sites_to_search = sites_df

    print(
        f"Step 3: Searching for imagery ({len(sites_to_search)} sites × {len(years)} years = {len(sites_to_search) * len(years)} queries)...\n"
    )

    # =========================================================================
    # Step 3: Search for imagery across all sites and years
    # =========================================================================
    # This is the main processing loop - can take hours for full dataset
    all_results = []
    total_combinations = len(sites_to_search) * len(years)

    # Use tqdm progress bar to track completion
    with tqdm(total=total_combinations, desc="Searching", unit="query") as pbar:
        for _, site in sites_to_search.iterrows():
            sid = site["site_id"]
            geom = geom_by_id.get(sid)

            if geom is None:
                # Skip sites without geometry (shouldn't happen if data is clean)
                print(f"\n[WARNING] Site {sid}: No geometry found")
                for _ in years:
                    pbar.update(1)
                continue

            for year in years:
                # Core function: search, download Fmask, compute cloud %
                results = choose_best_for_site_year(
                    site_id=sid,
                    site_geom=geom,
                    site_geom_crs=geom_crs,
                    year=year,
                    window_days=window_days,
                    req_session=req_session,
                    hard_cap=hard_cap,
                )

                # Accumulate results and update progress
                all_results.extend(results)
                pbar.update(1)
                pbar.set_postfix({"found": len(all_results)})

    # Step 4: Save results to CSV
    print(f"\nStep 4: Saving results...")
    if all_results:
        out_df = pd.DataFrame(all_results)
        out_csv.parent.mkdir(parents=True, exist_ok=True)

        # Separate results by status
        found_df = out_df[out_df["status"] == "found"]
        not_found_df = out_df[out_df["status"] == "not-found"]
        none_found_df = out_df[out_df["status"] == "none-found"]

        # Save main results (found imagery)
        if len(found_df) > 0:
            found_df.to_csv(out_csv, index=False)
            print(f"\n✓ Found imagery saved to: {out_csv.resolve()}")
            print(f"  Total found: {len(found_df)} imagery records")

        # Save not-found results if using hard cap
        if hard_cap is not None and len(not_found_df) > 0:
            not_found_csv = (
                out_csv.parent / f"{out_csv.stem}_not_found{out_csv.suffix}"
            )
            not_found_df.to_csv(not_found_csv, index=False)
            print(
                f"\n✓ Not-found site/years saved to: {not_found_csv.resolve()}"
            )
            print(
                f"  Total not-found: {len(not_found_df)} site/year combinations"
            )

        # Save none-found results (no candidates within quality threshold)
        if len(none_found_df) > 0:
            none_found_csv = (
                out_csv.parent / f"{out_csv.stem}_none_found{out_csv.suffix}"
            )
            none_found_df.to_csv(none_found_csv, index=False)
            print(
                f"\n✓ No suitable imagery saved to: {none_found_csv.resolve()}"
            )
            print(
                f"  Total none-found: {len(none_found_df)} site/year combinations"
            )

        print("\n" + "=" * 70)
        print("[SUCCESS] SEARCH COMPLETE")
        print("=" * 70)

        # Summary statistics
        if len(found_df) > 0:
            sites_with_imagery = found_df["site_id"].nunique()
            print(f"\nSites with suitable imagery: {sites_with_imagery}")
            print("Found imagery by year:")
            year_counts = found_df.groupby("year").size()
            for year, count in year_counts.items():
                print(f"  {year}: {count} images")

        if hard_cap is not None and len(not_found_df) > 0:
            print(f"\nSite/years beyond {hard_cap}-day hard cap:")
            not_found_sites = not_found_df["site_id"].nunique()
            print(
                f"  {len(not_found_df)} site/year combinations ({not_found_sites} unique sites)"
            )
            not_found_year_counts = not_found_df.groupby("year").size()
            for year, count in not_found_year_counts.items():
                print(f"    {year}: {count} site/years")

        if len(none_found_df) > 0:
            print(
                f"\nSite/years with NO suitable candidates (cloud_pct > 90%):"
            )
            none_found_sites = none_found_df["site_id"].nunique()
            print(
                f"  {len(none_found_df)} site/year combinations ({none_found_sites} unique sites)"
            )
            none_found_year_counts = none_found_df.groupby("year").size()
            for year, count in none_found_year_counts.items():
                print(f"    {year}: {count} site/years")

        print("=" * 70)
    else:
        print("\n" + "=" * 70)
        print("[ERROR] NO IMAGERY FOUND")
        print("=" * 70)


if __name__ == "__main__":
    main()
