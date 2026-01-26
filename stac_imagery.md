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

The `--mask` argument uses the Landsat `qa_pixel` band, a 16-bit packed bitmask where each bit encodes a quality condition. The following table shows all bit definitions:

| Bit | Flag | When set (= 1) |
|-----|------|-----------------|
| 0 | Fill | Pixel is fill / no data |
| 1 | Dilated Cloud | Cloud dilation buffer pixel |
| 2 | Cirrus | High-confidence cirrus |
| 3 | Cloud | High-confidence cloud |
| 4 | Cloud Shadow | High-confidence cloud shadow |
| 5 | Snow | High-confidence snow / ice |
| 6 | Clear | Pixel is clear (no cloud, shadow, snow, or cirrus) |
| 7 | Water | Pixel is water |
| 8–9 | Cloud Confidence | 00=None, 01=Low, 10=Medium, 11=High |
| 10–11 | Cloud Shadow Confidence | 00=None, 01=Low, 10=Medium, 11=High |
| 12–13 | Snow/Ice Confidence | 00=None, 01=Low, 10=Medium, 11=High |
| 14–15 | Cirrus Confidence | 00=None, 01=Low, 10=Medium, 11=High |

### Preset masks

These are mutually exclusive options that define which pixels to **keep**:

| Option | Behaviour |
|--------|-----------|
| `clear-only` | Keep only pixels where bit 6 (Clear) = 1. Most restrictive; recommended for compositing. |
| `clear-only-inc-water` | Keep pixels where bit 6 (Clear) = 1 **or** bit 7 (Water) = 1. Same as `clear-only` but retains water bodies. |

### Individual bit masks

These define which pixels to **remove** (set to NaN). Combine with commas:

| Option | Bit | Removes |
|--------|-----|---------|
| `fill` | 0 | Fill / no-data pixels |
| `dilated-cloud` | 1 | Cloud dilation buffer pixels |
| `cirrus` | 2 | Cirrus cloud pixels |
| `cloud` | 3 | Cloud pixels |
| `shadow` | 4 | Cloud shadow pixels |
| `snow` | 5 | Snow / ice pixels |
| `water` | 7 | Water pixels |

### Examples

```bash
# Most restrictive — clear land only (excludes water)
--mask clear-only

# Clear land and water (excludes clouds, shadow, snow, cirrus)
--mask clear-only-inc-water

# Remove clouds and shadows only
--mask cloud,shadow

# Remove clouds, shadows, and cirrus
--mask cloud,shadow,cirrus

# Remove clouds, shadows, and snow/ice
--mask cloud,shadow,snow
```

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
