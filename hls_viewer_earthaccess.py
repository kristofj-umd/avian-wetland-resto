"""
HLS Imagery Viewer for Earthaccess Output

Two viewing modes:
1. Interactive folium viewer (default, fast) - Uses Planetary Computer tile service
2. Static PNG export (--export-maps) - Downloads and renders NASA HLS data directly

Works with output from hls_imagery_search_earthaccess.py.
"""

import argparse
import json
import re
import webbrowser
from pathlib import Path
from typing import Optional

import earthaccess
import folium
import geopandas as gpd
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend to avoid tkinter threading issues
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from osgeo import gdal
import rioxarray as rxr
from matplotlib.patches import Polygon as MplPolygon
from shapely.geometry import mapping
from tqdm import tqdm

# Import shared utilities
import hls_utils

# Viewer-specific configuration
DEFAULT_RESULTS_CSV = Path("hls_site_results.csv")
OUTPUT_DIR = Path("output/static_maps")

# Cache for site geometries (viewer-specific optimization)
_sites_cache: Optional[gpd.GeoDataFrame] = None


def load_all_sites() -> gpd.GeoDataFrame:
    """
    Load all site geometries (cached) in EPSG:4326 for web mapping.

    This is a viewer-specific wrapper around hls_utils.load_site_geometries()
    that ensures geometries are in web-friendly WGS84 projection.
    """
    global _sites_cache
    if _sites_cache is None:
        sites_gdf = hls_utils.load_site_geometries(hls_utils.SITES_SHAPEFILE, "SITE")
        sites_gdf = sites_gdf.rename(columns={"SITE": "site_id"})
        if sites_gdf.crs != "EPSG:4326":
            sites_gdf = sites_gdf.to_crs("EPSG:4326")
        _sites_cache = sites_gdf
    return _sites_cache


def load_site_geometry(site_id: int):
    """Load the geometry for a specific site."""
    sites_gdf = load_all_sites()
    site = sites_gdf[sites_gdf["site_id"] == site_id]
    if len(site) == 0:
        raise ValueError(f"Site {site_id} not found")
    return site.iloc[0]


# Note: find_granule_by_id and get_band_urls moved to hls_utils module


def create_rgb_image(
    band_urls: dict,
    site_geom,
    site_geom_crs,
    output_path: Path,
    title: str,
    percentile_stretch: tuple = (2, 98),
):
    """
    Create an RGB image from HLS bands with site boundary overlay.

    Args:
        band_urls: Dict with 'red', 'green', 'blue' keys mapping to URLs
        site_geom: Site geometry
        site_geom_crs: CRS of site geometry
        output_path: Where to save the PNG
        title: Image title
        percentile_stretch: Percentiles for contrast stretch (min, max)
    """
    if not all(k in band_urls for k in ["red", "green", "blue"]):
        raise ValueError("Missing one or more RGB band URLs")

    # Load each band with rioxarray (cloud-optimized access)
    chunk_size = dict(band=1, x=512, y=512)

    try:
        red = rxr.open_rasterio(
            band_urls["red"], chunks=chunk_size, masked=True
        ).squeeze("band", drop=True)
        green = rxr.open_rasterio(
            band_urls["green"], chunks=chunk_size, masked=True
        ).squeeze("band", drop=True)
        blue = rxr.open_rasterio(
            band_urls["blue"], chunks=chunk_size, masked=True
        ).squeeze("band", drop=True)
    except Exception as e:
        raise RuntimeError(f"Failed to open bands: {e}")

    # Transform site geometry to match raster CRS
    site_gdf = gpd.GeoSeries([site_geom], crs=site_geom_crs)
    site_transformed = site_gdf.to_crs(red.spatial_ref.crs_wkt)
    geom_transformed = site_transformed.iloc[0]

    # Clip to site geometry with buffer
    buffered = geom_transformed.buffer(100)  # 100m buffer
    geoms = [mapping(buffered)]

    red_cropped = red.rio.clip(geoms, red.spatial_ref.crs_wkt, all_touched=True)
    green_cropped = green.rio.clip(
        geoms, green.spatial_ref.crs_wkt, all_touched=True
    )
    blue_cropped = blue.rio.clip(
        geoms, blue.spatial_ref.crs_wkt, all_touched=True
    )

    # Apply HLS scale factor to convert int16 to reflectance
    red_data = red_cropped.data * hls_utils.HLS_SCALE_FACTOR
    green_data = green_cropped.data * hls_utils.HLS_SCALE_FACTOR
    blue_data = blue_cropped.data * hls_utils.HLS_SCALE_FACTOR

    # Stack into RGB array
    rgb = np.stack([red_data, green_data, blue_data], axis=-1)

    # Normalize for display using percentile stretch
    for i in range(3):
        band_data = rgb[:, :, i]
        valid = (band_data > 0) & (band_data < 1)  # Valid reflectance range
        if valid.any():
            p_low, p_high = np.percentile(band_data[valid], percentile_stretch)
            rgb[:, :, i] = np.clip((band_data - p_low) / (p_high - p_low), 0, 1)
        else:
            rgb[:, :, i] = 0

    # Create figure
    fig, ax = plt.subplots(1, 1, figsize=(10, 10))
    ax.imshow(rgb)

    # Add site boundary in pixel coordinates
    transform = red_cropped.rio.transform()
    inv_transform = ~transform

    if geom_transformed.geom_type == "Polygon":
        exterior_coords = list(geom_transformed.exterior.coords)
        pixel_coords = [inv_transform * (x, y) for x, y in exterior_coords]
        poly = MplPolygon(
            pixel_coords, fill=False, edgecolor="red", linewidth=2
        )
        ax.add_patch(poly)
    elif geom_transformed.geom_type == "MultiPolygon":
        for polygon in geom_transformed.geoms:
            exterior_coords = list(polygon.exterior.coords)
            pixel_coords = [inv_transform * (x, y) for x, y in exterior_coords]
            poly = MplPolygon(
                pixel_coords, fill=False, edgecolor="red", linewidth=2
            )
            ax.add_patch(poly)

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.axis("off")

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, bbox_inches="tight", dpi=150, facecolor="white")
    plt.close(fig)


def granule_id_to_pc_item_id(granule_id: str) -> Optional[str]:
    """
    Convert NASA granule ID to Planetary Computer item ID.

    Planetary Computer uses the same granule ID format as NASA,
    including the version suffix (e.g., .v2.0).

    Format: HLS.L30.T15TXK.2020170T162519.v2.0
    """
    # No conversion needed - PC uses the same ID format as NASA
    return granule_id


def get_pc_tile_url(
    collection: str,
    item_id: str,
    gamma: float = 2.8,
    saturation: float = 1.3,
    sigmoid_contrast: float = 0.40,
    verbose: bool = False,
) -> Optional[str]:
    """Get tile URL from Planetary Computer (for folium viewer)."""
    color_formula = f"Gamma+RGB+{gamma}+Saturation+{saturation}+Sigmoidal+RGB+15+{sigmoid_contrast}"

    tilejson_url = (
        f"https://planetarycomputer.microsoft.com/api/data/v1/item/tilejson.json?"
        f"collection={collection}&item={item_id}&"
        f"assets=B04&assets=B03&assets=B02&"
        f"color_formula={color_formula}"
    )
    try:
        response = requests.get(tilejson_url, timeout=30)
        response.raise_for_status()
        tilejson = response.json()
        return tilejson["tiles"][0]
    except requests.exceptions.HTTPError as e:
        if verbose:
            print(f"       ✗ HTTP {e.response.status_code}: {e}")
        return None
    except Exception as e:
        if verbose:
            print(f"       ✗ Error: {e}")
        return None


def create_folium_viewer(
    results_csv: Path = DEFAULT_RESULTS_CSV,
    output_path: Optional[Path] = None,
    site_id: Optional[int] = None,
    year: Optional[int] = None,
    open_browser: bool = True
):
    """
    Create an interactive folium map with HLS imagery as tile layers.

    Uses Planetary Computer tile service (fast but some granules may not be available).

    Args:
        results_csv: Path to earthaccess results CSV
        output_path: Output HTML path
        site_id: Filter to specific site
        year: Filter to specific year
        open_browser: Whether to open in browser
    """
    if not results_csv.exists():
        print(f"Results file not found: {results_csv}")
        return

    df = pd.read_csv(results_csv)
    print(f"Loaded {len(df)} results from {results_csv}")

    # Apply filters
    if site_id is not None:
        df = df[df["site_id"] == site_id]
    if year is not None:
        df = df[df["year"] == year]

    if len(df) == 0:
        print("No results match the filters.")
        return

    if output_path is None:
        if site_id is not None:
            output_path = Path(f"output/maps/hls_viewer_site{site_id}.html")
        else:
            output_path = Path("output/maps/hls_viewer_earthaccess.html")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get unique sites
    unique_sites = df["site_id"].unique().tolist()

    # Load site geometries and calculate bounds
    sites_gdf = load_all_sites()
    sites_in_results = sites_gdf[sites_gdf["site_id"].isin(unique_sites)]
    total_bounds = sites_in_results.total_bounds  # [minx, miny, maxx, maxy]

    # Create map
    m = folium.Map(tiles=None)

    # Add base layer
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri Basemap",
        overlay=False,
        control=True,
    ).add_to(m)

    # Track success/failure
    layers_added = 0
    layers_failed = 0

    # Add each site's polygon and images
    for sid in unique_sites:
        site = load_site_geometry(sid)
        geometry = site.geometry

        # Add site polygon
        site_geojson = json.loads(gpd.GeoSeries([geometry]).to_json())
        folium.GeoJson(
            site_geojson,
            name=f"Site {sid} Boundary",
            style_function=lambda x: {
                "fillColor": "transparent",
                "fillOpacity": 0,
                "color": "red",
                "weight": 3,
            },
            tooltip=f"Site {sid}",
        ).add_to(m)

        # Add images for this site
        site_images = df[df["site_id"] == sid]

        print(f"\nProcessing {len(site_images)} images for site {sid}:")

        for idx, row in site_images.iterrows():
            product = row["product"]
            granule_id = row["granule_id"]
            year_val = row.get("year", "?")

            print(f"  [{idx}] {year_val} | {product} | {granule_id[:40]}...")

            # Get Planetary Computer collection and item ID
            collection = hls_utils.PC_COLLECTIONS.get(product)
            if not collection:
                print(f"       ✗ Unknown product type: {product}")
                layers_failed += 1
                continue

            item_id = granule_id_to_pc_item_id(granule_id)
            if not item_id:
                print(f"       ✗ Failed to convert granule_id to item_id")
                layers_failed += 1
                continue

            print(f"       → PC item_id: {item_id}")

            # Get tile URL
            tile_url = get_pc_tile_url(collection, item_id, verbose=True)
            if tile_url is None:
                layers_failed += 1
                continue

            print(f"       ✓ Tile URL obtained")

            # Format layer name
            year_val = row.get("year", "")
            cloud_pct = row.get("cloudy_pct", None)
            cloud_text = f"{cloud_pct:.1f}%" if pd.notna(cloud_pct) else "N/A"

            if "sensing_time_utc" in row and pd.notna(row["sensing_time_utc"]):
                date_str = row["sensing_time_utc"][:10]
            else:
                match = re.search(r'\.(\d{7})T\d+', granule_id)
                date_str = f"{match.group(1)[:4]}-{match.group(1)[4:]}" if match else "unknown"

            layer_name = f"Site {sid} | {year_val} | {date_str} | {product} | cloud: {cloud_text}"

            # Add tile layer
            folium.TileLayer(
                tiles=tile_url,
                attr="Microsoft Planetary Computer - HLS",
                name=layer_name,
                overlay=True,
                control=True,
                show=False,
            ).add_to(m)
            layers_added += 1

    # Fit map to bounds
    m.fit_bounds([[total_bounds[1], total_bounds[0]], [total_bounds[3], total_bounds[2]]])

    # Add layer control
    folium.LayerControl(collapsed=False).add_to(m)

    # Add title
    num_sites = len(unique_sites)
    years = sorted(df['year'].unique())
    years_str = ", ".join(map(str, years))

    title_html = f'''
    <div style="position: fixed; top: 10px; left: 50px; z-index: 1000;
                background-color: white; padding: 15px; border-radius: 5px;
                border: 2px solid gray; font-family: Arial; max-width: 400px;">
        <b>HLS Imagery Viewer (Earthaccess)</b><br>
        Sites: {num_sites} | Layers: {layers_added} | Years: {years_str}<br>
        <small>Toggle layers in the right panel.<br>
        Red outline = site boundary</small>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))

    # Save
    m.save(str(output_path))

    print(f"\n{'='*70}")
    print(f"Folium viewer created!")
    print(f"{'='*70}")
    print(f"Output: {output_path.resolve()}")
    print(f"Layers added: {layers_added}")
    print(f"Layers failed: {layers_failed}")
    if layers_failed > 0:
        print(f"\nNote: {layers_failed} images not available in Planetary Computer.")
        print(f"Use --export-maps to create PNGs from NASA data directly.")
    print(f"{'='*70}")

    if open_browser:
        webbrowser.open(f"file://{output_path.absolute()}")


def export_images_from_csv(
    results_csv: Path = DEFAULT_RESULTS_CSV,
    output_dir: Optional[Path] = None,
    site_id: Optional[int] = None,
    year: Optional[int] = None,
):
    """
    Export static PNG images for HLS results.

    Args:
        results_csv: Path to earthaccess results CSV
        output_dir: Output directory (default: output/static_maps)
        site_id: Filter to specific site (None = all)
        year: Filter to specific year (None = all)
    """
    if not results_csv.exists():
        print(f"Results file not found: {results_csv}")
        print(
            "Run hls_imagery_search_earthaccess.py first to generate results."
        )
        return

    # Load results
    df = pd.read_csv(results_csv)
    print(f"Loaded {len(df)} results from {results_csv}")

    # Validate columns
    required_cols = ["site_id", "year", "product", "granule_id"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"Error: Missing required columns: {missing}")
        return

    # Apply filters
    if site_id is not None:
        df = df[df["site_id"] == site_id]
    if year is not None:
        df = df[df["year"] == year]

    if len(df) == 0:
        print("No results match the filters.")
        return

    if output_dir is None:
        output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # Configure GDAL for NASA cloud access
    hls_utils.configure_gdal_for_nasa()

    # Authenticate with earthaccess
    print("\nAuthenticating with NASA Earthdata...")
    earthaccess.login(strategy="netrc")
    print("[OK] Authentication successful\n")

    print(f"Exporting {len(df)} static images...\n")

    success_count = 0
    fail_count = 0

    # Process each result
    for idx, row in tqdm(df.iterrows(), total=len(df), desc="Creating images"):
        site_id_val = row["site_id"]
        year_val = row["year"]
        product = row["product"]
        granule_id = row["granule_id"]

        # Extract date from granule_id or sensing_time_utc
        if "sensing_time_utc" in row and pd.notna(row["sensing_time_utc"]):
            date_str = row["sensing_time_utc"][:10]
        else:
            # Try to extract from granule ID (format: HLS.L30.T15TWM.2013163T170013...)
            match = re.search(r"\.(\d{7})T\d+", granule_id)
            if match:
                julian_date = match.group(1)
                date_str = f"{julian_date[:4]}-{julian_date[4:]}"
            else:
                date_str = "unknown"

        output_file = (
            output_dir
            / f"site_{site_id_val}_{year_val}_{date_str}_{product}.png"
        )

        # Skip if already exists
        if output_file.exists():
            success_count += 1
            continue

        try:
            # Load site geometry
            site = load_site_geometry(site_id_val)
            geometry = site.geometry

            # Search for granule to get data URLs
            granule = hls_utils.find_granule_by_id(granule_id)
            if granule is None:
                print(f"\n  Warning: Could not find granule {granule_id}")
                fail_count += 1
                continue

            # Get RGB band URLs
            band_urls = hls_utils.get_rgb_band_urls(granule, product)
            if not band_urls or len(band_urls) < 3:
                print(f"\n  Warning: Could not get band URLs for {granule_id}")
                fail_count += 1
                continue

            # Create title
            cloud_pct = row.get("cloudy_pct", None)
            cloud_text = (
                f" | Cloud: {cloud_pct:.1f}%" if pd.notna(cloud_pct) else ""
            )
            title = f"Site {site_id_val} | {date_str} | {product}{cloud_text}"

            # Create RGB image
            create_rgb_image(
                band_urls=band_urls,
                site_geom=geometry,
                site_geom_crs="EPSG:4326",
                output_path=output_file,
                title=title,
            )

            success_count += 1

        except Exception as e:
            print(f"\n  Error creating {output_file.name}: {e}")
            fail_count += 1

    # Summary
    print(f"\n{'='*70}")
    print(f"Export complete!")
    print(f"{'='*70}")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Output directory: {output_dir.resolve()}")
    print(f"{'='*70}")


def main():
    parser = argparse.ArgumentParser(
        description="HLS Imagery Viewer for Earthaccess Output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create interactive folium viewer (default, fast):
  python hls_viewer_earthaccess.py --site 1079
  python hls_viewer_earthaccess.py --results my_results.csv
  python hls_viewer_earthaccess.py --year 2020

  # Export static PNG images (requires downloading data from NASA):
  python hls_viewer_earthaccess.py --export-maps --site 1079
  python hls_viewer_earthaccess.py --export-maps --year 2020

  # Don't open browser:
  python hls_viewer_earthaccess.py --site 1079 --no-browser
        """,
    )

    parser.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS_CSV,
        help=f"Path to earthaccess results CSV (default: {DEFAULT_RESULTS_CSV})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (HTML for viewer, directory for maps)",
    )
    parser.add_argument(
        "--site", type=int, default=None, help="Filter to specific site ID"
    )
    parser.add_argument(
        "--year", type=int, default=None, help="Filter to specific year"
    )
    parser.add_argument(
        "--export-maps",
        action="store_true",
        help="Export static PNG maps instead of creating folium viewer",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser after generating viewer",
    )

    args = parser.parse_args()

    if args.export_maps:
        # Export static PNG images
        export_images_from_csv(
            results_csv=args.results,
            output_dir=args.output,
            site_id=args.site,
            year=args.year,
        )
    else:
        # Create interactive folium viewer (default)
        create_folium_viewer(
            results_csv=args.results,
            output_path=args.output,
            site_id=args.site,
            year=args.year,
            open_browser=not args.no_browser,
        )


if __name__ == "__main__":
    main()
