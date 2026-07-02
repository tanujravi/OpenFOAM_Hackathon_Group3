# cases/tools - pre-processing, receptor sampling, reporting

Python/Bash tooling for the Guimarães air-quality study. Split into three groups:
**case setup** (geometry, wind, emissions, streets), **receptor sampling** (surface +
volume), and **reporting** (tables, maps, PDF). Dependency-light: the reporting/analysis
scripts use `matplotlib`, `numpy` and (for the PDF) `reportlab`; everything else is
stdlib. Paths are passed on the CLI - no hard-coding.

---

## 1. Case setup (used by the flow/dispersion cases and the workflow)

| Tool | What it does |
|---|---|
| `preprocess_geometry.py` | recenter + merge geometry → `geo/` (small and big domains; `--vegetation` for the canopy) |
| `set_wind.py` | hourly `(u,v)` → ABL `Uref`/`angle` in `0/include/ABLConditions` (or a `0/U` vector) |
| `make_street_patches.py` | carve the `streets` patch out of `Terrain` (before the flow solve) |
| `add_streets_bc.py` | clone the `Terrain` BC entry into `streets` in the `0/` fields |
| `map_emissions.py` | per-segment scenario scaling (reference/S1/S2/S3); `--check` validates the S3 tiers |
| `set_emissions.py` | scaled per-segment rate → non-uniform `fixedGradient` on `streets` in `0/T` |
| `split_roi.py` | `ROI.obj` → four `receptor{1..4}.obj` + `receptors.json` (recentred + UTM centroids) |
| `split_inlet_outlet.py`, `clean_surface.py`, `set_vegetation_model.py` | inlet split, OBJ dedup, canopy porous/wall switch |

S3 note: the integers in `road_ids_reduction.txt` are the **0-based `geo_id`** (= emission-CSV
row index). Validated against the road geometry - the reduced set is predominantly the Circular
Urbana ring + one EN101 troço (the Metro-Bus corridor), not the full EN101.

---

## 2. Receptor sampling - surface AND volume

Two metrics; they agree on scenario %-changes within ~2 pp, so the **volume average is the
primary reported metric** (breathing-air exposure) and the surface areaAverage is a robustness
cross-check.

**Surface (built into the dispersion case).** `dispersionCase*/system/receptors` defines four
`surfaceFieldValue areaAverage(T)` FOs over the ROI surfaces; they run during the solve.
`collect_receptors.py --disp <run> --triSurface <dir> ...` parses their `postProcessing` output
into `receptors.csv`.

**Volume (`make_receptor_zones.py` + a collector).** Samples `T` in a box of air above each
receptor via a `volFieldValue volAverage` over a `cellZone`:

```bash
# generate topoSetDict (boxToCell -> roiNZone) + receptorsVolume FO + receptor_zone_map.json
python3 make_receptor_zones.py --disp ../dispersionCaseBig --out ../dispersionCaseBig/system \
    --halfwidth 30 --height 12 --below 2 [--exclude-zone vegetationZone]
```

- Box = receptor centroid ± `--halfwidth` in x,y and `[z-below, z+height]` (ROI cells ~5 m, so
  keep it a few cells tall). `--exclude-zone` subtracts a cellZone (e.g. canopy) from the box.
- **Two modes** (same file, different flags):
  - *Snapshot* (default): field token `__FIELD__` + a `readFields` FO - for post-processing
    already-finished runs.
  - *During-solve*: `--field T --no-readfields --wire-controldict <disp>/system/controlDict`
    - the FO rides along in the solve on the live `T` (used by `Snakefile.podrun`).

**Collect from FINISHED snapshots** (no re-solve) - `run_receptor_volumes.sh`:
```bash
FIXHDR=0 bash run_receptor_volumes.sh <MESH=flowCaseBig> <DISP=dispersionCaseBig> \
    <DISPROOT=runs_pod/disp> <out.csv> <HOURS> "CO NOx" <NP> <SCENARIO>
```
It `topoSet`s the zones into the shared mesh, then `postProcess -time 0 -parallel` on each
`T_<poll>` snapshot (a `readFields` FO loads the field, since `postProcess` doesn't auto-read).
`FIXHDR=0` skips the (slow, optional) FoamFile-header fix; `HDRJOBS` parallelizes it if needed.

**Collect from a NEW solve** (values written during the run) - `collect_receptor_volumes.sh
<DISP> <DISPROOT> <out.csv> <HOURS> "CO NOx" <SCENARIO>` - just reads `postProcessing/roiN_vol`.

Both collectors write the report schema: `hour,scenario,pollutant,receptor,site,conc_ugm3`.

---

## 3. Reporting pipeline

`receptors_long.csv` (per scenario, from either collector) → tables → maps → PDF:

```bash
# 1. tables + figures + auto report (per-scenario CSVs; volume or surface)
python3 make_report.py --run reference=<ref.csv> --run S1=<s1.csv> --run S2=<s2.csv> \
    --run S3=<s3.csv> --triSurface ../dispersionCaseBig/constant/triSurface --out report
#    -> report/{receptor_summary.csv, scenario_comparison.csv, air_quality_report.pdf, figs/}

# 2. spatial maps (road network width ~ emission; receptors coloured by concentration)
python3 make_maps.py --repo ../.. --disp ../dispersionCaseBig --report report --out report/figs
#    -> map_pollution.png, map_scenarios.png

# 3. (optional) ground-level concentration field: see ../postpro/pv_ground_slice.py

# 4. polished technical report (data-driven tables + figures + authored narrative)
python3 make_techreport.py --report report --maps report/figs \
    [--slice report/figs/<label>_T_NOx_ground.png] \
    [--compare-summary <surface receptor_summary.csv> --primary-label "volume average" \
                       --compare-label "surface area-average"] \
    --out report/technical_report.pdf
```

- `make_report.py` - per receptor/pollutant: mean & peak over the sampled hours, %change vs
  reference for S1/S2/S3; figures: grouped bars, %-change heatmap, diurnal profiles (24 h clock,
  hour 0 = 07:00). Reads `receptors_long.csv` **or** a run dir (scans `postProcessing`).
- `make_maps.py` - `map_pollution.png` (network + S3 corridor + receptors coloured by concentration)
  and `map_scenarios.png` (receptors per scenario, shared scale). Overlay uses `centroid_recentred`
  from `receptors.json` (same frame as the mesh).
- `make_techreport.py` - reportlab PDF: exec summary, methodology, scenarios, results (tables +
  Fig 1 bars, Fig 2 heatmap, Fig 3/4 maps, optional Fig 5 ground slice), §4.4 sensitivity
  (`--compare-summary` = surface vs volume), discussion, limitations. Headline numbers are
  computed from `receptor_summary.csv`.

**POD helper:** `select_hours.py` (maximin hour selection for the POD-snapshot run).

---

## 4. Gotchas
- The reporting scripts are dependency-light but need `reportlab` for `make_techreport.py`
  (`pip install --user reportlab`); if unavailable, the other outputs (CSVs, figs,
  `air_quality_report.pdf`, maps) still work.
- `postProcess` on decomposed snapshots does NOT auto-read fields → the volume FO file includes a
  `readFields` FO; the snapshot field lives at **time 0** as `T_<poll>` (stashed by
  `run_disp_decomp.sh`), and its FoamFile `object` header still says `T`.
- Keep the box geometry (`--halfwidth/height/below`) identical across metrics/scenarios so results
  are comparable.
