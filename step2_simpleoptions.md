# Option A — Easiest: “Two indices + one buffer” (desktop-only)

**Workflow**

- Load a clear Landsat image (per year) in QGIS/ArcGIS; apply cloud/shadow mask.
- Compute indices:

  - **NDVI** (greenness) and **MNDWI** (water).

- Build masks:

  - Water = MNDWI ≥ one chosen cutoff (pick once on a sample site).
  - Riparian = fixed buffer around the water mask (e.g., 90 m).
  - Emergent = pixels inside the buffer with NDVI ≥ one chosen cutoff (e.g., 0.40).

- Optional cleanup: remove tiny specks (morphology).
- Zonal statistics: total areas of water, emergent, riparian inside each wetland polygon.

**Pros**

- Fastest, no coding or labeling, fully transparent.

**Cons**

- Coarse edges at 30 m; fixed buffer may include uplands; low-NDVI but moist emergent can be undercounted.

---

# Option B — Medium: “Auto-threshold + distance-to-water + object cleanup”

**Workflow**

- Preprocess per year; compute **NDVI** (greenness), **MNDWI** (water), **NDMI** (moisture).
- Water = **Otsu** (automatic histogram-based) threshold on MNDWI.
- Compute **distance-to-water** (per-pixel meters; replaces fixed buffer).
- Emergent = NDVI high AND NDMI moderate/high AND distance ≤ X m (e.g., 60 m).
- Riparian = distance ≤ R m (e.g., 120 m); optionally require NDMI ≥ τ for “riparian vegetated.”
- **SLIC** superpixels (object segmentation) → majority vote per object; remove tiny objects; smooth edges.
- Zonal statistics by polygon.

**Pros**

- Cleaner boundaries, fewer false positives; thresholds adapt per scene; still minimal labeling.

**Cons**

- Some scripting/model-builder work; more compute than A; parameters (X, R, SLIC size) need one-time tuning.

---

# Option C — Hardest: “Trained model + probabilities + strict adjacency” (fully coded)

**Workflow**

- Create modest labeled data on representative sites: {water, emergent, riparian-veg, other}.
- Build features: bands (Green/Red/NIR/SWIR), indices (NDVI/MNDWI/NDMI), simple textures, distance-to-water.
- Train per-sensor **Random Forest / Gradient-Boosted Trees**; validate; pick probability cutoffs (e.g., target ≥70% precision for “emergent”).
- Predict per year; enforce adjacency rules (emergent/riparian must be within X/R m of water).
- Optional SLIC/CRF cleanup; write probability/confidence layers.
- Zonal statistics by polygon; log thresholds/models for reproducibility.

**Pros**

- Highest accuracy and consistency; probability outputs enable calibrated QA and uncertainty reporting.

**Cons**

- Front-loaded labeling/validation; full Python/GEE pipeline; per-sensor models to maintain.
