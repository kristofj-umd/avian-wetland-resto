# Methods: Imagery from Landsat for 2010

## Overview

For two sites (site ID = 496 and 523), data prior to the beginning of the Harmonized Landsat-Sentinel Catalog (2013) was desired. Both Landsat 5 and Landsat 7 constellations were operating in 2010 and provide imagery for this period via the [Landsat Collection 2 Level-2 surface reflectance STAC collection](https://planetarycomputer.microsoft.com/dataset/landsat-c2-l2) hosted by the [Planetary Computer](https://planetarycomputer.microsoft.com/).

## Imagery Search

A python script was developed to search through planetary computer's imagery archive for imagery from a given date range that covered a given area of interest. At this point the list of imagery found could be reviewed and from there a determination could be made to proceed to the next stage which is downloading the imagery.

## Imagery Download

Full satellite scenes are large and cumbersome and could include unwanted artifacts like clouds or shadows. So the download functionality provided by the script included a number of different options depending on the desired outcome.

These include:

**Masking** based on the Pixel Quality Assessment Band (`qa_pixel`) to filter out areas considered to be clouds or snow; or, conversely, to only include areas that are considered clear ([see Masking Options for more information](stac_imagery.md#masking-options))

**Compositing** allows for a series of overlapping images to be laid on one another to produce a composite image. The final pixel is the result of whatever operation is applied to all of the contributing pixels. In this case, the _median_ value is used. This is a common approach when creating temporal composites. It also serves as a means of augmenting [the inherent striping of Landsat 7 imagery due to the Scan Line Corrector failure](https://www.usgs.gov/faqs/what-landsat-7-etm-slc-data).

Regardless of whether the data is composited into a single multispectral image for the given date range or kept as single images per date, the imagery are filtered to only include the surface reflectance bands, clipped to the area of interest, rescaled using a specific scale and offset for each band, and finally, output as a Cloud Optimized GeoTIFF (COG) for quick reading and visualizing.

## Results

Ultimately, the imagery produced by this tool utlized the temporal composite approach as well as the masking so that only clear pixels as well as those with any water were allowed through.

### Image Dates and Cloud Cover

| Site ID | Item ID                         | Date       | Cloud% |
| ------- | ------------------------------- | ---------- | ------ |
| 496     | LT05_L2SP_020030_20100721_02_T1 | 2010-07-21 | 24.0   |
| 496     | LE07_L2SP_021029_20100720_02_T1 | 2010-07-20 | 26.0   |
| 496     | LE07_L2SP_020030_20100713_02_T1 | 2010-07-13 | 99.0   |
| 496     | LT05_L2SP_021029_20100712_02_T1 | 2010-07-12 | 61.0   |
| 496     | LT05_L2SP_020030_20100705_02_T1 | 2010-07-05 | 21.0   |
| 496     | LE07_L2SP_021029_20100704_02_T1 | 2010-07-04 | 9.0    |
| 496     | LE07_L2SP_020030_20100627_02_T1 | 2010-06-27 | 76.0   |
| 496     | LT05_L2SP_021029_20100626_02_T1 | 2010-06-26 | 75.0   |
| 496     | LT05_L2SP_020030_20100619_02_T1 | 2010-06-19 | 52.0   |
| 496     | LE07_L2SP_021029_20100618_02_T2 | 2010-06-18 | 85.0   |
| 496     | LE07_L2SP_020030_20100611_02_T1 | 2010-06-11 | 61.0   |
| 496     | LT05_L2SP_021029_20100610_02_T1 | 2010-06-10 | 58.0   |
| 496     | LT05_L2SP_020030_20100603_02_T2 | 2010-06-03 | 100.0  |
| 496     | LE07_L2SP_021029_20100602_02_T2 | 2010-06-02 | 100.0  |
| 496     | LE07_L2SP_020030_20100526_02_T1 | 2010-05-26 | 25.0   |
| 496     | LT05_L2SP_021029_20100525_02_T1 | 2010-05-25 | 5.0    |
| 496     | LT05_L2SP_020030_20100518_02_T1 | 2010-05-18 | 84.0   |
| 496     | LE07_L2SP_021029_20100517_02_T1 | 2010-05-17 | 77.0   |
| 523     | LT05_L2SP_020030_20100721_02_T1 | 2010-07-21 | 24.0   |
| 523     | LE07_L2SP_021030_20100720_02_T1 | 2010-07-20 | 90.0   |
| 523     | LE07_L2SP_021029_20100720_02_T1 | 2010-07-20 | 26.0   |
| 523     | LE07_L2SP_020030_20100713_02_T1 | 2010-07-13 | 99.0   |
| 523     | LT05_L2SP_021030_20100712_02_T1 | 2010-07-12 | 62.0   |
| 523     | LT05_L2SP_021029_20100712_02_T1 | 2010-07-12 | 61.0   |
| 523     | LT05_L2SP_020030_20100705_02_T1 | 2010-07-05 | 21.0   |
| 523     | LE07_L2SP_021030_20100704_02_T1 | 2010-07-04 | 0.0    |
| 523     | LE07_L2SP_021029_20100704_02_T1 | 2010-07-04 | 9.0    |
| 523     | LE07_L2SP_020030_20100627_02_T1 | 2010-06-27 | 76.0   |
| 523     | LT05_L2SP_021030_20100626_02_T1 | 2010-06-26 | 39.0   |
| 523     | LT05_L2SP_021029_20100626_02_T1 | 2010-06-26 | 75.0   |
| 523     | LT05_L2SP_020030_20100619_02_T1 | 2010-06-19 | 52.0   |
| 523     | LE07_L2SP_021030_20100618_02_T2 | 2010-06-18 | 14.0   |
| 523     | LE07_L2SP_021029_20100618_02_T2 | 2010-06-18 | 85.0   |
| 523     | LE07_L2SP_020030_20100611_02_T1 | 2010-06-11 | 61.0   |
| 523     | LT05_L2SP_021030_20100610_02_T1 | 2010-06-10 | 8.0    |
| 523     | LT05_L2SP_021029_20100610_02_T1 | 2010-06-10 | 58.0   |
| 523     | LT05_L2SP_020030_20100603_02_T2 | 2010-06-03 | 100.0  |
| 523     | LE07_L2SP_021030_20100602_02_T2 | 2010-06-02 | 100.0  |
| 523     | LE07_L2SP_021029_20100602_02_T2 | 2010-06-02 | 100.0  |
| 523     | LE07_L2SP_020030_20100526_02_T1 | 2010-05-26 | 25.0   |
| 523     | LT05_L2SP_021030_20100525_02_T1 | 2010-05-25 | 15.0   |
| 523     | LT05_L2SP_021029_20100525_02_T1 | 2010-05-25 | 5.0    |
| 523     | LT05_L2SP_020030_20100518_02_T1 | 2010-05-18 | 84.0   |
| 523     | LE07_L2SP_021030_20100517_02_T1 | 2010-05-17 | 100.0  |
| 523     | LE07_L2SP_021029_20100517_02_T1 | 2010-05-17 | 77.0   |

### Filenames

The imagery is labelled as:
siteID_date_imageItemID.tif

The composite imagery is labelled as:
siteID_startDate-endDate_composite_maskType.tif
