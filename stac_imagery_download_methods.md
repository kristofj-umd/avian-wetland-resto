# Methods: Imagery from Landsat for 2010

## Overview

For two sites (site ID = 496 and 523), data prior to the beginning of the Harmonized Landsat-Sentinel Catalog (2013) was desired. Both Landsat 5 and Landsat 7 constellations were operating in 2010 and provide imagery for this period via the [Landsat Collection 2 Level-2 surface reflectance archive](https://planetarycomputer.microsoft.com/dataset/landsat-c2-l2) hosted by the [Planetary Computer](https://planetarycomputer.microsoft.com/).

## Imagery Search

A python script was developed to search through planetary computer's imagery archive for imagery from a given date range that covered a given area of interest. At this point the list of imagery found could be reviewed and from there a determination could be made to proceed to the next stage which is downloading the imagery.

## Imagery Download

Full satellite scenes are large and cumbersome and could include unwanted artifacts like clouds or shadows. So the download functionality provided by the script included a number of different options depending on the desired outcome.

These include:

**Masking** based on the Pixel Quality Assessment Band (`qa_pixel`) to filter out areas considered to be clouds or snow; or, conversely, to only include areas that are considered clear ([see Masking Options for more information](stac_imagery.md#masking-options))

**Compositing** allows for a series of overlapping images to be laid on one another to produce a composite image. The final pixel is the result of whatever operation is applied to all of the contributing pixels. In this case, the _median_ value is used. This is a common approach when creating temporal composites. It also serves as a means of augmenting [the inherent striping of Landsat 7 imagery due to the Scan Line Corrector failure](https://www.usgs.gov/faqs/what-landsat-7-etm-slc-data).

Regardless of whether the data is composited into a single multispectral image for the given date range or kept as single images per date, the imagery are filtered to only include the surface reflectance bands, clipped to the area of interest, rescaled using a specific scale and offset for each band, and finally, output as a Cloud Optimized GeoTIFF (COG) for quick reading and visualizing.

## Result

Ultimately, the imagery produced by this tool utlized the temporal composite approach as well as the masking so that only clear pixels as well as those with any water were allowed through.

The imagery is labelled as:  
`siteID_date_imageItemID.tif`

The composite imagery is labelled as:  
`siteID_startDate-endDate_composite_maskType.tif`
