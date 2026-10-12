"""
QA checks on the class-summary CSVs written by class_summary_by_buffer.py.

These read data/output/*_class_summary_by_buffer.csv, so rerun the pipeline
before running them. Run only these with:  pytest -m output
Skip them with:                            pytest -m "not output"
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.output

OUTPUT_DIR = Path("data/output")
DATASETS = ["glfwra", "cwmp"]
BUFFERS = [200, 500, 1000, 2000]
PIXEL_AREA = 30 * 30  # NLCD and NALCMS are both 30 m

STAT_RE = re.compile(r"_(count|area|percent)$")


@pytest.fixture(scope="module", params=DATASETS)
def output(request):
    path = OUTPUT_DIR / f"{request.param}_class_summary_by_buffer.csv"
    if not path.exists():
        pytest.skip(f"{path} not found")
    return pd.read_csv(path, low_memory=False)


def _stems(df, prefix=""):
    """Column names without the _count/_area/_percent suffix (class columns only)."""
    return sorted(
        {
            STAT_RE.sub("", c)
            for c in df.columns
            if c.startswith(prefix) and STAT_RE.search(c) and not c.endswith("_total_area")
        }
    )


def _landcover_blocks(df):
    """(source, buffer, year) for every land cover block present in the output."""
    found = df.columns.str.extract(r"^(nlcd|nalcms)_buff(\d+)_yr(\d+)_").dropna()
    return sorted({(s, int(b), int(y)) for s, b, y in found.itertuples(index=False)})


def _block(df, prefix, stat):
    """All <prefix>*_<stat> columns, e.g. every nwi_buff500_code_*_area."""
    return df[[c for c in df.columns if c.startswith(prefix) and c.endswith(f"_{stat}")]]


# -----------------------------------------------------------------------------
# structure
# -----------------------------------------------------------------------------
def test_count_area_percent_blank_together(output):
    bad = [
        s
        for s in _stems(output)
        if not (
            output[f"{s}_count"].isna().equals(output[f"{s}_area"].isna())
            and output[f"{s}_count"].isna().equals(output[f"{s}_percent"].isna())
        )
    ]
    assert not bad, f"count/area/percent blanks disagree for: {bad[:10]}"


@pytest.mark.parametrize("source", ["nlcd", "nalcms"])
def test_raster_area_is_count_times_pixel_area(output, source):
    bad = [
        s
        for s in _stems(output, source)
        if not np.allclose(output[f"{s}_area"], output[f"{s}_count"] * PIXEL_AREA, equal_nan=True)
    ]
    assert not bad, f"area != count x {PIXEL_AREA} for: {bad[:10]}"


# -----------------------------------------------------------------------------
# land cover: 0 vs NaN (issue #4) and complete class lists (issue #2)
# -----------------------------------------------------------------------------
def test_landcover_blocks_are_all_or_nothing(output):
    """Within a source/buffer/year block a row is either all NaN (no data) or has no NaN."""
    bad = []
    for source, buffer, year in _landcover_blocks(output):
        block = output[[c for c in output.columns if c.startswith(f"{source}_buff{buffer}_yr{year}_")]]
        n_nan = block.isna().sum(axis=1)
        partial = (n_nan > 0) & (n_nan < block.shape[1])
        if partial.any():
            bad.append(f"{source} {buffer} m {year}: {partial.sum()} rows")
    assert not bad, f"blocks with some but not all values missing: {bad[:10]}"


def test_landcover_percents_sum_to_one(output):
    """With Open Water included, every class is accounted for."""
    bad = []
    for source, buffer, year in _landcover_blocks(output):
        total = _block(output, f"{source}_buff{buffer}_yr{year}_", "percent").sum(axis=1, min_count=1)
        off = total.dropna()[lambda s: (s - 1).abs() > 1e-6]
        if not off.empty:
            bad.append(f"{source} {buffer} m {year}: {len(off)} rows, e.g. {off.iloc[0]:.3f}")
    assert not bad, f"land cover percents don't sum to 1: {bad[:10]}"


def test_datasets_have_the_same_landcover_columns():
    """Every LUT class is always written, so both outputs share one schema."""
    cols = {}
    for name in DATASETS:
        path = OUTPUT_DIR / f"{name}_class_summary_by_buffer.csv"
        if not path.exists():
            pytest.skip(f"{path} not found")
        header = pd.read_csv(path, nrows=0).columns
        cols[name] = {c for c in header if c.startswith(("nlcd_", "nalcms_"))}
    a, b = (cols[n] for n in DATASETS)
    assert a == b, f"only in {DATASETS[0]}: {sorted(a - b)[:5]}; only in {DATASETS[1]}: {sorted(b - a)[:5]}"


# -----------------------------------------------------------------------------
# denominators
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("buffer", BUFFERS)
def test_nalcms_denominator_is_buffer_area(output, buffer):
    """
    area / percent recovers the total the percents were computed against.
    It should be the buffer area (pi r^2), within pixel-discretization error
    (a 200 m buffer is only ~140 pixels).

    NLCD is left out until issue #4: buffers that reach into Canada are only
    partly covered by NLCD, so their denominator is smaller than the buffer.
    """
    lo, hi = (0.95, 1.05) if buffer == 200 else (0.99, 1.01)
    years = sorted({int(m) for m in output.columns.str.extract(rf"^nalcms_buff{buffer}_yr(\d+)_")[0].dropna()})
    for year in years:
        prefix = f"nalcms_buff{buffer}_yr{year}_"
        area = _block(output, prefix, "area").sum(axis=1, min_count=1)
        pct = _block(output, prefix, "percent").sum(axis=1, min_count=1)
        ratio = (area / pct / (np.pi * buffer**2)).dropna()
        out_of_range = ratio[(ratio < lo) | (ratio > hi)]
        assert out_of_range.empty, (
            f"{year}: {len(out_of_range)} rows outside [{lo}, {hi}], "
            f"e.g. rows {out_of_range.index[:5].tolist()}"
        )


# -----------------------------------------------------------------------------
# NWI (issue #1)
# -----------------------------------------------------------------------------
@pytest.mark.parametrize("buffer", BUFFERS)
def test_nwi_area_not_larger_than_buffer(output, buffer):
    """Wetland area can't exceed the buffer; if it does, polygons overlap."""
    area = _block(output, f"nwi_buff{buffer}_code_", "area").sum(axis=1)
    ratio = area / (np.pi * buffer**2)
    over = ratio[ratio > 1.001]
    assert over.empty, (
        f"{len(over)} rows with NWI area > buffer area (max {ratio.max():.2f}x), "
        f"e.g. rows {over.index[:5].tolist()}"
    )


@pytest.mark.parametrize("buffer", BUFFERS)
def test_nwi_type_and_code_areas_agree(output, buffer):
    """WETLAND_TYPE and ATTRIBUTE are two labelings of the same polygons."""
    by_type = _block(output, f"nwi_buff{buffer}_type_", "area").sum(axis=1)
    by_code = _block(output, f"nwi_buff{buffer}_code_", "area").sum(axis=1)
    assert np.allclose(by_type, by_code, rtol=1e-9, atol=1e-3)


# -----------------------------------------------------------------------------
# NWI: 0 vs NaN (issue #4)
# -----------------------------------------------------------------------------
def _nwi_class_cols(df, buffer):
    return [c for c in df.columns if c.startswith((f"nwi_buff{buffer}_code_", f"nwi_buff{buffer}_type_"))]


@pytest.mark.parametrize("buffer", BUFFERS)
def test_nwi_total_area_column_exists(output, buffer):
    assert f"nwi_buff{buffer}_total_area" in output.columns


@pytest.mark.parametrize("buffer", BUFFERS)
def test_nwi_classes_are_zero_not_nan_where_covered(output, buffer):
    covered = output[f"nwi_buff{buffer}_total_area"].notna()
    n_nan = output.loc[covered, _nwi_class_cols(output, buffer)].isna().any(axis=1).sum()
    assert n_nan == 0, f"{n_nan} covered rows still have blank NWI class cells"


@pytest.mark.parametrize("buffer", BUFFERS)
def test_nwi_classes_are_nan_where_not_covered(output, buffer):
    not_covered = output[f"nwi_buff{buffer}_total_area"].isna()
    n_vals = output.loc[not_covered, _nwi_class_cols(output, buffer)].notna().any(axis=1).sum()
    assert n_vals == 0, f"{n_vals} uncovered rows have NWI class values"


@pytest.mark.parametrize("buffer", BUFFERS)
def test_nwi_total_area_equals_sum_of_codes(output, buffer):
    total = output[f"nwi_buff{buffer}_total_area"]
    codes = _block(output, f"nwi_buff{buffer}_code_", "area").sum(axis=1)
    covered = total.notna()
    assert np.allclose(total[covered], codes[covered], rtol=1e-9, atol=1e-3)


def test_nwi_and_nlcd_agree_on_coverage(output):
    """
    Cross-check two independent coverage sources: NLCD and NWI are both US-only,
    so rows with no NLCD data (Canadian sites) should have no NWI data either.
    A few border buffers can legitimately differ, hence the tolerance.
    """
    nlcd_cols = [c for c in output.columns if c.startswith("nlcd_buff2000_")]
    no_nlcd = output[nlcd_cols].isna().all(axis=1)
    if not no_nlcd.any():
        pytest.skip("no rows without NLCD data")
    has_nwi = output.loc[no_nlcd, "nwi_buff2000_total_area"].notna()
    assert has_nwi.mean() <= 0.05, (
        f"{has_nwi.sum()} of {no_nlcd.sum()} rows without NLCD data have NWI values"
    )
