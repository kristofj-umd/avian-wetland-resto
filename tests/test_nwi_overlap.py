"""
Tests for removing NWI polygons that are counted more than once when
neighbouring state geopackages both contain them (issue #1).

All data here is synthetic, so these tests run without the NWI geopackages.
"""

import json

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point, box

from libs.nwi import _erase_cross_file_overlap, process_one_nwi, wetlands_within_buffer

CRS = "EPSG:5070"
BUFFER = 500

# a point in the St. Louis River estuary (Duluth-Superior harbor)
LON, LAT = -92.183, 46.711


# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------
def _gdf(geoms, files, codes=None):
    n = len(geoms)
    return gpd.GeoDataFrame(
        {
            "WETLAND_TYPE": ["Riverine"] * n,
            "ATTRIBUTE": codes or ["R2UBH"] * n,
            "_file": files,
        },
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
    Write synthetic state geopackages the same way the real ones are laid out
    (<STATE>_Wetlands layer) and return the path to an nwi_filelist.json.
    Each state can be stored in its own CRS, like the real files.
    """

    def _make(states: dict[str, tuple[gpd.GeoDataFrame, str]]) -> str:
        paths = []
        for state, (gdf, file_crs) in states.items():
            path = tmp_path / f"{state}_Wetlands_Geopackage.gpkg"
            gdf[["WETLAND_TYPE", "ATTRIBUTE", "geometry"]].to_crs(file_crs).to_file(
                path, layer=f"{state}_Wetlands", driver="GPKG"
            )
            paths.append(str(path))
        json_path = tmp_path / "nwi_filelist.json"
        json_path.write_text(json.dumps(paths))
        return str(json_path)

    return _make


def _buffer(cx, cy, r=BUFFER):
    return gpd.GeoSeries([Point(cx, cy).buffer(r)], crs=CRS)


# -----------------------------------------------------------------------------
# _erase_cross_file_overlap
# -----------------------------------------------------------------------------
def test_identical_copy_in_second_file_is_removed():
    sq = box(0, 0, 100, 100)
    out = _erase_cross_file_overlap(_gdf([sq, sq], ["MN_Wetlands", "WI_Wetlands"]))
    assert len(out) == 1
    assert out.area.sum() == pytest.approx(sq.area)


def test_partial_overlap_keeps_only_uncovered_part():
    # same river, but each state drew it to a different extent
    mn = box(0, 0, 300, 100)
    wi = box(200, 0, 500, 100)
    out = _erase_cross_file_overlap(_gdf([mn, wi], ["MN_Wetlands", "WI_Wetlands"]))
    assert out.area.sum() == pytest.approx(mn.union(wi).area)
    assert out.area.sum() == pytest.approx(out.union_all().area)


def test_non_overlapping_polygons_untouched():
    a, b = box(0, 0, 10, 10), box(20, 20, 30, 30)
    out = _erase_cross_file_overlap(_gdf([a, b], ["MN_Wetlands", "WI_Wetlands"]))
    assert len(out) == 2
    assert out.area.sum() == pytest.approx(a.area + b.area)


def test_single_file_is_returned_unchanged():
    gdf = _gdf([box(0, 0, 10, 10), box(5, 5, 15, 15)], ["MN_Wetlands"] * 2)
    out = _erase_cross_file_overlap(gdf)
    assert len(out) == 2
    assert out.area.sum() == pytest.approx(gdf.area.sum())


def test_slivers_below_min_area_are_dropped():
    # WI copy is 5 mm wider -> a 0.005 m x 100 m = 0.5 m2 sliver is left after erasing
    mn = box(0, 0, 100, 100)
    wi = box(0, 0, 100.005, 100)
    out = _erase_cross_file_overlap(_gdf([mn, wi], ["MN_Wetlands", "WI_Wetlands"]))
    assert len(out) == 1
    assert out["_file"].tolist() == ["MN_Wetlands"]


def test_first_file_label_wins_when_codes_disagree():
    sq = box(0, 0, 100, 100)
    gdf = _gdf([sq, sq], ["MN_Wetlands", "WI_Wetlands"], codes=["R2UBH", "PEM1C"])
    out = _erase_cross_file_overlap(gdf)
    assert out["ATTRIBUTE"].tolist() == ["R2UBH"]


# -----------------------------------------------------------------------------
# wetlands_within_buffer / process_one_nwi (reads synthetic geopackages)
# -----------------------------------------------------------------------------
@pytest.fixture
def border_river(center, make_nwi):
    """
    MN and WI both contain the river polygon, drawn to different extents
    (identical inside the buffer), plus one wetland unique to each state.
    """
    cx, cy = center
    river_mn = box(cx - 3000, cy - 100, cx + 1000, cy + 100)
    river_wi = box(cx - 1000, cy - 100, cx + 3000, cy + 100)
    marsh_mn = box(cx + 200, cy + 200, cx + 300, cy + 300)
    swamp_wi = box(cx - 300, cy - 300, cx - 200, cy - 200)

    mn = _gdf([river_mn, marsh_mn], ["MN_Wetlands"] * 2, codes=["R2UBH", "PEM1C"])
    wi = _gdf([river_wi, swamp_wi], ["WI_Wetlands"] * 2, codes=["R2UBH", "PFO1A"])
    json_path = make_nwi({"MN": (mn, CRS), "WI": (wi, CRS)})

    circle = Point(cx, cy).buffer(BUFFER)
    expected = {
        "R2UBH": river_mn.intersection(circle).area,  # one copy only
        "PEM1C": marsh_mn.area,
        "PFO1A": swamp_wi.area,
    }
    return json_path, expected


def test_border_river_is_not_double_counted(center, border_river):
    json_path, expected = border_river
    out = wetlands_within_buffer(_buffer(*center), CRS, json_path)

    total = out.area.sum()
    assert total <= np.pi * BUFFER**2
    assert total == pytest.approx(out.union_all().area, abs=1.0)
    assert total == pytest.approx(sum(expected.values()), abs=1.0)


def test_process_one_nwi_reports_single_copy_area(border_river):
    json_path, expected = border_river
    point = gpd.points_from_xy([LON], [LAT], crs="EPSG:4326")
    result = process_one_nwi(point, BUFFER, "nwi", CRS, json_path)

    for code, area in expected.items():
        assert result[f"nwi_buff{BUFFER}_code_{code.lower()}_area"] == pytest.approx(area, abs=1.0)


def test_files_stored_in_different_crs_are_combined(center, make_nwi):
    # state files don't have to share a native CRS
    cx, cy = center
    marsh_mn = box(cx + 200, cy + 200, cx + 300, cy + 300)
    swamp_wi = box(cx - 300, cy - 300, cx - 200, cy - 200)
    json_path = make_nwi(
        {
            "MN": (_gdf([marsh_mn], ["MN_Wetlands"], codes=["PEM1C"]), CRS),
            "WI": (_gdf([swamp_wi], ["WI_Wetlands"], codes=["PFO1A"]), "EPSG:26915"),
        }
    )
    out = wetlands_within_buffer(_buffer(cx, cy), CRS, json_path)
    assert out.area.sum() == pytest.approx(marsh_mn.area + swamp_wi.area, abs=1.0)


def test_wetland_in_bbox_corner_but_outside_buffer_returns_none(center, make_nwi):
    # inside the buffer's bounding box, but outside the circle -> clip is empty
    cx, cy = center
    corner = box(cx + 420, cy + 420, cx + 490, cy + 490)
    json_path = make_nwi({"MN": (_gdf([corner], ["MN_Wetlands"]), CRS)})

    assert wetlands_within_buffer(_buffer(cx, cy), CRS, json_path) is None
