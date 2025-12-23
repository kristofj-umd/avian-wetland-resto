"""
hls_utils.py

Shared utilities for HLS (Harmonized Landsat Sentinel-2) data processing.

This module provides common functionality used across HLS workflow scripts:
- Configuration constants (file paths, band definitions, CMR concept IDs)
- GDAL configuration for NASA Earthdata Cloud access
- NASA Earthdata authentication
- Site geometry loading and caching
- Granule metadata extraction and querying
- Band URL extraction from granules

Used by:
- hls_imagery_search_earthaccess.py (search for imagery)
- hls_composite_export.py (download and export COGs)
- hls_viewer_earthaccess.py (visualize results)
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import geopandas as gpd
from osgeo import gdal

import earthaccess

# ============================================================================
# Logging Configuration
# ============================================================================
logger = logging.getLogger(__name__)

# ============================================================================
# File Path Constants
# ============================================================================

# Sites shapefile - contains polygon geometries for all sites
SITES_SHAPEFILE = Path(
    "data/sites_v2024-08-02-20251027T153209Z-1-001/sites_v2024-08-02/sites_all_polygons.shp"
)

# Sites Excel - contains site metadata and attributes
SITES_EXCEL = Path("data/sites_2025.11.20.xlsx")

# Cache directory for downloaded Fmask files
CACHE_DIR = Path(".cache_hls")

# ============================================================================
# HLS Band Definitions
# ============================================================================

# HLS L30 (Landsat 8/9 OLI) spectral bands - 10 bands total
# Band order matters for stacking operations
L30_BANDS = [
    "B01",  # Coastal Aerosol (433-453 nm)
    "B02",  # Blue (450-515 nm)
    "B03",  # Green (525-600 nm)
    "B04",  # Red (630-680 nm)
    "B05",  # NIR (845-885 nm)
    "B06",  # SWIR1 (1560-1660 nm)
    "B07",  # SWIR2 (2100-2300 nm)
    "B09",  # Cirrus (1360-1390 nm)
    "B10",  # Thermal1 (10600-11190 nm)
    "B11",  # Thermal2 (11500-12510 nm)
]

# HLS S30 (Sentinel-2 MSI) spectral bands - 13 bands total
S30_BANDS = [
    "B01",  # Coastal Aerosol (433-453 nm)
    "B02",  # Blue (458-523 nm)
    "B03",  # Green (543-578 nm)
    "B04",  # Red (650-680 nm)
    "B05",  # Red Edge1 (698-713 nm)
    "B06",  # Red Edge2 (733-748 nm)
    "B07",  # Red Edge3 (773-793 nm)
    "B08",  # NIR Broad (785-900 nm)
    "B8A",  # NIR Narrow (855-875 nm)
    "B09",  # Water Vapor (935-955 nm)
    "B10",  # Cirrus (1360-1390 nm)
    "B11",  # SWIR1 (1565-1655 nm)
    "B12",  # SWIR2 (2100-2280 nm)
]

# Descriptive band names for Landsat 8/9 (L30)
# Used for metadata and band descriptions in output files
L30_BAND_NAMES = {
    "B01": "Coastal_Aerosol",
    "B02": "Blue",
    "B03": "Green",
    "B04": "Red",
    "B05": "NIR",
    "B06": "SWIR1",
    "B07": "SWIR2",
    "B09": "Cirrus",
    "B10": "Thermal1",
    "B11": "Thermal2",
}

# Descriptive band names for Sentinel-2 (S30)
S30_BAND_NAMES = {
    "B01": "Coastal_Aerosol",
    "B02": "Blue",
    "B03": "Green",
    "B04": "Red",
    "B05": "Red_Edge1",
    "B06": "Red_Edge2",
    "B07": "Red_Edge3",
    "B08": "NIR_Broad",
    "B8A": "NIR_Narrow",
    "B09": "Water_Vapor",
    "B10": "Cirrus",
    "B11": "SWIR1",
    "B12": "SWIR2",
}

# RGB band mappings for true-color visualization
# Both L30 and S30 use the same band codes for RGB
HLS_RGB_BANDS = {
    "Landsat": {"red": "B04", "green": "B03", "blue": "B02"},
    "Sentinel-2": {"red": "B04", "green": "B03", "blue": "B02"},
}

# Mapping from product name to full band list
PRODUCT_BANDS = {
    "Landsat": L30_BANDS,
    "Sentinel-2": S30_BANDS,
}

# Mapping from product name to band name lookup
PRODUCT_BAND_NAMES = {
    "Landsat": L30_BAND_NAMES,
    "Sentinel-2": S30_BAND_NAMES,
}

# ============================================================================
# NASA CMR (Common Metadata Repository) Configuration
# ============================================================================

# CMR concept IDs for HLS v2.0 collections in LP DAAC Cloud
# These permanent identifiers are used to query the NASA CMR API
DEFAULT_CONCEPT_IDS = {
    "L30": "C2021957657-LPCLOUD",  # HLSL30 v2.0 (Landsat 8/9 OLI)
    "S30": "C2021957295-LPCLOUD",  # HLSS30 v2.0 (Sentinel-2 A/B MSI)
}

# First available date for each HLS product
# Used to avoid querying before data exists
DATASET_START_UTC = {
    "L30": dt.datetime(2013, 4, 11, tzinfo=dt.timezone.utc),
    "S30": dt.datetime(2015, 11, 28, tzinfo=dt.timezone.utc),
}

# Both Landsat and Sentinel-2 products
PRODUCTS = ["L30", "S30"]

# HLS reflectance scale factor (convert from int16 to float reflectance)
HLS_SCALE_FACTOR = 0.0001

# ============================================================================
# Planetary Computer Configuration (for tile service)
# ============================================================================

# Planetary Computer collection IDs (HLS v2.0)
# Used for web map tile service in viewer
PC_COLLECTIONS = {
    "Landsat": "hls2-l30",
    "Sentinel-2": "hls2-s30",
}

# ============================================================================
# GDAL Configuration
# ============================================================================


def configure_gdal_for_nasa() -> None:
    """
    Configure GDAL to access NASA Earthdata Cloud COGs.

    Sets GDAL configuration options for:
    - Cookie-based authentication (credentials stored in cookies.txt)
    - Efficient cloud access (disable directory listing)
    - Retry logic for transient network failures
    - SSL configuration for NASA servers

    This function should be called before any rasterio/GDAL operations
    that access NASA cloud data.
    """
    gdal.SetConfigOption("GDAL_HTTP_COOKIEFILE", "~/cookies.txt")
    gdal.SetConfigOption("GDAL_HTTP_COOKIEJAR", "~/cookies.txt")
    gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    gdal.SetConfigOption("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", "TIF")
    gdal.SetConfigOption("GDAL_HTTP_UNSAFESSL", "YES")
    gdal.SetConfigOption("GDAL_HTTP_MAX_RETRY", "10")
    gdal.SetConfigOption("GDAL_HTTP_RETRY_DELAY", "0.5")


# ============================================================================
# NASA Earthdata Authentication
# ============================================================================


def authenticate_earthdata() -> Any:
    """
    Authenticate with NASA Earthdata using netrc credentials.

    Reads credentials from ~/.netrc (Unix) or ~/_netrc (Windows).
    The netrc file should contain:
        machine urs.earthdata.nasa.gov
        login <username>
        password <password>

    Returns:
        Authenticated requests session for downloading data

    Raises:
        RuntimeError: If authentication fails
    """
    try:
        earthaccess.login(strategy="netrc")
        req_session = earthaccess.get_requests_https_session()
        logger.info("Successfully authenticated with NASA Earthdata")
        return req_session
    except Exception as e:
        raise RuntimeError(
            f"Failed to authenticate with NASA Earthdata: {e}\n"
            "Check that ~/.netrc contains valid Earthdata credentials."
        ) from e


# ============================================================================
# Site Geometry Loading
# ============================================================================

# Global cache for site geometries (prevents reloading on every call)
_sites_cache: Optional[gpd.GeoDataFrame] = None


def load_site_geometries(
    path: Optional[Path] = None, id_col: str = "SITE"
) -> gpd.GeoDataFrame:
    """
    Load site geometries from shapefile with caching and validation.

    This function:
    1. Loads the shapefile (cached after first call)
    2. Fixes invalid geometries using buffer(0) trick
    3. Dissolves multiple polygons per site into single geometry
    4. Returns GeoDataFrame with one row per unique site

    Args:
        path: Path to shapefile (default: SITES_SHAPEFILE constant)
        id_col: Column name for site IDs (default: "SITE")

    Returns:
        GeoDataFrame with columns [id_col, geometry]

    Raises:
        ValueError: If id_col not found in shapefile
        FileNotFoundError: If shapefile doesn't exist
    """
    global _sites_cache

    if path is None:
        path = SITES_SHAPEFILE

    # Use cache if available
    if _sites_cache is not None:
        return _sites_cache

    if not path.exists():
        raise FileNotFoundError(f"Sites shapefile not found: {path}")

    logger.info(f"Loading site geometries from {path}")
    gdf = gpd.read_file(path)

    if id_col not in gdf.columns:
        raise ValueError(
            f"Column '{id_col}' not found. Available: {list(gdf.columns)}"
        )

    # Fix invalid geometries with buffer(0) - standard GEOS trick
    # This resolves self-intersections and other topology issues
    gdf["geometry"] = gdf["geometry"].apply(
        lambda g: g.buffer(0) if g and not g.is_valid else g
    )

    # Dissolve/union by site ID to get one geometry per site
    # Some sites may have multiple polygons that need to be combined
    gdf = gdf[[id_col, "geometry"]].dropna(subset=["geometry"]).copy()
    dissolved = gdf.dissolve(by=id_col, as_index=False)

    logger.info(f"Loaded {len(dissolved)} site geometries")

    # Cache for future calls
    _sites_cache = dissolved

    return dissolved


def get_site_geometry(site_id: Any, crs: Optional[str] = None) -> Any:
    """
    Get geometry for a specific site.

    Args:
        site_id: Site identifier
        crs: Target CRS (default: keep original CRS)

    Returns:
        Shapely geometry object

    Raises:
        ValueError: If site_id not found
    """
    sites_gdf = load_site_geometries()
    site_data = sites_gdf[sites_gdf["SITE"] == site_id]

    if len(site_data) == 0:
        raise ValueError(f"Site {site_id} not found in shapefile")

    geom = site_data.iloc[0]["geometry"]

    # Transform to target CRS if specified
    if crs is not None:
        geom_series = gpd.GeoSeries([geom], crs=sites_gdf.crs)
        geom = geom_series.to_crs(crs).iloc[0]

    return geom


def get_site_geometries_as_dict(id_col: str = "SITE") -> Dict[Any, Any]:
    """
    Get site geometries as a dictionary mapping site_id -> geometry.

    Args:
        id_col: Column name for site IDs

    Returns:
        Dict mapping site IDs to shapely geometry objects
    """
    gdf = load_site_geometries(id_col=id_col)
    return dict(zip(gdf[id_col].tolist(), gdf.geometry.tolist()))


# ============================================================================
# Granule Metadata Extraction
# ============================================================================


def _as_dict(obj: Any) -> Dict[str, Any]:
    """
    Best-effort conversion of an earthaccess DataGranule to a dict.

    The earthaccess library uses different object types across versions.
    This function handles multiple possible object structures to extract
    metadata reliably.

    Args:
        obj: Granule object from earthaccess

    Returns:
        Dictionary with granule metadata
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj

    # Try common attributes that contain the data
    for attr in ("data", "umm"):
        if hasattr(obj, attr):
            val = getattr(obj, attr)
            if isinstance(val, dict):
                return {attr: val} if attr == "umm" else val

    # Try common methods that return dicts
    for meth in ("model_dump", "dict", "to_dict"):
        if hasattr(obj, meth) and callable(getattr(obj, meth)):
            try:
                d = getattr(obj, meth)()
                return d if isinstance(d, dict) else {}
            except Exception:
                pass

    return {}


def granule_id(gr: Any) -> str:
    """
    Extract granule identifier from earthaccess granule object.

    Tries multiple possible field names for robustness across API versions.

    Args:
        gr: Granule object from earthaccess

    Returns:
        Granule ID string (e.g., "HLS.L30.T17TQJ.2020170T155042.v2.0")
    """
    d = _as_dict(gr)

    # Try UMM (Unified Metadata Model) fields first
    ur = (
        d.get("umm", {}).get("GranuleUR")
        or d.get("umm", {}).get("GranuleURs", [None])[0]
    )
    if ur:
        return str(ur)

    # Fallback to common alternative field names
    for k in ("title", "granule_ur", "id", "name"):
        if k in d and d[k]:
            return str(d[k])

    return "UNKNOWN_GRANULE"


def granule_start_time_utc(gr: Any) -> Optional[dt.datetime]:
    """
    Extract granule acquisition start time (UTC).

    Args:
        gr: Granule object from earthaccess

    Returns:
        Datetime object in UTC, or None if not found
    """
    d = _as_dict(gr)

    # Try common top-level time fields
    for k in (
        "time_start",
        "start_time",
        "beginningDateTime",
        "BeginningDateTime",
    ):
        v = d.get(k)
        if v:
            try:
                return dt.datetime.fromisoformat(
                    str(v).replace("Z", "+00:00")
                ).astimezone(dt.timezone.utc)
            except Exception:
                pass

    # Try nested UMM temporal extent field
    umm = d.get("umm", {})
    try:
        v = umm["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
        return dt.datetime.fromisoformat(
            str(v).replace("Z", "+00:00")
        ).astimezone(dt.timezone.utc)
    except Exception:
        pass

    return None


def granule_data_links(gr: Any) -> List[str]:
    """
    Extract data file URLs from granule object.

    Args:
        gr: Granule object from earthaccess

    Returns:
        List of URLs to granule files (bands, Fmask, etc.)
    """
    # Try using the data_links() method if available (preferred)
    if hasattr(gr, "data_links") and callable(getattr(gr, "data_links")):
        try:
            links = gr.data_links()
            return list(links) if links else []
        except Exception:
            pass

    # Fallback to parsing links from metadata dict
    d = _as_dict(gr)
    links = d.get("links") or d.get("Links") or []
    out = []
    for link in links:
        if isinstance(link, dict) and link.get("href"):
            out.append(link["href"])
        elif isinstance(link, str):
            out.append(link)

    return out


# ============================================================================
# Granule Search Functions
# ============================================================================


def find_granule_by_id(granule_id: str) -> Optional[Any]:
    """
    Search for a specific HLS granule by ID using earthaccess.

    Extracts the product type (L30/S30) from the granule ID and queries
    the appropriate NASA CMR collection.

    Args:
        granule_id: HLS granule identifier (e.g., "HLS.L30.T17TQJ.2020170T155042.v2.0")

    Returns:
        Granule object with data_links() method, or None if not found

    Example:
        >>> granule = find_granule_by_id("HLS.L30.T17TQJ.2020170T155042.v2.0")
        >>> if granule:
        ...     urls = granule.data_links()
    """
    # Extract product type from granule ID
    # Format: HLS.{L30|S30}.{tile}.{datetime}.{version}
    match = re.match(r"HLS\.([LS]30)\.", granule_id)
    if not match:
        logger.warning(f"Invalid granule ID format: {granule_id}")
        return None

    product = match.group(1)
    short_name = f"HLS{product}"

    try:
        logger.debug(f"Querying CMR for {granule_id}")
        results = earthaccess.search_data(
            short_name=short_name, granule_name=granule_id, count=1
        )
        return results[0] if results else None
    except Exception as e:
        logger.error(
            f"CMR query failed for {granule_id}: {type(e).__name__}: {e}"
        )
        return None


# ============================================================================
# Band URL Extraction
# ============================================================================


def get_all_band_urls(
    granule: Any, product: str
) -> tuple[Dict[str, str], Optional[str]]:
    """
    Extract all spectral band URLs and Fmask URL from a granule.

    Args:
        granule: earthaccess granule object
        product: "Landsat" or "Sentinel-2"

    Returns:
        Tuple of (band_urls dict, fmask_url)
        - band_urls: {"B01": "https://...", "B02": "https://...", ...}
        - fmask_url: "https://...Fmask.tif" or None

    Example:
        >>> granule = find_granule_by_id("HLS.L30.T17TQJ.2020170T155042.v2.0")
        >>> band_urls, fmask_url = get_all_band_urls(granule, "Landsat")
        >>> print(f"Found {len(band_urls)} bands")
    """
    if granule is None:
        return {}, None

    # Get all data links from granule
    try:
        links = granule_data_links(granule)
    except Exception as e:
        logger.warning(f"Failed to get data links: {e}")
        links = []

    if not links:
        return {}, None

    band_list = PRODUCT_BANDS.get(product, [])
    band_urls = {}
    fmask_url = None

    for url in links:
        # Check for Fmask quality band
        if "Fmask.tif" in url or ".Fmask." in url:
            fmask_url = url
            continue

        # Check for each spectral band
        # URLs contain band code like ".B04.tif"
        for band in band_list:
            if f".{band}.tif" in url:
                band_urls[band] = url
                break

    logger.debug(
        f"Found {len(band_urls)} band URLs and fmask={fmask_url is not None}"
    )
    return band_urls, fmask_url


def get_rgb_band_urls(granule: Any, product: str) -> Dict[str, str]:
    """
    Extract RGB band URLs from a granule (for visualization).

    Args:
        granule: earthaccess granule object
        product: "Landsat" or "Sentinel-2"

    Returns:
        Dict with keys: 'red', 'green', 'blue' mapping to URLs

    Example:
        >>> granule = find_granule_by_id("HLS.L30.T17TQJ.2020170T155042.v2.0")
        >>> rgb_urls = get_rgb_band_urls(granule, "Landsat")
        >>> red_url = rgb_urls.get("red")
    """
    if granule is None:
        return {}

    # Get all data links
    try:
        links = granule_data_links(granule)
    except Exception:
        links = []

    if not links:
        return {}

    # Get RGB band names for this product
    bands = HLS_RGB_BANDS.get(product, {})
    if not bands:
        return {}

    # Find URLs for each RGB band
    band_urls = {}
    for color, band_name in bands.items():
        for url in links:
            if f".{band_name}.tif" in url:
                band_urls[color] = url
                break

    return band_urls


# ============================================================================
# Fmask URL Extraction
# ============================================================================


def pick_fmask_url(links: List[str]) -> Optional[str]:
    """
    Choose the Fmask file URL from a list of granule file links.

    Args:
        links: List of URLs from granule.data_links()

    Returns:
        URL to Fmask file, or None if not found
    """
    tif_links = [u for u in links if ".tif" in u.lower()]
    fmask = [u for u in tif_links if "fmask" in u.lower()]

    if fmask:
        return fmask[0]

    # Fallback to first TIF if no Fmask found
    return tif_links[0] if tif_links else None


# ============================================================================
# Product Name Conversions
# ============================================================================


def product_code_to_name(code: str) -> str:
    """
    Convert product code to human-readable name.

    Args:
        code: "L30" or "S30"

    Returns:
        "Landsat" or "Sentinel-2"
    """
    return "Landsat" if code == "L30" else "Sentinel-2"


def product_name_to_code(name: str) -> str:
    """
    Convert product name to code.

    Args:
        name: "Landsat" or "Sentinel-2"

    Returns:
        "L30" or "S30"
    """
    return "L30" if name == "Landsat" else "S30"
