# Part 1: Class Summary by Buffer

**Calculate total area and percent occupied by class for buffers of CWMP and GLFWRA bird count locations.**

_Buffers_: 200m, 500m, 1km, 2km  
_Data_: land cover and wetland type & code  
_Years_: 2010, 2015, 2020, 2023  
_Deliverable_: CSV file for each bird count dataset containing class summaries for each buffer for each location.

## Data

### Land Cover

##### [National Land Cover Database (NLCD)](https://www.usgs.gov/data/annual-national-land-cover-database-nlcd-collection-1-products-ver-11-june-2025)  
*source*: United States Geological Survey (USGS)  
*years*: 2010, 2015, 2020, 2023  
*metadata*: https://www.mrlc.gov/downloads/sciweb1/shared/mrlc/metadata/Annual_NLCD_LndCov_2024_CU_C1V1.xml  
*how to cite*:  
U.S. Geological Survey (USGS), 2024, Annual NLCD Collection 1 Science Products (ver. 1.1, June 2025): U.S. Geological Survey data release, https://doi.org/10.5066/P94UXNTS.


##### [North American Land Change Monitoring System](https://www.cec.org/north-american-land-change-monitoring-system/)  
*source*: Commission for Environmental Cooperation (CEC)  
*years*: 2010, 2015, 2020  
*metadata*: [NA_landcover_2020v2_30m_metadata.html](metadata/NA_landcover_2020v2_30m_metadata.html)  
*how to cite*:  
Commission for Environmental Cooperation (CEC). 2024. "North American Environmental Atlas - Land Cover 2020 30m". North American Land Change Monitoring System. Canada Centre for Remote Sensing (CCRS), U.S. Geological Survey (USGS), Comisión Nacional para el Conocimiento y Uso de la Biodiversidad (CONABIO), Comisión Nacional Forestal (CONAFOR), Instituto Nacional de Estadística y Geografía (INEGI). Ed. 2.0, Raster digital data [30-m]. Available at https://www.cec.org/north-american-environmental-atlas/land-cover-30m-2020/

### Wetlands

##### [National Wetlands Inventory](https://www.fws.gov/program/national-wetlands-inventory)
*source*: United States Fish and Wildlife Service (USFWS)  
*years*: continually updated  
*metadata*: https://documentst.ecosphere.fws.gov/wetlands/data/metadata/FWS_Wetlands.xml  
*how to cite*:  
U. S. Fish and Wildlife Service. May 1st, 2024. National Wetlands Inventory website. U.S. Department of the Interior, Fish and Wildlife Service, Washington, D.C.

### Bird Count Locations

Bird count locations were provided by Annie & Isabel. From the original methods notes:
- Great Lakes Coastal Wetland Monitoring Program (CWMP) bird point count locations (PCL): [CWMP_PCL_all.xlsx](https://docs.google.com/spreadsheets/d/1-FZrtUYZS9HEFVKIO94fKBhGXi5KQDon)
- GLFWRA bird point count locations (PCL): GLFWRA_PCL_all.csv


## Load bird count locations

- [coastal wetlands](https://docs.google.com/spreadsheets/d/1-FZrtUYZS9HEFVKIO94fKBhGXi5KQDon)
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


## Process each location, buffer

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
