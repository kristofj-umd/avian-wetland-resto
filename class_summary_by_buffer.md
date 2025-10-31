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





<div>
<style scoped>
    .dataframe tbody tr th:only-of-type {
        vertical-align: middle;
    }

    .dataframe tbody tr th {
        vertical-align: top;
    }

    .dataframe thead th {
        text-align: right;
    }
</style>
<table border="1" class="dataframe">
  <thead>
    <tr style="text-align: right;">
      <th></th>
      <th>site_id</th>
      <th>crew_name</th>
      <th>year</th>
      <th>date</th>
      <th>sample</th>
      <th>point_id</th>
      <th>bearing</th>
      <th>waypoint</th>
      <th>longitude</th>
      <th>latitude</th>
      <th>coord_qual</th>
      <th>comments</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>0</th>
      <td>1</td>
      <td>SUNY-B</td>
      <td>2015</td>
      <td>5/28/2015</td>
      <td>1</td>
      <td>1</td>
      <td>140</td>
      <td>AB0001.1.BE</td>
      <td>-78.840043</td>
      <td>43.312097</td>
      <td>Excellent</td>
      <td>NaN</td>
    </tr>
    <tr>
      <th>1</th>
      <td>1</td>
      <td>SUNY-B</td>
      <td>2020</td>
      <td>6/1/2020</td>
      <td>1</td>
      <td>1</td>
      <td>238</td>
      <td>AB0001.1.AM</td>
      <td>-78.840627</td>
      <td>43.312285</td>
      <td>Confirmed</td>
      <td>NaN</td>
    </tr>
    <tr>
      <th>2</th>
      <td>4</td>
      <td>SUNY-B</td>
      <td>2015</td>
      <td>5/28/2015</td>
      <td>1</td>
      <td>1</td>
      <td>350</td>
      <td>AB0004.1.BE</td>
      <td>-78.744200</td>
      <td>43.329043</td>
      <td>Excellent</td>
      <td>NaN</td>
    </tr>
    <tr>
      <th>3</th>
      <td>5</td>
      <td>SUNY-B</td>
      <td>2013</td>
      <td>6/12/2013</td>
      <td>1</td>
      <td>1</td>
      <td>183</td>
      <td>B0005.PM</td>
      <td>-78.715802</td>
      <td>43.334753</td>
      <td>Excellent</td>
      <td>NaN</td>
    </tr>
    <tr>
      <th>4</th>
      <td>5</td>
      <td>SUNY-B</td>
      <td>2018</td>
      <td>5/24/2018</td>
      <td>1</td>
      <td>1</td>
      <td>180</td>
      <td>AB0005.1.PM</td>
      <td>-78.716118</td>
      <td>43.335103</td>
      <td>Excellent</td>
      <td>NaN</td>
    </tr>
  </tbody>
</table>
</div>




- GLFWRA
  - field mapping
    - lat: Lat
    - lon: Lon


<div>
<style scoped>
    .dataframe tbody tr th:only-of-type {
        vertical-align: middle;
    }

    .dataframe tbody tr th {
        vertical-align: top;
    }

    .dataframe thead th {
        text-align: right;
    }
</style>
<table border="1" class="dataframe">
  <thead>
    <tr style="text-align: right;">
      <th></th>
      <th>Source</th>
      <th>Site</th>
      <th>PID</th>
      <th>Lat</th>
      <th>Lon</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>0</th>
      <td>21_NRRI, CWM</td>
      <td>21st Ave W</td>
      <td>7049.1.2</td>
      <td>46.757203</td>
      <td>-92.125481</td>
    </tr>
    <tr>
      <th>1</th>
      <td>21_NRRI, CWM</td>
      <td>21st Ave W</td>
      <td>7049.2.2</td>
      <td>46.759090</td>
      <td>-92.122097</td>
    </tr>
    <tr>
      <th>2</th>
      <td>21_NRRI, CWM</td>
      <td>21st Ave W</td>
      <td>7049.1</td>
      <td>46.763798</td>
      <td>-92.123170</td>
    </tr>
    <tr>
      <th>3</th>
      <td>21_NRRI, CWM</td>
      <td>21st Ave W</td>
      <td>7049.2</td>
      <td>46.760550</td>
      <td>-92.123525</td>
    </tr>
    <tr>
      <th>4</th>
      <td>CWM</td>
      <td>40th Ave W</td>
      <td>7048.1</td>
      <td>46.739972</td>
      <td>-92.153694</td>
    </tr>
  </tbody>
</table>
</div>


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
