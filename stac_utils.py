"""
stac_utils.py

Utilities for STAC (SpatioTemporal Asset Catalog) API interaction.

This module provides functions for searching STAC collections, parsing STAC items,
and extracting asset URLs for satellite imagery bands. Designed to work with any
STAC-compliant API endpoint.

Key functionality:
- STAC API searching with spatial, temporal, and property filters
- STAC item metadata parsing and normalization
- Asset URL extraction and band discovery
- Collection metadata introspection

Primary use case: Search and download satellite imagery from STAC collections
like USGS Landsat, Sentinel-2, and other cloud-hosted datasets.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from pystac_client import Client
from pystac import Item, Collection

# ============================================================================
# Logging Configuration
# ============================================================================
logger = logging.getLogger(__name__)

# ============================================================================
# STAC API Search Functions
# ============================================================================


def search_stac_collection(
    *,
    collection_url: str,
    bbox: Optional[Tuple[float, float, float, float]] = None,
    temporal: Optional[Tuple[dt.datetime, dt.datetime]] = None,
    cloud_cover_max: Optional[float] = None,
    max_items: int = 1000,
    intersects: Optional[Dict] = None,
) -> List[Item]:
    """
    Search a STAC collection for items matching spatial and temporal criteria.

    Parameters
    ----------
    collection_url : str
        URL to STAC catalog or collection API endpoint
    bbox : tuple of float, optional
        Bounding box (minx, miny, maxx, maxy) in EPSG:4326
    temporal : tuple of datetime, optional
        (start_datetime, end_datetime) for temporal filter
    cloud_cover_max : float, optional
        Maximum cloud cover percentage (0-100)
    max_items : int, default=1000
        Maximum number of items to return
    intersects : dict, optional
        GeoJSON geometry for spatial intersection (alternative to bbox)

    Returns
    -------
    list of pystac.Item
        List of STAC items matching search criteria

    Raises
    ------
    RuntimeError
        If STAC API connection or search fails

    Examples
    --------
    >>> from datetime import datetime, timezone
    >>> items = search_stac_collection(
    ...     collection_url="https://landsatlook.usgs.gov/stac-server",
    ...     bbox=(-83.5, 42.0, -83.0, 42.5),
    ...     temporal=(datetime(2020, 6, 1, tzinfo=timezone.utc),
    ...              datetime(2020, 8, 31, tzinfo=timezone.utc)),
    ...     cloud_cover_max=20.0
    ... )
    >>> print(f"Found {len(items)} items")
    """
    try:
        # Open STAC catalog
        logger.debug(f"Connecting to STAC catalog: {collection_url}")
        catalog = Client.open(collection_url)

        # Extract collection ID from URL if it's a collection endpoint
        collection_id = _extract_collection_id(collection_url)

        # Build search parameters
        search_params = {}

        if collection_id:
            search_params["collections"] = [collection_id]

        if bbox is not None:
            search_params["bbox"] = bbox
            logger.debug(f"Spatial filter (bbox): {bbox}")

        if intersects is not None:
            search_params["intersects"] = intersects
            logger.debug(f"Spatial filter (intersects): geometry provided")

        if temporal is not None:
            start, end = temporal
            # Format as ISO 8601 interval
            search_params["datetime"] = f"{start.isoformat()}/{end.isoformat()}"
            logger.debug(f"Temporal filter: {start.date()} to {end.date()}")

        # Cloud cover filter (try common property names)
        if cloud_cover_max is not None:
            # STAC uses different property names for cloud cover
            # Try eo:cloud_cover first (most common), fall back to others
            search_params["query"] = {
                "eo:cloud_cover": {"lt": cloud_cover_max}
            }
            logger.debug(f"Cloud cover filter: < {cloud_cover_max}%")

        # Execute search
        logger.info(f"Searching STAC collection with {len(search_params)} filters...")
        search = catalog.search(max_items=max_items, **search_params)

        # Collect items
        items = list(search.items())
        logger.info(f"Found {len(items)} STAC items")

        return items

    except Exception as e:
        raise RuntimeError(
            f"Failed to search STAC collection at {collection_url}: {e}"
        ) from e


def _extract_collection_id(url: str) -> Optional[str]:
    """
    Attempt to extract collection ID from STAC URL.

    Parameters
    ----------
    url : str
        STAC catalog or collection URL

    Returns
    -------
    str or None
        Collection ID if found in URL path, None otherwise

    Examples
    --------
    >>> _extract_collection_id("https://example.com/stac/collections/landsat-c2l2-sr")
    'landsat-c2l2-sr'
    """
    # Try to extract collection ID from URL path
    # Common patterns: /collections/{id}, /collection/{id}
    match = re.search(r'/collections?/([^/\?]+)', url)
    if match:
        return match.group(1)
    return None


# ============================================================================
# STAC Item Parsing Functions
# ============================================================================


def parse_stac_item(item: Item) -> Dict[str, Any]:
    """
    Extract and normalize metadata from a STAC item.

    Parameters
    ----------
    item : pystac.Item
        STAC item to parse

    Returns
    -------
    dict
        Normalized metadata with keys:
        - id: Item identifier
        - datetime: Acquisition datetime (datetime object)
        - geometry: GeoJSON geometry
        - bbox: Bounding box [minx, miny, maxx, maxy]
        - cloud_cover: Cloud cover percentage (float or None)
        - assets: Dict of asset key -> asset object
        - collection: Collection ID if available

    Examples
    --------
    >>> item_dict = parse_stac_item(stac_item)
    >>> print(f"Item {item_dict['id']} acquired on {item_dict['datetime']}")
    """
    parsed = {
        "id": item.id,
        "datetime": item.datetime,
        "geometry": item.geometry,
        "bbox": item.bbox,
        "assets": {key: asset for key, asset in item.assets.items()},
        "collection": item.collection_id if hasattr(item, 'collection_id') else None,
    }

    # Extract cloud cover from properties (try multiple common names)
    cloud_cover = None
    if item.properties:
        for key in ["eo:cloud_cover", "cloud_cover", "cloudCover", "CLOUD_COVER"]:
            if key in item.properties:
                cloud_cover = item.properties[key]
                break

    parsed["cloud_cover"] = cloud_cover

    # Extract additional useful properties
    if item.properties:
        parsed["properties"] = item.properties

    return parsed


# ============================================================================
# Asset URL Extraction Functions
# ============================================================================


def get_stac_asset_urls(
    item: Item,
    band_names: Optional[List[str]] = None,
) -> Tuple[Dict[str, str], Optional[str]]:
    """
    Extract band asset URLs and quality band URL from STAC item.

    Parameters
    ----------
    item : pystac.Item
        STAC item containing assets
    band_names : list of str, optional
        Specific band names to extract. If None, extracts all band assets.

    Returns
    -------
    band_urls : dict
        Dictionary mapping band name -> asset URL
    qa_url : str or None
        URL to quality assessment band if available

    Examples
    --------
    >>> band_urls, qa_url = get_stac_asset_urls(
    ...     item,
    ...     band_names=["red", "green", "blue", "nir"]
    ... )
    >>> print(f"Found {len(band_urls)} bands")
    """
    band_urls = {}
    qa_url = None

    if not item.assets:
        logger.warning(f"Item {item.id} has no assets")
        return band_urls, qa_url

    # Iterate through assets
    for asset_key, asset in item.assets.items():
        # Check if this is a quality/QA band
        if _is_qa_band(asset_key, asset):
            qa_url = asset.href
            logger.debug(f"Found QA band: {asset_key}")
            continue

        # Check if this is a spectral band
        if _is_spectral_band(asset_key, asset):
            # Use asset key as band name, or extract from metadata
            band_name = asset_key

            # Try to get more descriptive name from asset properties
            if hasattr(asset, 'extra_fields') and asset.extra_fields:
                if 'eo:bands' in asset.extra_fields:
                    eo_bands = asset.extra_fields['eo:bands']
                    if eo_bands and len(eo_bands) > 0:
                        band_name = eo_bands[0].get('common_name', asset_key)

            # If specific bands requested, filter
            if band_names is None or band_name in band_names or asset_key in band_names:
                band_urls[band_name] = asset.href
                logger.debug(f"Found band: {band_name} ({asset_key})")

    logger.debug(f"Extracted {len(band_urls)} band URLs from item {item.id}")
    return band_urls, qa_url


def _is_qa_band(asset_key: str, asset: Any) -> bool:
    """
    Determine if an asset represents a quality assessment band.

    Parameters
    ----------
    asset_key : str
        Asset identifier key
    asset : pystac.Asset
        Asset object

    Returns
    -------
    bool
        True if asset is a QA/quality band
    """
    # Common QA band patterns
    qa_patterns = [
        "qa", "quality", "qc", "fmask", "pixel_qa",
        "qa_pixel", "qapixel", "cloud", "mask"
    ]

    key_lower = asset_key.lower()

    # Check asset key
    if any(pattern in key_lower for pattern in qa_patterns):
        return True

    # Check asset title/description
    if hasattr(asset, 'title') and asset.title:
        if any(pattern in asset.title.lower() for pattern in qa_patterns):
            return True

    if hasattr(asset, 'description') and asset.description:
        if any(pattern in asset.description.lower() for pattern in qa_patterns):
            return True

    return False


def _is_spectral_band(asset_key: str, asset: Any) -> bool:
    """
    Determine if an asset represents a spectral band (not metadata/thumbnail).

    Parameters
    ----------
    asset_key : str
        Asset identifier key
    asset : pystac.Asset
        Asset object

    Returns
    -------
    bool
        True if asset is likely a spectral band
    """
    # Skip common non-band assets
    skip_patterns = [
        "thumbnail", "metadata", "index", "xml", "txt",
        "json", "preview", "overview", "ang", "mtl"
    ]

    key_lower = asset_key.lower()

    # Skip if matches exclusion pattern
    if any(pattern in key_lower for pattern in skip_patterns):
        return False

    # Check media type - should be image format
    if hasattr(asset, 'media_type') and asset.media_type:
        image_types = ["image/tiff", "image/vnd.stac.geotiff", "image/cog", "image/geotiff"]
        if asset.media_type in image_types:
            return True

    # Check for common band patterns
    band_patterns = [
        r"^b\d+",  # B01, B1, etc.
        r"^sr_b\d+",  # Landsat surface reflectance
        r"^coastal$", r"^blue$", r"^green$", r"^red$",
        r"^nir", r"^swir", r"^lwir", r"^tirs"
    ]

    if any(re.match(pattern, key_lower) for pattern in band_patterns):
        return True

    return False


# ============================================================================
# Band Discovery Functions
# ============================================================================


def discover_stac_bands(
    collection_url: str,
    sample_item: Optional[Item] = None,
) -> List[str]:
    """
    Discover available bands in a STAC collection.

    Parameters
    ----------
    collection_url : str
        URL to STAC collection
    sample_item : pystac.Item, optional
        Sample item to inspect. If None, fetches a sample from collection.

    Returns
    -------
    list of str
        List of band names/keys available in the collection

    Examples
    --------
    >>> bands = discover_stac_bands(
    ...     "https://landsatlook.usgs.gov/stac-server/collections/landsat-c2l2-sr"
    ... )
    >>> print(f"Available bands: {bands}")
    """
    try:
        # If no sample item provided, fetch one
        if sample_item is None:
            logger.debug("Fetching sample item to discover bands...")
            items = search_stac_collection(
                collection_url=collection_url,
                max_items=1
            )
            if not items:
                logger.warning("No items found in collection")
                return []
            sample_item = items[0]

        # Extract band names from sample item
        band_urls, _ = get_stac_asset_urls(sample_item)
        bands = list(band_urls.keys())

        logger.info(f"Discovered {len(bands)} bands: {bands}")
        return bands

    except Exception as e:
        logger.error(f"Failed to discover bands: {e}")
        return []


def get_stac_collection_metadata(collection_url: str) -> Dict[str, Any]:
    """
    Fetch and parse collection-level metadata from STAC catalog.

    Parameters
    ----------
    collection_url : str
        URL to STAC collection

    Returns
    -------
    dict
        Collection metadata including:
        - id: Collection identifier
        - title: Human-readable title
        - description: Collection description
        - extent: Spatial and temporal extent
        - license: Data license
        - summaries: Collection summaries (may include band info)

    Raises
    ------
    RuntimeError
        If collection metadata cannot be fetched

    Examples
    --------
    >>> metadata = get_stac_collection_metadata(collection_url)
    >>> print(f"Collection: {metadata['title']}")
    >>> print(f"License: {metadata['license']}")
    """
    try:
        logger.debug(f"Fetching collection metadata from {collection_url}")

        # Try to fetch collection directly if URL points to a collection
        if "/collections/" in collection_url or "/collection/" in collection_url:
            response = requests.get(collection_url, timeout=30)
            response.raise_for_status()
            collection_dict = response.json()
        else:
            # Open catalog and try to get collection
            catalog = Client.open(collection_url)
            collection_id = _extract_collection_id(collection_url)

            if collection_id:
                collection = catalog.get_collection(collection_id)
                collection_dict = collection.to_dict()
            else:
                # Get first collection if no ID specified
                collections = list(catalog.get_collections())
                if not collections:
                    raise ValueError("No collections found in catalog")
                collection_dict = collections[0].to_dict()

        # Extract key metadata
        metadata = {
            "id": collection_dict.get("id"),
            "title": collection_dict.get("title"),
            "description": collection_dict.get("description"),
            "extent": collection_dict.get("extent"),
            "license": collection_dict.get("license"),
            "summaries": collection_dict.get("summaries", {}),
        }

        logger.info(f"Retrieved metadata for collection: {metadata['id']}")
        return metadata

    except Exception as e:
        raise RuntimeError(
            f"Failed to fetch collection metadata from {collection_url}: {e}"
        ) from e
