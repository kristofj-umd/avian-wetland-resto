Perfect—here’s a tightened set of three workflows that clearly stair-step from **quickest/simplest** to **slowest/most accurate**. I made **Option A** much simpler, and clarified how **C** improves on **B**.

---

# Option A — Easiest / fastest / desktop-only

**“Two indices + one buffer” (no scripting).**

**What you do (per year):**

1. Open a clear Landsat image near your target day-of-year in QGIS/ArcGIS; apply the cloud mask if available.
2. Make two rasters with the Raster Calculator:

   - **NDVI** (_Normalized Difference Vegetation Index_ = greenness).
   - **MNDWI** (_Modified ND Water Index_ = open water).

3. Create a **water mask**: MNDWI ≥ a single cutoff (pick once on a sample site, then reuse).
4. Draw a **fixed buffer** around the water mask (e.g., 90 m) to define **riparian**.
5. Define **emergent vegetation** as pixels that are **inside the buffer AND NDVI ≥ a single cutoff** (e.g., 0.4).
6. Run **zonal statistics**: within each wetland polygon, count area of water, emergent, and riparian.

**Knobs (only three numbers):**

- MNDWI cutoff (water), NDVI cutoff (vegetation), buffer distance (riparian).

**Pros:** dead simple, explainable, fast to run for all 60 polygons × 4 years.  
**Cons:** coarse boundaries (30 m), can miss moist but low-NDVI emergent, fixed buffer may include uplands on steep banks.

---

# Option B — Medium effort / hybrid desktop + light scripting

**“Auto-threshold + distance-to-water + object cleanup.”**

**What’s added vs A (and why it’s better):**

- Add **NDMI** (_Normalized Difference Moisture Index_ = moisture from NIR & SWIR) to better separate emergent from upland veg.
- Use an **automatic threshold** (e.g., Otsu) to set water/veg cutoffs per scene rather than hand-picking once—more robust across sites/years.
- Replace fixed buffer with a **distance-to-water raster** so you can say “within ≤ X m” precisely at every pixel.
- Clean boundaries with **object-based** steps (e.g., SLIC superpixels or connected-components) so patches aren’t speckly.

**What you do (per year):**

1. Preprocess (cloud/shadow mask). Compute **NDVI**, **MNDWI**, **NDMI**.
2. **Water mask** via MNDWI with **auto-threshold** (Otsu), then compute **distance-to-water** (in meters).
3. **Emergent** = NDVI high (auto-threshold or set once) **AND** NDMI moderate/high **AND** distance ≤ X (e.g., 60 m).
4. **Riparian** = distance ≤ R (e.g., 120 m), optionally require NDMI ≥ τ to report “riparian vegetated.”
5. **Object cleanup:** run **SLIC** (_Simple Linear Iterative Clustering_—groups similar adjacent pixels) or just remove tiny blobs; majority-filter by object.
6. Zonal statistics to polygons; export rasters.

**Pros:** noticeably cleaner edges and fewer false positives in uplands; adapts to per-scene brightness/wetness.
**Cons:** a bit of scripting (Python or a QGIS model) and one extra index; slightly more compute.

---

# Option C — Hardest / most work / fully coded & most accurate

**“Trained model + probabilities + strict water adjacency.”**

**What’s added vs B (and why it’s better):**

- You **teach** a model using a small labeled set (examples of water, emergent, riparian-veg, other) from a few representative wetlands.
- The model learns subtle spectral patterns (e.g., shaded water, variable sediment, dense vs sparse emergent) that fixed rules can’t capture.
- You get **probabilities** per class (with a chosen cutoff), which helps control precision/recall and report uncertainty.
- Keep **separate models per sensor family** (Landsat-5/7 for 2010 vs Landsat-8/9 for 2015/20/25; add Sentinel-2 in 2020/2025 if you want sharper boundaries).
- Still apply **distance-to-water** rules after prediction so “emergent” can’t appear far from water.

**What you do (once, then per year):**

1. **Label** a modest set of pixels/objects on 2020/2025 images (a few sites each): classes = water, emergent, riparian-veg, other.
2. Train a **Random Forest (RF)** or **Gradient-Boosted Trees (GBM)** on features: bands (Green/Red/NIR/SWIR), **NDVI**, **MNDWI**, **NDMI**, simple textures, **distance-to-water**.
3. **Validate**, pick probability cutoffs (e.g., choose a threshold that gives ≥ 70% precision for “emergent”). Freeze model + cutoffs.
4. For each year: preprocess like B, run the model, then enforce **adjacency** (emergent/riparian must be within X/R meters of water), clean small bits, and do zonal stats.

**Pros:** best separation of classes, calibrated thresholds, explicit uncertainty, repeatable at scale.
**Cons:** front-loaded labeling/validation and a full (but manageable) Python workflow.

---

## Quick chooser

- **Need a one-afternoon run with minimal decisions?** Use **Option A** (NDVI + MNDWI + fixed buffer).
- **Want better maps with modest extra effort and still no labeling?** Use **Option B** (add NDMI, auto-thresholds, distance-to-water, object cleanup).
- **Want the best, most defensible results across diverse wetlands?** Use **Option C** (train a small model + probabilities + adjacency).

If you want, I can turn any option into a minimal checklist (or a tiny QGIS model/Python script) tailored to your 60 polygons and four years.
