# Satellite Imagery Acquisition Methodology

Satellite imagery for this analysis was obtained from NASA's Harmonized Landsat Sentinel-2 (HLS) version 2.0 dataset. The HLS product harmonizes observations from Landsat 8/9 Operational Land Imager (L30 product) and Sentinel-2 Multispectral Instrument (S30 product) into a consistent 30-meter resolution, atmospherically corrected surface reflectance dataset. An automated workflow implemented in Python using NASA's earthaccess library for data discovery and GDAL for raster processing was developed to search, assess, and acquire imagery for each study site.

## Step 1: Imagery Search

Candidate imagery was identified by querying NASA's Common Metadata Repository (CMR) for HLS granules intersecting each study site boundary. Search parameters included a configurable target date with an adjustable temporal window (±N days), allowing flexibility to prioritize imagery from specific periods of interest. Both Landsat and Sentinel-2 collections were queried for each combination of site and year, enabling multi-temporal analysis across the study period. For each query, candidate granules were ranked by their temporal proximity to the target date, with those closest to the target prioritized for subsequent assessment. Search results were compiled into a structured dataset for systematic evaluation.

## Step 2: Imagery Assessment

Each candidate image underwent automated cloud quality assessment using the HLS Fmask quality assurance band. The Fmask band encodes pixel-level quality information as bitwise flags, which were decoded to calculate three key metrics: direct cloud coverage percentage, cloud shadow percentage, and adjacent-to-cloud/shadow percentage. Critically, these statistics were computed only within each study site's boundaries rather than across the entire satellite tile, providing site-specific quality metrics that more accurately reflected usability for the analysis.

A rejection threshold was applied to exclude imagery with excessive cloud contamination. Among acceptable candidates, the image closest to the target date was selected as the primary acquisition for each site-year combination. Results were categorized by status: imagery meeting quality criteria ("found"), candidates existing but failing to meet thresholds within the temporal window ("not-found"), or no suitable candidates available ("none-found").

Visual quality assurance supplemented the automated assessment. Interactive web maps were generated for rapid review of candidate imagery, and RGB composite previews with site boundary overlays enabled manual verification of automated selections. This step ensured that selected imagery was suitable for downstream classification analysis.

## Step 3: Imagery Acquisition

Selected imagery was downloaded from NASA's Earthdata Cloud storage. All spectral bands were clipped to each study site's boundary with an optional spatial buffer to ensure complete coverage of areas of interest. The clipped bands were then stacked into multi-band Cloud-Optimized GeoTIFFs (COGs), a format optimized for efficient cloud-based access and processing. The original integer data type and HLS scale factor (0.0001) were preserved in the output metadata, allowing conversion to physical reflectance values during subsequent analysis.

The Fmask quality band was exported separately for each acquisition, enabling pixel-level quality masking during classification. Output files were organized systematically by site identifier, acquisition date, and sensor platform, facilitating reproducible analysis workflows.

## Summary

This three-step workflow—search, assessment, and acquisition—provided an automated, reproducible method for obtaining cloud-screened satellite imagery from the HLS archive. The resulting clipped imagery composites and associated quality masks served as inputs for land cover classification analysis at each study site.
