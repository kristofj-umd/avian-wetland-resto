Here's the list, ordered from clear bugs down to minor suggestions. Each item says what's wrong, where it is, and the change I'd make.

## Tier 1: Bugs that make the numbers wrong

**1. NWI polygons are counted twice in the overlap between state files.** [nwi.py](libs/nwi.py), `wetlands_within_buffer`

- Every state geopackage whose extent overlaps the buffer gets read and combined, so polygons stored in both the MN and WI files are counted twice.
- In 61 of 67 GLFWRA points, NWI `_area` and `_count` are doubled. Some buffers report more wetland than their own area (up to 1.96×). CWMP has 240 rows over 100% of the buffer.
- **Fix:** after combining the files, remove repeated polygons (same geometry and attributes), or clip each state's features to that state's boundary. Then confirm the NWI area is never larger than the buffer.

**2. Open Water is dropped from the output but still counted in the denominator.** [land_cover.py](libs/land_cover.py), `NLCD_CLASS_LUT` and `NALCMS_CLASS_LUT`

- NLCD class 11 and NALCMS class 18 are commented out of the lookup tables.
- As a result, land cover percents sum to about 65% (median), and the missing share is water I didn't cover. I confirmed this for NLCD: CSV sum + water = 1.0000.
- **Fix:** uncomment both classes. Water extent is probably an important variable for wetland birds anyway.

**3. Bad coordinates in the input.** One CWMP row (site 5539) has longitude **+80.45**, which should almost certainly be −80.45. It was processed as a point in Asia.

- **Fix:** correct the source value, and add a check (item 6) so this can't recur.

## Tier 2: Misleading or ambiguous results

**4. A blank cell can mean three different things.**

- It can mean (a) the class isn't in the buffer, (b) the point is outside the dataset's coverage (Canadian points for NLCD and NWI; that's 1,976 CWMP rows), or (c) the calculation errored. `process_one_landcover` catches every exception, prints it, and returns `{}`, so an error looks exactly like an absent class.
- **Fix:** fill 0 where a row has coverage but the class is absent. Leave NaN where there's no coverage. Add a status column per source and buffer (e.g. `nlcd_buff500_status = ok | no_coverage | error`), and write errors to a log file instead of only printing them.

**5. NWI percent uses a different denominator than land cover.**

- `nwi_*_percent` is each class's share of the *mapped NWI area*, while land cover percent is share of the *buffer*. Columns with the same name mean different things, and NWI percents sum to 1.0 by definition, so that check proves nothing.
- **Fix:** either compute NWI percent as `area / buffer_area`, or keep both and rename the current one to something like `_pct_of_nwi`. Also note that `lake` and `riverine` are deep-water habitat, not wetland. Consider separating them, or at least document it.

**6. No input validation step.**

- What it should catch: exact duplicate rows (GLFWRA rows 31 and 32), PIDs that aren't unique (MPCAR2R uses `1` at several sites), and the positive longitude above.
- **Fix:** add a `validate_inputs()` step that stops or warns on duplicate rows, duplicate IDs, missing coordinates, and coordinates outside a Great Lakes bounding box. Use a composite key (`Site` + `PID`) for joins.

**7. Masking relies on the raster having a nodata value.** [land_cover.py](libs/land_cover.py), `nlcd_buffer_clip` and `nalcms_buffer_clip`

- `mask(..., filled=True)` fills pixels outside the buffer with the raster's nodata value. If a raster has no nodata value set, they're filled with 0 and counted as valid pixels.
- The current outputs look fine (total area ≈ πr²), so this isn't causing errors today, but it would break silently with a different raster.
- **Fix:** use `filled=False` and keep only the unmasked pixels, so pixels outside the buffer are excluded no matter how the raster is set up. Also remove `250: "NoData"` from `NLCD_CLASS_LUT` so nodata can never be written out as a class.

## Tier 3: Workflow and reproducibility

**8. Add automated QA checks.** `tests/` is empty. Turn the checks from this review into a script that runs after each run:

- land cover percent sums ≈ 1
- class areas sum to πr² within a tolerance (3% at 200 m, under 0.5% at larger buffers)
- NWI area ≤ buffer area
- no NWI codes with all-even counts across a row
- count, area and percent blank together
- `area == count × pixel_area`

**9. Document and pin the source data.** The NALCMS rasters and NWI geopackages referenced in the script aren't on this machine, so the outputs can't be rebuilt or audited here. Record where each came from, the download date and version (NWI changes over time), and how to rebuild `nwi_filelist.json`.

**10. Decide how repeat visits should be buffered (CWMP).**

- There are 4,941 rows but only 2,120 unique site + point combinations. The GPS coordinates for the same point differ slightly between years (4,707 unique coordinate pairs).
- Decide whether buffers belong to the *point* (use one canonical coordinate per point) or the *visit*. Point-level would also cut processing roughly in half.

**11. Match land cover year to survey year.** CWMP surveys run 2011–2024, but every row gets all of 2010, 2015, 2020 and 2023. Consider adding a "nearest land cover year" set of columns so models use the right year without extra steps. NALCMS has no 2023, so decide what to do there.

## Tier 4: Minor improvements

**12. Read NWI once per point, not once per buffer.** Read and clip for the 2,000 m buffer, then clip that result down to 1,000, 500 and 200 m. That's about 4× less file I/O.

**13. Write long-format output.** The CWMP CSV has 6,342 columns and is 60 MB. A long format (`id, source, buffer, year, class, count, area, percent`) is smaller and easier to check. Pivot it to wide at the end if a model needs that.

**14. Treat NWI `_count` with caution.** It counts polygons, which depends on how NWI split the features and on where the buffer edge cuts them. It isn't a meaningful ecological measure. Drop it or document what it means.

**15. Pixel-center masking is coarse at 200 m.** A 200 m buffer holds only about 139 pixels, so the area is only accurate to about ±3%. If that matters, use fractional pixel coverage (e.g. `exactextract`); otherwise just document it.

**16. Small code-hygiene fixes:**

- Replace the mutable default arguments (`nlcd_paths: dict = {}`) with `None`.
- Comment the `from osgeo import gdal` import in [land_cover.py](libs/land_cover.py). In this env, `rasterio` fails to load without it, and it looks unused, so a linter or a cleanup could delete it.
- Fix the leftover module header (`# nlcd.py` at the top of `land_cover.py`).

`✶ Insight ─────────────────────────────────────`

- Items 1 and 2 are different kinds of bug. #1 adds data (rows duplicated by combining files), and #2 drops data (a class left out of the output but still in the denominator). Item 8's "area ≈ πr²" and "NWI area ≤ buffer" checks catch both, which is why turning this review's checks into a script is worth it.
- Item 4 matters most for whoever builds models on this. Treating a blank as zero is correct for 55% of cells in GLFWRA but wrong for every Canadian CWMP row. Keeping "absent" and "no data" as separate values stops that mistake from carrying into the analysis.
`─────────────────────────────────────────────────`

Items 1, 2, 4, 5 and 7 are code changes I can make now, and item 8 would let us confirm they worked. Items 3, 6, 10 and 11 need decisions from you or whoever owns the data. Do you want me to start on Tier 1?
