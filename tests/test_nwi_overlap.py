"""
Tests for removing NWI polygons that are counted more than once when
neighbouring state geopackages both contain them (issue #1).

All data here is synthetic (see conftest.py), so these tests run without the
NWI geopackages.
"""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point, box

from conftest import CRS, LAT, LON, wetlands_gdf
from libs.nwi import _erase_cross_file_overlap, process_one_nwi, wetlands_within_buffer

BUFFER = 500


# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------
def _tagged(geoms, files, codes=None):
    gdf = wetlands_gdf(geoms, codes)
    gdf["_file"] = files
    return gdf


def _buffer(cx, cy, r=BUFFER):
    return gpd.GeoSeries([Point(cx, cy).buffer(r)], crs=CRS)


def _full_coverage(cx, cy):
    """NWI coverage that contains the whole test area."""
    return gpd.GeoDataFrame(geometry=[box(cx - 10_000, cy - 10_000, cx + 10_000, cy + 10_000)], crs=CRS)


# -----------------------------------------------------------------------------
# _erase_cross_file_overlap
# -----------------------------------------------------------------------------
def test_identical_copy_in_second_file_is_removed():
    sq = box(0, 0, 100, 100)
    out = _erase_cross_file_overlap(_tagged([sq, sq], ["MN_Wetlands", "WI_Wetlands"]))
    assert len(out) == 1
    assert out.area.sum() == pytest.approx(sq.area)


def test_partial_overlap_keeps_only_uncovered_part():
    # same river, but each state drew it to a different extent
    mn = box(0, 0, 300, 100)
    wi = box(200, 0, 500, 100)
    out = _erase_cross_file_overlap(_tagged([mn, wi], ["MN_Wetlands", "WI_Wetlands"]))
    assert out.area.sum() == pytest.approx(mn.union(wi).area)
    assert out.area.sum() == pytest.approx(out.union_all().area)


def test_non_overlapping_polygons_untouched():
    a, b = box(0, 0, 10, 10), box(20, 20, 30, 30)
    out = _erase_cross_file_overlap(_tagged([a, b], ["MN_Wetlands", "WI_Wetlands"]))
    assert len(out) == 2
    assert out.area.sum() == pytest.approx(a.area + b.area)


def test_single_file_is_returned_unchanged():
    gdf = _tagged([box(0, 0, 10, 10), box(5, 5, 15, 15)], ["MN_Wetlands"] * 2)
    out = _erase_cross_file_overlap(gdf)
    assert len(out) == 2
    assert out.area.sum() == pytest.approx(gdf.area.sum())


def test_slivers_below_min_area_are_dropped():
    # WI copy is 5 mm wider -> a 0.005 m x 100 m = 0.5 m2 sliver is left after erasing
    mn = box(0, 0, 100, 100)
    wi = box(0, 0, 100.005, 100)
    out = _erase_cross_file_overlap(_tagged([mn, wi], ["MN_Wetlands", "WI_Wetlands"]))
    assert len(out) == 1
    assert out["_file"].tolist() == ["MN_Wetlands"]


def test_first_file_label_wins_when_codes_disagree():
    sq = box(0, 0, 100, 100)
    gdf = _tagged([sq, sq], ["MN_Wetlands", "WI_Wetlands"], codes=["R2UBH", "PEM1C"])
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

    mn = wetlands_gdf([river_mn, marsh_mn], codes=["R2UBH", "PEM1C"])
    wi = wetlands_gdf([river_wi, swamp_wi], codes=["R2UBH", "PFO1A"])
    nwi = make_nwi({"MN": (mn, CRS), "WI": (wi, CRS)})

    circle = Point(cx, cy).buffer(BUFFER)
    expected = {
        "R2UBH": river_mn.intersection(circle).area,  # one copy only
        "PEM1C": marsh_mn.area,
        "PFO1A": swamp_wi.area,
    }
    return nwi, expected


def test_border_river_is_not_double_counted(center, border_river):
    nwi, expected = border_river
    out = wetlands_within_buffer(_buffer(*center), CRS, nwi.index)

    total = out.area.sum()
    assert total <= np.pi * BUFFER**2
    assert total == pytest.approx(out.union_all().area, abs=1.0)
    assert total == pytest.approx(sum(expected.values()), abs=1.0)


def test_process_one_nwi_reports_single_copy_area(center, border_river):
    nwi, expected = border_river
    point = gpd.points_from_xy([LON], [LAT], crs="EPSG:4326")
    result = process_one_nwi(point, BUFFER, "nwi", CRS, nwi.index, _full_coverage(*center))

    for code, area in expected.items():
        assert result[f"nwi_buff{BUFFER}_code_{code.lower()}_area"] == pytest.approx(area, abs=1.0)


def test_files_stored_in_different_crs_are_combined(center, make_nwi):
    # state files don't have to share a native CRS
    cx, cy = center
    marsh_mn = box(cx + 200, cy + 200, cx + 300, cy + 300)
    swamp_wi = box(cx - 300, cy - 300, cx - 200, cy - 200)
    nwi = make_nwi(
        {
            "MN": (wetlands_gdf([marsh_mn], codes=["PEM1C"]), CRS),
            "WI": (wetlands_gdf([swamp_wi], codes=["PFO1A"]), "EPSG:26915"),
        }
    )
    out = wetlands_within_buffer(_buffer(cx, cy), CRS, nwi.index)
    assert out.area.sum() == pytest.approx(marsh_mn.area + swamp_wi.area, abs=1.0)


def test_wetland_in_bbox_corner_but_outside_buffer_returns_none(center, make_nwi):
    # inside the buffer's bounding box, but outside the circle -> clip is empty
    cx, cy = center
    corner = box(cx + 420, cy + 420, cx + 490, cy + 490)
    nwi = make_nwi({"MN": (wetlands_gdf([corner]), CRS)})

    assert wetlands_within_buffer(_buffer(cx, cy), CRS, nwi.index) is None
