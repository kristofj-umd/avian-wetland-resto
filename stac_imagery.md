# Landsat Collection 2 Level-2 Imagery Download

## Overview

Download Landsat Collection 2 Level-2 surface reflectance imagery from Microsoft Planetary Computer. The script provides a unified workflow for searching, reviewing, and downloading satellite imagery with optional cloud masking and temporal compositing.

## Data Source

- **Provider:** Microsoft Planetary Computer
- **Collection:** Landsat Collection 2 Level-2 (`landsat-c2-l2`)
- **Endpoint:** `https://planetarycomputer.microsoft.com/api/stac/v1`
- **Data type:** Surface Reflectance (atmospherically corrected)

## Output Bands

The script outputs 8-band GeoTIFFs with the following spectral bands:

| Band | Name | Wavelength | Description |
|------|------|------------|-------------|
| 1 | coastal | 0.43-0.45 μm | Coastal Aerosol |
| 2 | blue | 0.45-0.51 μm | Blue |
| 3 | green | 0.53-0.59 μm | Green |
| 4 | red | 0.64-0.67 μm | Red |
| 5 | nir08 | 0.85-0.88 μm | Near Infrared |
| 6 | swir16 | 1.57-1.65 μm | Shortwave Infrared 1 |
| 7 | swir22 | 2.11-2.29 μm | Shortwave Infrared 2 |
| 8 | lwir11 | 10.6-11.19 μm | Thermal Infrared (Surface Temperature) |

**Note:** The `qa_pixel` band is used for cloud/shadow masking but is NOT included in the output GeoTIFF.

## Output Values

**Default:** Raw Digital Number (DN) values as stored in Landsat Collection 2 Level-2 data.

**With `--rescale` flag:** Converts DN to surface reflectance using:
```
reflectance = DN * 0.0000275 - 0.2
```
Rescaled values are in the approximate range -0.2 to 1.6.

## Usage

### Basic Search and Download

```bash
python stac_imagery_download.py \
    --output-dir data/imagery/landsat \
    --aoi data/sites.geojson \
    --start-date 2020-06-01 \
    --end-date 2020-08-31 \
    --cloud-cover 20
```

### With Cloud Masking and Compositing

```bash
python stac_imagery_download.py \
    --output-dir data/imagery/landsat \
    --aoi data/sites.geojson \
    --start-date 2020-06-01 \
    --end-date 2020-08-31 \
    --mask clear-only \
    --composite \
    --yes
```

### Command-Line Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--output-dir` | Yes | Output directory for imagery |
| `--aoi` | Yes | Path to AOI spatial dataset (shapefile, geojson, etc.) |
| `--aoi-filter` | No | Filter AOI by attribute (format: `column:value1,value2`) |
| `--start-date` | No | Start date for search (YYYY-MM-DD) |
| `--end-date` | No | End date for search (YYYY-MM-DD) |
| `--cloud-cover` | No | Maximum cloud cover percentage (0-100) |
| `--mask` | No | Pixel types to mask (`cloud,shadow` or `clear-only`) |
| `--composite` | No | Create temporal median composite |
| `--rescale` | No | Convert DN to surface reflectance (default: raw DN) |
| `--log-file` | No | Enable logging to file in output directory |
| `--log-level` | No | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `-y, --yes` | No | Auto-proceed with download (skip user prompt) |

## Masking Options

The `--mask` argument supports the following options:

- `clear-only`: Keep only pixels flagged as clear (recommended)
- `cloud`: Mask cloud pixels
- `shadow`: Mask cloud shadow pixels
- `cirrus`: Mask cirrus cloud pixels
- Combinations: `cloud,shadow` or `cloud,shadow,cirrus`

## Output Files

### Individual Images (default)
```
aoi{id}_{YYYYMMDD}_{scene_id}.tif
```

### Temporal Composites (`--composite`)
```
aoi{id}_{start_date}-{end_date}_composite.tif
```

## Workflow Phases

1. **Search Phase**: Query Planetary Computer for imagery matching spatial, temporal, and cloud cover criteria
2. **Review Phase**: Display summary statistics and item list; export options available
3. **Download Phase**: Download, clip, mask, and optionally composite imagery

## Configuration Constants

The script uses constants defined at the top of `stac_imagery_download.py`:

```python
PC_CATALOG_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION_ID = "landsat-c2-l2"
SPECTRAL_BANDS = ["coastal", "blue", "green", "red", "nir08", "swir16", "swir22", "lwir11"]
QA_BAND = "qa_pixel"
SCALE_FACTOR = 0.0000275
SCALE_OFFSET = -0.2
```

To support different collections, modify these constants.

## Dependencies

- `pystac-client`: STAC API client
- `planetary-computer`: Microsoft Planetary Computer authentication
- `stackstac`: Efficient STAC to xarray loading
- `rioxarray`: Raster I/O with xarray
- `geopandas`: Spatial data handling
- `xarray`: N-dimensional arrays
- `numpy`: Array operations
- `tqdm`: Progress bars

## Verification

After running, verify output with:

```bash
# Check band count (should be 8)
gdalinfo output.tif | grep "Band "

# Check statistics (values should NOT be NaN)
gdalinfo -stats output.tif

# Expected reflectance range: approximately -0.2 to 1.6
```
