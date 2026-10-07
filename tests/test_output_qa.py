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
    """Column names without the _count/_area/_percent suffix."""
    return sorted(
        {STAT_RE.sub("", c) for c in df.columns if c.startswith(prefix) and STAT_RE.search(c)}
    )


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
