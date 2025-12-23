# Appendix: Threshold Calibration and Discussion

This document outlines a workflow to help you choose the thresholds for NDVI and NDMI that can be applied to the full dataset.

The detailed workflow for quantifying emergent vegetation for a single image for a site is in [step2_steps.md](step2_steps.md).

See the discussion at the end for how to apply the results of this workflow towards selecting thresholds.

1. **Pick representative calibration sites**

   - Select **6–10** sites that span the variability you expect (clear vs turbid water, lots vs little emergent, different Great Lakes).

2. **Lock the workflow settings (same for everything)**

   - Use the same:

     - distance-to-water method (Euclidean Distance from water-only raster),
     - emergent “near-water” distance threshold (e.g., **X = 60 m**),
     - and any smoothing/cleanup steps.

3. **Define three fixed NDVI/NDMI threshold sets**

   - **Low:** NDVI > **0.20**, NDMI > **0.00**
   - **Mid:** NDVI > **0.30**, NDMI > **0.10**
   - **High:** NDVI > **0.35**, NDMI > **0.20**

4. **Identify a start year and an end year** for your calibration period (e.g., 2015 and 2025).

5. **Run the [full emergent workflow](step2_steps.md) on the calibration sites for each year**

   - For each calibration site and each target year (e.g., 2015 and 2025):

     - compute NDVI and NDMI
     - compute water mask from Fmask
     - compute distance-to-water
     - compute emergent mask 3 times (low/mid/high) using your same rule
     - summarize **emergent area** inside the site polygon for each threshold set

6. **Compute change per site (paired, within-site)**

   - For each calibration site:

     - `Δ_low = Emergent_low_2025 − Emergent_low_2015`
     - `Δ_mid = Emergent_mid_2025 − Emergent_mid_2015`
     - `Δ_high = Emergent_high_2025 − Emergent_high_2015`

7. **Set a “minimum meaningful change” tolerance**

   - Use a tolerance to avoid over-interpreting 1–2 pixels at 30 m:

     - **2 pixels = 0.18 ha** is a good default (since 1 pixel = 0.09 ha)

8. **Classify each site’s change as robust or uncertain**

   - For each site:

     - **Robust increase** if Δ_low, Δ_mid, Δ_high are all **> +tolerance**
     - **Robust decrease** if all are **< −tolerance**
     - Otherwise mark as **threshold-sensitive / uncertain**

9. **Aggregate results across the calibration sites**

- You can now report on:

  - **Δ_mid** as the main change estimate
  - **[Δ_low, Δ_high]** as the threshold-sensitivity band
  - **robust / uncertain** flag based on Step 7

## Discussion

If the direction and magnitude of change are broadly similar across the three sets for most sites (and changes exceed your minimum-change tolerance), then the method is not highly threshold-sensitive and you can move forward with a single “default” threshold set, typically the **mid** set as a balanced choice. If results frequently flip sign or show large swings between low/mid/high, treat the thresholds as a major source of uncertainty and either (a) select the set that produces the most stable, least jumpy time series across the calibration sites, or (b) commit up front to reporting the **mid** results as the primary estimate while carrying **low/high** as an uncertainty band and flagging sites where the change is not robust. In all cases, once you choose the study-wide threshold set, freeze it and apply it consistently to every site and year so that observed differences are attributable to real landscape change rather than shifting decision rules.
