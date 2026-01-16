# Satellite Imagery Acquisition Methodology

In preparation for future analysis, satellite imagery was obtained from NASA's Harmonized Landsat Sentinel-2 (HLS) version 2.0 dataset. The HLS product harmonizes observations from Landsat 8/9 Operational Land Imager ([L30 product](https://planetarycomputer.microsoft.com/dataset/hls2-l30)) and Sentinel-2 Multispectral Instrument ([S30 product](https://planetarycomputer.microsoft.com/dataset/hls2-s30)) into a consistent 30-meter resolution, atmospherically corrected surface reflectance dataset. An automated workflow implemented in Python using NASA's [earthaccess library](https://www.earthdata.nasa.gov/data/tools/earthaccess) for data discovery and [GDAL](https://gdal.org/en/stable/) for raster processing was developed to search, assess, and acquire imagery for each study site.

## Imagery Search

Candidate imagery was identified by querying NASA's Common Metadata Repository (CMR) for HLS granules intersecting each study site boundary. Search parameters included a configurable target date with an adjustable temporal window (±N days), allowing flexibility to prioritize imagery from specific periods of interest. Both Landsat and Sentinel-2 collections were queried for each combination of site and year, enabling multi-temporal analysis across the study period. For each query, candidate granules were ranked by their temporal proximity to the target date, with those closest to the target prioritized for subsequent assessment. Search results were compiled into a structured dataset for systematic evaluation.

## Imagery Assessment

Each candidate image underwent automated cloud quality assessment using the HLS Fmask quality assurance band. The Fmask band encodes pixel-level quality information as bitwise flags, which were decoded to calculate three key metrics: direct cloud coverage percentage, cloud shadow percentage, and adjacent-to-cloud/shadow percentage. Critically, these statistics were computed only within each study site's boundaries rather than across the entire satellite tile, providing site-specific quality metrics that more accurately reflected usability for the analysis.

A rejection threshold was applied to exclude imagery with excessive cloud contamination. Among acceptable candidates, the image closest to the target date was selected as the primary acquisition for each site-year combination. Results were categorized by status: imagery meeting quality criteria ("found"), candidates existing but failing to meet thresholds within the temporal window ("not-found"), or no suitable candidates available ("none-found").

For those sites and years that did not have an ideal ("found") candidate, a manual visual quality check was used. Interactive web maps were generated for rapid review of candidate imagery, and RGB composite previews with site boundary overlays enabled manual verification of automated selections. This step ensured that selected imagery was suitable for downstream classification analysis.

## Imagery Acquisition

Selected imagery was downloaded from [NASA's Earthdata Cloud storage](https://www.earthdata.nasa.gov/). All spectral bands were clipped to each study site's boundary. The clip method was inclusive, meaning that any pixels that were within or intersected with the site boundary were kept. The clipped bands were then stacked into multi-band Cloud-Optimized GeoTIFFs (COGs), a format optimized for efficient cloud-based access and processing. The original integer data type and HLS scale factor (0.0001) were preserved in the output metadata, allowing conversion to physical reflectance values during subsequent analysis.

The Fmask quality band was exported separately for each acquisition, to be later processed into a water mask. Output files were organized systematically by site identifier, acquisition date, and sensor platform, facilitating reproducible analysis workflows.

## Summary

This three-step workflow—search, assessment, and acquisition—provided an automated, reproducible method for obtaining cloud-screened satellite imagery from the HLS archive for areas of interest. The resulting clipped imagery composites and associated quality masks served as inputs for land cover classification analysis at each study site.
