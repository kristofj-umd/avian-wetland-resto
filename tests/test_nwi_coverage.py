"""
Tests for NWI coverage (issue #4): a buffer outside the NWI-mapped area gets
NaN (process_one_nwi returns None), a covered buffer with no wetlands gets 0.

Coverage comes from the dissolved <STATE>_Wetlands_Project_Metadata layers,
built once and cached by _load_or_build_nwi_coverage.
"""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point, box

import class_summary_by_buffer as pipeline
from conftest import CRS, LAT, LON, wetlands_gdf
from libs.nwi import _coverage_fraction, process_one_nwi

BUFFER = 500
TOTAL_COL = f"nwi_buff{BUFFER}_total_area"


@pytest.fixture(autouse=True)
def _isolate_coverage_cache(tmp_path, monkeypatch):
    # never let a test write to (or read from) the real data/nwi_coverage.gpkg
    monkeypatch.setattr(pipeline, "NWI_COVERAGE_PATH", str(tmp_path / "default_cov.gpkg"))


def _buffer(cx, cy, r=BUFFER):
    return gpd.GeoSeries([Point(cx, cy).buffer(r)], crs=CRS)


def _coverage(*geoms):
    return gpd.GeoDataFrame(geometry=list(geoms), crs=CRS)


def _point():
    return gpd.points_from_xy([LON], [LAT], crs="EPSG:4326")


@pytest.fixture
def marsh_nwi(center, make_nwi):
    """One MN wetland inside the buffer."""
    cx, cy = center
    marsh = box(cx + 100, cy + 100, cx + 200, cy + 200)
    return make_nwi({"MN": (wetlands_gdf([marsh], codes=["PEM1C"]), CRS)}), marsh


# -----------------------------------------------------------------------------
# _coverage_fraction
# -----------------------------------------------------------------------------
def test_coverage_fraction_full(center):
    cx, cy = center
    cov = _coverage(box(cx - 5000, cy - 5000, cx + 5000, cy + 5000))
    assert _coverage_fraction(_buffer(cx, cy), cov) == pytest.approx(1.0)


def test_coverage_fraction_none(center):
    cx, cy = center
    cov = _coverage(box(cx + 5000, cy + 5000, cx + 6000, cy + 6000))
    assert _coverage_fraction(_buffer(cx, cy), cov) == pytest.approx(0.0)


def test_coverage_fraction_half(center):
    # coverage ends at the buffer's center line (like a border through the buffer)
    cx, cy = center
    cov = _coverage(box(cx - 5000, cy - 5000, cx, cy + 5000))
    assert _coverage_fraction(_buffer(cx, cy), cov) == pytest.approx(0.5, abs=1e-3)


# -----------------------------------------------------------------------------
# process_one_nwi: NaN vs 0
# -----------------------------------------------------------------------------
def test_not_covered_returns_none(center, marsh_nwi):
    # wetland polygons exist, but the buffer is outside the mapped area -> NaN
    cx, cy = center
    nwi, _ = marsh_nwi
    cov = _coverage(box(cx + 5000, cy + 5000, cx + 6000, cy + 6000))
    assert process_one_nwi(_point(), BUFFER, "nwi", CRS, nwi.index, cov) is None


def test_partly_covered_below_cutoff_returns_none(center, marsh_nwi):
    # half the buffer is mapped -> below any sensible cutoff -> NaN
    cx, cy = center
    nwi, _ = marsh_nwi
    cov = _coverage(box(cx - 5000, cy - 5000, cx, cy + 5000))
    assert process_one_nwi(_point(), BUFFER, "nwi", CRS, nwi.index, cov) is None


def test_mostly_covered_above_cutoff_returns_values(center, marsh_nwi):
    # 98% of the buffer is mapped -> above the cutoff -> values
    cx, cy = center
    nwi, marsh = marsh_nwi
    cov = _coverage(box(cx - 5000, cy - 5000, cx + 480, cy + 5000))
    assert _coverage_fraction(_buffer(cx, cy), cov) > 0.95
    result = process_one_nwi(_point(), BUFFER, "nwi", CRS, nwi.index, cov)
    assert result[TOTAL_COL] == pytest.approx(marsh.area, abs=1.0)


def test_covered_without_wetlands_returns_zero_total(center, make_nwi):
    # mapped area, but the only wetland is far outside the buffer -> 0
    cx, cy = center
    far = box(cx + 8000, cy + 8000, cx + 8100, cy + 8100)
    nwi = make_nwi({"MN": (wetlands_gdf([far]), CRS)})
    cov = _coverage(box(cx - 10_000, cy - 10_000, cx + 10_000, cy + 10_000))
    assert process_one_nwi(_point(), BUFFER, "nwi", CRS, nwi.index, cov) == {TOTAL_COL: 0.0}


def test_total_area_equals_sum_of_class_areas(center, make_nwi):
    cx, cy = center
    a = box(cx + 100, cy + 100, cx + 200, cy + 200)
    b = box(cx - 200, cy - 200, cx - 100, cy - 100)
    nwi = make_nwi({"MN": (wetlands_gdf([a, b], codes=["PEM1C", "PFO1A"]), CRS)})
    cov = _coverage(box(cx - 10_000, cy - 10_000, cx + 10_000, cy + 10_000))
    result = process_one_nwi(_point(), BUFFER, "nwi", CRS, nwi.index, cov)

    code_area = sum(v for k, v in result.items() if "_code_" in k and k.endswith("_area"))
    assert result[TOTAL_COL] == pytest.approx(a.area + b.area, abs=1.0)
    assert result[TOTAL_COL] == pytest.approx(code_area, abs=1.0)


# -----------------------------------------------------------------------------
# building / loading the coverage cache
# -----------------------------------------------------------------------------
@pytest.fixture
def two_state_meta(center, make_nwi):
    """MN and WI metadata footprints that overlap along the border."""
    cx, cy = center
    mn_meta = box(cx - 5000, cy - 5000, cx + 1000, cy + 5000)
    wi_meta = box(cx - 1000, cy - 5000, cx + 5000, cy + 5000)
    marsh = wetlands_gdf([box(cx, cy, cx + 10, cy + 10)])
    nwi = make_nwi({"MN": (marsh, CRS), "WI": (marsh, CRS)}, meta={"MN": mn_meta, "WI": wi_meta})
    return nwi, mn_meta.union(wi_meta)


def test_build_coverage_dissolves_states(tmp_path, two_state_meta):
    nwi, expected = two_state_meta
    cov = pipeline._load_or_build_nwi_coverage(nwi.paths, str(tmp_path / "cov.gpkg"))
    assert cov.crs == CRS
    assert cov.area.sum() == pytest.approx(expected.area)          # overlap counted once
    assert cov.area.sum() == pytest.approx(cov.union_all().area)   # parts don't overlap


def test_build_coverage_writes_cache_to_given_path(tmp_path, two_state_meta):
    nwi, _ = two_state_meta
    cache = tmp_path / "cov.gpkg"
    pipeline._load_or_build_nwi_coverage(nwi.paths, str(cache))
    assert cache.exists()


def test_existing_cache_is_loaded_not_rebuilt(tmp_path, center, two_state_meta):
    # a cache whose footprint differs from the metadata layers: it must be what comes back
    nwi, _ = two_state_meta
    cx, cy = center
    cached = box(cx, cy, cx + 50, cy + 50)
    cache = tmp_path / "cov.gpkg"
    _coverage(cached).to_file(cache, layer="coverage")

    cov = pipeline._load_or_build_nwi_coverage(nwi.paths, str(cache))
    assert cov.area.sum() == pytest.approx(cached.area)


def test_wetland_setup_returns_index_and_coverage(tmp_path, monkeypatch, two_state_meta):
    nwi, expected = two_state_meta
    monkeypatch.setattr(pipeline, "NWI_PATH_JSON", nwi.json)
    monkeypatch.setattr(pipeline, "NWI_COVERAGE_PATH", str(tmp_path / "cov.gpkg"))

    nwi_index, coverage = pipeline.wetland_setup()

    assert [p for p, *_ in nwi_index] == nwi.paths
    assert isinstance(coverage, gpd.GeoDataFrame)
    assert coverage.area.sum() == pytest.approx(expected.area)
    assert np.isclose(coverage.area.sum(), coverage.union_all().area)
