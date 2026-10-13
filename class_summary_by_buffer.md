# Part 1: Class Summary by Buffer

**Calculate total area and percent occupied by class for buffers of CWMP and GLFWRA bird count locations.**

_Buffers_: 200m, 500m, 1km, 2km  
_Data_: land cover and wetland type & code  
_Years_: 2010, 2015, 2020, 2023  
_Deliverable_: CSV file for each bird count dataset containing class summaries for each buffer for each location.

## Data

### Land Cover

#### [National Land Cover Database (NLCD)](https://doi.org/10.5066/P94UXNTS)  

_source_: United States Geological Survey (USGS)  
_product_: Annual NLCD Collection 1 Land Cover, Conterminous United States, ver. 1.0  
_years_: 2010, 2015, 2020, 2023  
_files_: `s3://usgs-landcover/annual-nlcd/c1/v0/cu/mosaic/Annual_NLCD_LndCov_<year>_CU_C1V0.tif` (requester-pays bucket)  
_metadata_: [Annual_NLCD_LndCov_2023_CU_C1V0.xml](metadata/Annual_NLCD_LndCov_2023_CU_C1V0.xml)  
_how to cite_:  
U.S. Geological Survey (USGS), 2024, Annual NLCD Collection 1 Science Products (ver. 1.0, October 2024): U.S. Geological Survey data release, <https://doi.org/10.5066/P94UXNTS>.

#### [North American Land Change Monitoring System](https://www.cec.org/north-american-land-change-monitoring-system/)  

_source_: Commission for Environmental Cooperation (CEC)  
_years_: 2010, 2015, 2020

| Year | Edition | File | Metadata |
| :--- | :--- | :--- | :--- |
| 2010 | v3 | `NA_NALCMS_landcover_2010v3_30m.tif` | [NA_landcover_2010v3_30m_metadata.html](metadata/NA_landcover_2010v3_30m_metadata.html) |
| 2015 | v4 | `NA_NALCMS_landcover_2015v4_30m.tif` | [NA_landcover_2015v4_30m_metadata.html](metadata/NA_landcover_2015v4_30m_metadata.html) |
| 2020 | v2 | `NA_NALCMS_landcover_2020v2_30m.tif` | [NA_landcover_2020v2_30m_metadata.html](metadata/NA_landcover_2020v2_30m_metadata.html) |

#### How to cite

**2010**:

Commission for Environmental Cooperation (CEC). 2024. "North American Environmental Atlas - Land Cover 2010 30m". North American Land Change Monitoring System. Canada Centre for Remote Sensing (CCRS), U.S. Geological Survey (USGS), Comisión Nacional para el Conocimiento y Uso de la Biodiversidad (CONABIO), Comisión Nacional Forestal (CONAFOR), Instituto Nacional de Estadística y Geografía (INEGI). Ed. 3.0, Raster digital data [30-m]. Available at <https://www.cec.org/north-american-environmental-atlas/land-cover-2010-landsat-30m/>

**2015**:

Commission for Environmental Cooperation (CEC). 2024. "North American Environmental Atlas - Land Cover 2015 30m". North American Land Change Monitoring System. Canada Centre for Remote Sensing (CCRS), U.S. Geological Survey (USGS), Comisión Nacional para el Conocimiento y Uso de la Biodiversidad (CONABIO), Comisión Nacional Forestal (CONAFOR), Instituto Nacional de Estadística y Geografía (INEGI). Ed. 4.0, Raster digital data [30-m]. Available at <https://www.cec.org/north-american-environmental-atlas/land-cover-30m-2015-landsat-and-rapideye/>

**2020**:

Commission for Environmental Cooperation (CEC). 2024. "North American Environmental Atlas - Land Cover 2020 30m". North American Land Change Monitoring System. Canada Centre for Remote Sensing (CCRS), U.S. Geological Survey (USGS), Comisión Nacional para el Conocimiento y Uso de la Biodiversidad (CONABIO), Comisión Nacional Forestal (CONAFOR), Instituto Nacional de Estadística y Geografía (INEGI). Ed. 2.0, Raster digital data [30-m]. Available at <https://www.cec.org/north-american-environmental-atlas/land-cover-30m-2020/>

### Wetlands

#### [National Wetlands Inventory](https://www.fws.gov/program/national-wetlands-inventory)

_source_: United States Fish and Wildlife Service (USFWS)  
_years_: continually updated; the version used is fixed by the download date of October, 2024.  
_how to cite_:  
U. S. Fish and Wildlife Service. May 1st, 2024. National Wetlands Inventory website. U.S. Department of the Interior, Fish and Wildlife Service, Washington, D.C.

## Bird Count Locations

Bird count locations were provided by Annie & Isabel. From the original methods notes:

- Great Lakes Coastal Wetland Monitoring Program (CWMP) bird point count locations (PCL): [CWMP_PCL_all.xlsx](https://docs.google.com/spreadsheets/d/1-FZrtUYZS9HEFVKIO94fKBhGXi5KQDon)
- GLFWRA bird point count locations (PCL): GLFWRA_PCL_all.csv

[Coastal Wetlands source data](https://docs.google.com/spreadsheets/d/1-FZrtUYZS9HEFVKIO94fKBhGXi5KQDon)

- field mapping
  - lat: latitude
  - lon: longitude

|   site_id | crew_name   |   year | date      |   sample |   point_id |   bearing | waypoint    |   longitude |   latitude | coord_qual   |   comments |
|----------:|:------------|-------:|:----------|---------:|-----------:|----------:|:------------|------------:|-----------:|:-------------|-----------:|
|         1 | SUNY-B      |   2015 | 5/28/2015 |        1 |          1 |       140 | AB0001.1.BE |    -78.84   |    43.3121 | Excellent    |        nan |
|         1 | SUNY-B      |   2020 | 6/1/2020  |        1 |          1 |       238 | AB0001.1.AM |    -78.8406 |    43.3123 | Confirmed    |        nan |
|         4 | SUNY-B      |   2015 | 5/28/2015 |        1 |          1 |       350 | AB0004.1.BE |    -78.7442 |    43.329  | Excellent    |        nan |
|         5 | SUNY-B      |   2013 | 6/12/2013 |        1 |          1 |       183 | B0005.PM    |    -78.7158 |    43.3348 | Excellent    |        nan |
|         5 | SUNY-B      |   2018 | 5/24/2018 |        1 |          1 |       180 | AB0005.1.PM |    -78.7161 |    43.3351 | Excellent    |        nan |

- GLFWRA
  - field mapping
    - lat: Lat
    - lon: Lon

| Source       | Site       | PID      |     Lat |      Lon |
|:-------------|:-----------|:---------|--------:|---------:|
| 21_NRRI, CWM | 21st Ave W | 7049.1.2 | 46.7572 | -92.1255 |
| 21_NRRI, CWM | 21st Ave W | 7049.2.2 | 46.7591 | -92.1221 |
| 21_NRRI, CWM | 21st Ave W | 7049.1   | 46.7638 | -92.1232 |
| 21_NRRI, CWM | 21st Ave W | 7049.2   | 46.7606 | -92.1235 |
| CWM          | 40th Ave W | 7048.1   | 46.74   | -92.1537 |

## Workflow

1. create buffer
2. read in raster for buffer
3. calculate stats for buffer

- for each class:
  - count
  - area
  - percent of total

## Output format

Output is in wide format, meaning the output spreadsheet has the same number of rows as the input spreadsheet. Output results have been added as new columns to the right of existing columns.

The format of the new columns is as:  
`<dataset>_buff<size>_yr<number>_<wetland code/>type>_<class>_<count/area/percent>`

### Some examples:

The percent of developed (open space) landcover according to the NLCD for the year 2010 within the 200m buffer would look like this:  
`nlcd_buff200_yr2010_developed__open_space_percent`

The area classified as urban according to the NALCMS for the year 2020 within the 200m buffer would look like this:  
`nalcms_buff200_yr2020_urban_area`

Wetlands with a class code of R2UBH occupy this percent of total area within the 500m buffer would look like this:  
`nwi_buff500_code_R2UBH_percent`
> *note the lack of year for NWI columns*

The percent of the 500m buffer with Riverine type wetlands would look like this:  
`nwi_buff500_type_riverine_percent`

### Column notes

- *count* is the number of pixels (for landcover) or wetland polygons
- *area* is in meters squared
- *percent* is a decimal (0-1)
