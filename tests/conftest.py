"""
Shared fixtures for the NWI tests: synthetic state geopackages laid out like
the real ones (<STATE>_Wetlands and <STATE>_Wetlands_Project_Metadata layers),
so the tests run without the NWI downloads.
"""

import json
from types import SimpleNamespace

import geopandas as gpd
import pyogrio as po
import pytest

CRS = "EPSG:5070"

# a point in the St. Louis River estuary (Duluth-Superior harbor)
LON, LAT = -92.183, 46.711


def wetlands_gdf(geoms, codes=None, wetland_type="Riverine"):
    """GeoDataFrame with the NWI attribute columns the pipeline reads."""
    n = len(geoms)
    return gpd.GeoDataFrame(
        {"WETLAND_TYPE": [wetland_type] * n, "ATTRIBUTE": codes or ["R2UBH"] * n},
        geometry=geoms,
        crs=CRS,
    )


@pytest.fixture
def center():
    """Projected (EPSG:5070) x, y of the test point."""
    pt = gpd.GeoSeries(gpd.points_from_xy([LON], [LAT]), crs="EPSG:4326").to_crs(CRS)
    return pt.x.iloc[0], pt.y.iloc[0]


@pytest.fixture
def make_nwi(tmp_path):
    """
    Write one geopackage per state and return:
      .index  -> [(path, layer, crs, total_bounds)], the same shape _scan_nwi returns
      .paths  -> list of geopackage paths
      .json   -> path to an nwi_filelist.json listing them

    states: {"MN": (wetlands_gdf, file_crs), ...}
    meta:   {"MN": project-metadata geometry (EPSG:5070)}, optional
    """

    def _make(states, meta=None):
        meta = meta or {}
        index, paths = [], []
        for state, (gdf, file_crs) in states.items():
            path = tmp_path / f"{state}_Wetlands_Geopackage.gpkg"
            layer = f"{state}_Wetlands"
            gdf[["WETLAND_TYPE", "ATTRIBUTE", "geometry"]].to_crs(file_crs).to_file(
                path, layer=layer, driver="GPKG"
            )
            if state in meta:
                gpd.GeoDataFrame(
                    {"STATUS": ["Digital"]}, geometry=[meta[state]], crs=CRS
                ).to_file(path, layer=f"{state}_Wetlands_Project_Metadata", driver="GPKG")
            info = po.read_info(path, layer=layer)
            index.append((str(path), layer, info["crs"], tuple(info["total_bounds"])))
            paths.append(str(path))
        json_path = tmp_path / "nwi_filelist.json"
        json_path.write_text(json.dumps(paths))
        return SimpleNamespace(index=index, paths=paths, json=str(json_path))

    return _make
