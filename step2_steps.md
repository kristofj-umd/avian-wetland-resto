# Step 2: Restoration Site Image Classification

## 1. Prep & band mapping

- Add your multispectral raster to a map in ArcGIS Pro.

  1.3 Band Mapping:

* **Landsat (HLSL30)**:

  - B1: Coastal Aerosol
  - B2: Blue
  - B3: Green
  - B4: Red
  - B5: NIR
  - B6: SWIR1
  - B7: SWIR2
  - B9: Cirrus
  - B10: Thermal1
  - B11: Thermal2

* **Sentinel (HLSS30)**:
  - B1: Coastal Aerosol
  - B2: Blue
  - B3: Green
  - B4: Red
  - B5: Red Edge1
  - B6: Red Edge2
  - B7: Red Edge3
  - B8: NIR Broad
  - B8A: NIR Narrow
  - B9: Water Vapor
  - B10: Cirrus
  - B11: SWIR1
  - B12: SWIR2

## 2. Build indices

Use pre-set indices under the [**Indices** tab](https://doc.arcgis.com/en/imagery/workflows/resources/visualizing-spectral-indices.htm) to create:

- **NDVI** (Normalized Difference Vegetation Index or greenness)
- **MNDWI** (Modified Normalized Difference Water Index or open water)
- **NDMI** (Normalized Difference Moisture Index or soil moisture)

Create:

- **NDVI** = (NIR − Red)/(NIR + Red).
- **MNDWI** = (Green − SWIR1)/(Green + SWIR1).
- **NDMI** = (NIR − SWIR1)/(NIR + SWIR1).

Name outputs clearly since these are generated on the fly (eg. site1_2020_NDVI).

🤓Pro Tip: rasters may not initially appear to contain the data you expect. The `stretch` symbology may be disguising the real data. Try switching to `classify` or even `unique values` to see if the data you expect is really there.

## 3. Make a water mask with an automatic cutoff (Otsu)

You have two options for delineating a water mask: 1) use the water bit within the Fmask quality bits band, or 2) or use threshold value on the MNDWI index. I give you instructions for both below:

### 3.1. Fmask water mask

The Fmask is a bitmask raster that indicates, within its various bits, which pixels have been determined to contain clouds, snow, water, etc. (see _**Fmask**_ within [the user guide to HLS](https://lpdaac.usgs.gov/documents/1698/HLS_User_Guide_V2.pdf) and [this research paper](https://doi.org/10.1016/j.rse.2019.05.024) for details). The water bit in these Fmasks is bit 5.

- Open the [**Bitwise And** raster function](https://pro.arcgis.com/en/pro-app/latest/help/analysis/raster-functions/bitwise-and-function.htm).
  - Set **First raster** = the Fmask raster
  - Set **Second raster** = 32 (the water bit)

This is essentially the same as saying "set every pixel with water to true (1) and everything else to false (0)".

### 3.2. MNDWI water mask

Open [**Raster Calculator**](https://pro.arcgis.com/en/pro-app/latest/tool-reference/analysis/raster-calculator.htm).

- Expression: `MNDWI > threshold_value`
  - e.g. `MNDWI > -0.2`
- Output: your water mask

### 3.3. Create water only raster

No matter which approach you took above to creating a water raster, we now need to set all of those non-water pixels (0) to NoData (or Null) using the Set Null tool.

- Open [**Set Null**](https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/set-null.htm). ([ArcGIS Pro][3])
- In the tool, set:

  - **Input conditional raster** = your water mask raster
  - **Expression**: `VALUE = 0`

  - **Input false raster or constant value** = `1` (constant)

- Output result:

  - **Water pixels** have a value of 1
  - **Non-water pixels** are **NoData** ([ArcGIS Pro][4])

> Set Null behavior: when the condition is true (VALUE=0), output becomes NoData; otherwise it returns the false raster/constant. ([ArcGIS Pro][4])

🤓Pro Tip: (Optional) Right-click any result layer → **Data** → [**Export Raster**](https://pro.arcgis.com/en/pro-app/latest/help/data/imagery/export-or-convert-raster-datasets.htm) to save a permanent version of it for later tools. ([ArcGIS Pro][7])

## 4. Compute distance-to-water

- Run **Euclidean Distance**, which is now called [**Distance Accumulation**](https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/distance-accumulation.htm).

  - **Input Raster** = your water only raster (the rest should be NoData)

> Output will be a float raster of straight-line distance (meters) from each pixel to the nearest water pixel. ([ArcGIS Pro][8])

## 5. Make vegetation and moisture masks

### 5.1. Vegetation mask

Apply **Binary Thresholding** to your NDVI raster to create a 0/1 **Veg** mask.

### 5.2. Moisture mask

Either

- Use **Binary Thresholding** on NDMI (automatic)

`-OR-`

- Use **Raster Calculator** (Analysis → Tools → Spatial Analyst → [**Raster Calculator**](https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/raster-calculator.htm)) with a simple expression like `NDMI > 0.05` to create **Moist = 1/0**. ([ArcGIS Pro][9])

## 6. Build an **emergent vegetation** mask with a simple rule

- Open **Raster Calculator** and use a conditional expression to combine masks:

  - Example expression: `Con( (Veg == 1) & (Moist == 1) & (EucDist <= 60), 1, 0 )`
  - This says: emergent = green **and** moist **and** within 60m of water
    - Change the `60` to whatever distance you decide to use for this study.

- (Optional) Build a **riparian** mask the same way (e.g., `Con(EucDist <= 120, 1, 0)`
  - you can AND with moisture if you want “riparian-vegetated”).

> By using the **Con** function, the output of this tool will be another 0/1 mask indicating 1=emergent veg, 0=anything else.

## 7. Clean up with object-based smoothing (Segmentation)

Segmentation is worth considering because with 30 m pixels, pixel-by-pixel thresholds produce speckle and jittery shorelines that can dominate area totals in small polygons. Grouping similar neighboring pixels into segments and classifying by majority enforces a minimum patch size, stabilizes boundaries, and makes results more repeatable across years.

### 7.1. Stack indices

Combine your index rasters (NDVI, MNDWI, NDMI) into a 3-band stack

- [**Composite Bands**](https://pro.arcgis.com/en/pro-app/latest/help/analysis/raster-functions/composite-bands-function.htm)

### 7.2. Segment the stack into objects

Goal: build a segmented raster where each region represents a different combination of NDVI/MNDWI/NDMI.

Tool: [**Segment Mean Shift**](https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/segment-mean-shift.htm)

**How Mean Shift segmentation works (basic mental model)**

- It groups pixels that are:

  - **close in value** (spectrally similar across NDVI/MNDWI/NDMI), and
  - **close in space** (nearby pixels)

- The parameters control how strict those “close” criteria are.

**Key parameters you’ll tune**

- **Spectral Detail**

  - Think: “How different do pixels need to be before I split them into different segments?”
  - Higher spectral detail → more segments, finer boundaries
  - Lower spectral detail → fewer segments, more smoothing

- **Spatial Detail**

  - Think: “How strongly do I prefer compact, local segments?”
  - Higher spatial detail → segments stay compact / local (more, smaller segments)
  - Lower spatial detail → segments can spread further if values are similar (larger segments)

- **Min Segment Size**

  - Think: “What’s the smallest patch I’m willing to keep?”
  - Larger value removes tiny patches (good for speckle, but can remove real small features)

### 7.3 Convert pixel classification to segment classification

Use **Zonal Statistics** (zones = segments, values = emergent):

- [**Zonal Statistics**](https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/zonal-statistics.htm)

  - input raster (zones) = segmented raster
  - input table (values) = emergent raster

- Statistic choice:

  - **MAJORITY**: segment becomes 1 if most pixels in that segment are 1 (simple and robust)
  - **MEAN**: gives fraction emergent in the segment (0–1). Then you threshold (e.g., mean ≥ 0.5)

- Or use [**Zonal Statistics as Table**](https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/zonal-statistics-as-table.htm) if you want the segment-level stats as a table you can inspect/join.

### 7.4 (Optional) pixel-only alternative

If you don’t want segmentation, a quick cleanup is:

- [**Majority Filter**](https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/majority-filter.htm)

But it’s worth knowing the trade-off:

- Majority Filter uses a moving window (like 3×3 pixels).
- It smooths noise, but it **doesn’t respect real boundaries** as well (can erode narrow shoreline bands or smear small ponds).
- Segments usually preserve shoreline structure better.

## 8. Summarize area by wetland polygons

- Ensure class rasters are integer **0/1**. If needed, recast with Raster Calculator (`Con(expr,1,0)`).
- Run **Tabulate Area**: zones = your wetland polygons (zone field = polygon ID), class raster = each mask (Water, Emergent, Riparian).

  - Tool: [**Tabulate Area**](https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/tabulate-area.htm). ([ArcGIS Pro][15])

- Convert cell counts to area (count × cell_area); add hectares/acres fields as needed. (See also “Working with Tabulate Area”.) ([ArcGIS Pro][16])

[1]: https://pro.arcgis.com/en/pro-app/latest/tool-reference/environment-settings/cell-size.htm?utm_source=chatgpt.com "Cell Size (Environment setting)—ArcGIS Pro | Documentation"
[2]: https://pro.arcgis.com/en/pro-app/latest/tool-reference/environment-settings/snap-raster.htm?utm_source=chatgpt.com "Snap Raster (Environment setting)—ArcGIS Pro"
[3]: https://pro.arcgis.com/en/pro-app/latest/help/analysis/raster-functions/band-arithmetic-function.htm?utm_source=chatgpt.com "Band Arithmetic function—ArcGIS Pro | Documentation"
[4]: https://pro.arcgis.com/en/pro-app/latest/help/analysis/raster-functions/ndvi-function.htm?utm_source=chatgpt.com "NDVI function—ArcGIS Pro | Documentation"
[5]: https://pro.arcgis.com/en/pro-app/3.5/help/analysis/raster-functions/calculator-function.htm?utm_source=chatgpt.com "Calculator function—ArcGIS Pro | Documentation"
[6]: https://pro.arcgis.com/en/pro-app/latest/help/analysis/raster-functions/binary-thresholding-function.htm?utm_source=chatgpt.com "Binary Thresholding function—ArcGIS Pro | Documentation"
[7]: https://pro.arcgis.com/en/pro-app/latest/help/data/imagery/export-or-convert-raster-datasets.htm?utm_source=chatgpt.com "Export or convert raster datasets—ArcGIS Pro | Documentation"
[8]: https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/euclidean-distance.htm?utm_source=chatgpt.com "Euclidean Distance (Spatial Analyst) - ArcGIS Pro Resources"
[9]: https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/raster-calculator.htm?utm_source=chatgpt.com "Raster Calculator (Spatial Analyst) - ArcGIS Pro Resources"
[10]: https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/con-.htm?utm_source=chatgpt.com "Con (Spatial Analyst)—ArcGIS Pro | Documentation"
[11]: https://pro.arcgis.com/en/pro-app/latest/help/analysis/raster-functions/composite-bands-function.htm?utm_source=chatgpt.com "Composite Bands function—ArcGIS Pro | Documentation"
[12]: https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/segment-mean-shift.htm?utm_source=chatgpt.com "Segment Mean Shift (Spatial Analyst)—ArcGIS Pro"
[13]: https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/zonal-statistics.htm?utm_source=chatgpt.com "Zonal Statistics (Spatial Analyst)—ArcGIS Pro | Documentation"
[14]: https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/majority-filter.htm?utm_source=chatgpt.com "Majority Filter (Spatial Analyst)—ArcGIS Pro | Documentation"
[15]: https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/tabulate-area.htm?utm_source=chatgpt.com "Tabulate Area (Spatial Analyst)—ArcGIS Pro | Documentation"
[16]: https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/h-working-with-tabulate-area.htm?utm_source=chatgpt.com "Working with Tabulate Area—ArcGIS Pro | Documentation"
