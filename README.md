# Guimarães Air-Quality / Mobility-Scenario CFD Workflow

OpenFOAM workflow for the OFW21 hackathon: quantify how four sustainable-mobility
scenarios change **CO and NOx** concentrations at four sensitive receptors
(Martins Sarmento HS, Francisco de Holanda HS, Santos Simões HS, Public Hospital)
relative to a reference case, on the real 3-D terrain of Guimarães.

This README documents the pipeline end to end: the recentred geometry frame, the
meshing strategy, the two-solver (flow → dispersion) split, the post-mesh street
patch creation, the emission mapping, receptor sampling, and the orchestration.


**Note:** `canopy/merged.obj` (1.5 GB) is not committed to this repo. The vegetation canopy
is handled on the **big domain** (`flowCaseBig`/`dispersionCaseBig`) as a porous momentum
sink for the flow and a scalar sink for the dispersion; the dispersion canopy is now a
**finite deposition** −λT (`scalarSemiImplicitSource`), replacing the earlier perfect-sink
(T=0) trial — see `dispersionCaseBig/constant/fvOptions`.

> **Status (updated).** The pipeline below is complete and has run end-to-end on the cluster:
> all four scenarios (reference/S1/S2/S3), the 24 h→10 representative-hour POD sweep, receptor
> tables (surface **and** volume metrics), spatial maps, a ground-level concentration field, and
> an auto-generated technical report. See §11 for the reporting/analysis toolchain and
> `cases/tools/README.md` for the tools. The `Ricardo Andrade note:` TODOs are resolved inline below.
---

## 1. Big picture

```
                provided data (read-only)
   terrain + buildings + canopy + roads + emissions + wind
                          │
            cases/tools/preprocess_geometry.py   (recenter to origin, merge buildings)
                          │
                       geo/  (recentred OBJs + transform.json)
                          │
        ┌─────────────────┴───────────────────┐
        │  STAGE 0  MESH  (runallgeo.sh)       │  snappyHexMesh on the terrain
        │  blockMesh → snappy → checkMesh      │  + ROI buildings (one mesh, reused)
        └─────────────────┬───────────────────┘
                          │  constant/polyMesh
        ┌─────────────────┴───────────────────┐
        │  STAGE 1  WIND  (cases/flowCase)     │  simpleFoam, k-ε ABL, steady RANS
        │  per-hour ABL inlet (Uref,angle)     │  → frozen U, phi, nut
        └─────────────────┬───────────────────┘
                          │  frozen flow fields
        ┌─────────────────┴───────────────────┐
        │  STAGE 2  DISPERSION (dispersionCase)│  scalarTransportFoam on frozen flow
        │  set per-segment emission -> solve   │  one passive scalar per pollutant
        └─────────────────┬───────────────────┘
                          │  T (kg/m³)
        ┌─────────────────┴───────────────────┐
        │  STAGE 3  RECEPTORS + TABLE          │  areaAverage(T) at the 4 ROI sites
        └──────────────────────────────────────┘  results/.../receptor_table.csv (µg/m³)
```

Driver `cases/run_single_hour.sh` chains Stages 1–3 for one hour / one scenario.
The same mesh, BCs, solver settings and temporal strategy are reused across all
four scenarios — **only the emission scaling changes** — so comparisons are fair.

---

## 2. Provided data (read-only inputs)

| Path | Contents |
|---|---|
| `terrain_and_buildings/Mesh_Terrain.obj` | 6.3 × 6.3 km terrain, real relief (Z 143–613 m) |
| `terrain_and_buildings/Mesh_Buildings_0..5.obj` | ROI buildings |
| `terrain_and_buildings/Mesh_Buildings_6.obj` | far-field buildings (excluded from the small-domain build) |
| `canopy/merged.obj` | vegetation surface (1.5 GB; porous-zone candidate, **not** a wall) |
| `bigger_terrain_results/city4CFD/` | alternative 25 × 25 km domain (for the domain-influence study) |
| `traffic/emission_factor_per_segment_{CO,NOx}.csv` | 196 segments × 24 hourly columns, **units g/h** |
| `traffic/snapped_road_segments.csv` | 196 road LINESTRING Z, snapped to terrain |
| `wind_data/wind_velocity_time.csv` | hourly (u, v) reference wind, 24 bins 07:00→07:00 |
| `road_ids_reduction.txt` | Scenario-3 road IDs: a 50%-list (19) and a 30%-list (28) |
| `ROI/ROI.obj` | the four receptor surfaces (4 connected components) |

Coordinates are a projected CRS in metres; all layers share the frame and overlay
directly. Row order in the emission CSVs == segment order == road ID == 0-based row
index (validated: IDs ≤ 192 < 196, the two S3 tiers don't overlap).

---

## 3. Recentred coordinate frame
**Resolved:** validated — this pure translation is used for every run; the recentred and UTM
receptor centroids in `receptors.json` overlay the road network exactly (confirmed when building
the spatial maps in `cases/tools/make_maps.py`).

The provided geometry sits at large UTM-like offsets (X ≈ −13 000, Y ≈ 197 000).
The mesh templates assume a city centred on the origin with the ground near Z = 0,
so a single **pure translation** is applied to every geometry layer:

```
X' = X − X0   (X0 = terrain X bbox-centre = −13152.617)
Y' = Y − Y0   (Y0 = terrain Y bbox-centre =  197434.738)
Z' = Z − Z0   (Z0 = terrain min elevation =     142.676)
```

Result: terrain spans ±3150 m in X/Y and Z 0–470 m; the ROI sits at the origin.
The transform is recorded in `geo/transform.json` (with its inverse) so receptor
results and source locations map straight back to real UTM coordinates.

Translation-invariant and therefore **not** transformed: the wind `(u, v)` vectors
and the per-segment emission factors. No rotation is applied (the inlet handles
arbitrary wind direction — see §5).

`cases/tools/preprocess_geometry.py` performs the recenter, merges `Mesh_Buildings_0..5`
into one `Mesh_Buildings.obj` (far-field `_6` excluded), recentres `ROI.obj` and the
road coordinates, and writes everything to `geo/`.

---

## 4. Stage 0 — Meshing strategy (`cases/flowCase/runallgeo.sh`)

A single `snappyHexMesh` mesh is built **once** and reused for every hour and
scenario (fairness + cost). Driven on the cluster by `cases/flowCase/runallgeo.sh` (SLURM, 96
ranks): `surfaceFeatureExtract → blockMesh → decomposePar → snappyHexMesh -parallel
→ reconstructParMesh → checkMesh`.

**Background domain — `system/blockMeshDict.m4`.** A COST732-style **cylinder**
generated by `m4`: outer vertices on a circle (radius set to **3000 m**, terrain-
limited — the source-city's `15·H + 2·s` rule would overrun our fixed 6.3 km
footprint), arc edges, and one all-round side patch named `inletOutlet`. Floor at
Z = −10 (below the lowest terrain), top at ~1870 m (clears the 470 m of terrain
relief plus a deep ABL). Patches: `inletOutlet` (cylinder side), `bottom` (flat
floor), `top` (`symmetry`).

> The `m4` `calc` macro defines `pi` inline (`4*atan2(1,1)`) so it needs **no Perl
> `Math::Trig`** module — this was a cluster failure (`Can't locate Math/Trig.pm`).

**Surfaces — `system/snappyHexMeshDict`.** `Mesh_Buildings` and `Mesh_Terrain` are
snapped as `wall` patches (`Buildings`, `Terrain`); refinement boxes are sized to
the ~3.2 × 2.3 km ROI; `locationInMesh (0 0 800)` sits in the air above all terrain.
Terrain at refinement level 4, buildings at 5 (cell-count balance). Canopy and
"water" are **not** meshed (no water provided; canopy is a porous-zone step).

**Key mesh facts after the first run** (~1.71 M cells, mostly hexahedra):
- The `bottom` patch is **fully carved away** (its faces lie below the terrain), so
  the live mesh exposes only **4 patches**: `inletOutlet`, `top`, `Buildings`,
  `Terrain`. The `0/` fields therefore do **not** reference `bottom`.
- checkMesh passes apart from a moderate skewness flag (max ~5) and ~70° max
  non-orthogonality — normal for snapped urban terrain. The flow `fvSolution` uses
  `nNonOrthogonalCorrectors 2` to handle it.

---

## 5. Stage 1 — Wind precursor (`cases/flowCase`, `simpleFoam`)

Steady RANS (`simpleFoam`, **k-ε** with neutral-ABL coefficients, Hargreaves &
Wright) produces the hourly wind field that the dispersion stage advects on.


**Resolved:** the atmospheric-inlet BCs below were used for all production runs; the two-stage
flow converges and the resulting receptor concentrations are physically reasonable (NOx ≈ 3–6 µg/m³
mean at the receptors, well below EU/WHO NO2 references).

**Atmospheric boundary-layer inlet (the `round`-template approach).** The domain
boundary is a single cylindrical `inletOutlet` patch and the hourly wind arrives from
a different direction each hour, so we use OpenFOAM's flux-aware **atmospheric** BCs:
they impose the ABL log-law profile where flow enters and switch to zero-gradient
where it leaves. One fixed mesh handles every wind direction, with a physically
correct profile (better than a uniform/freestream guess). Needs the
`atmosphericModels` library (`libs (atmosphericModels);` in `controlDict`).

| field | `inletOutlet` patch | walls (`Terrain`, `Buildings`) | `top` |
|---|---|---|---|
| `U` | `atmBoundaryLayerInletVelocity` (log-law in `flowDir`) | `noSlip` | `symmetry` |
| `p` | `freestreamPressure` | `zeroGradient` | `symmetry` |
| `k` | `atmBoundaryLayerInletK` | `kqRWallFunction` | `symmetry` |
| `epsilon` | `atmBoundaryLayerInletEpsilon` | `atmEpsilonWallFunction` (Terrain, z0) / `epsilonWallFunction` (Buildings) | `symmetry` |
| `nut` | `calculated` | `atmNutkWallFunction` (Terrain, z0 = 0.25 m) / `nutkWallFunction` (Buildings) | `symmetry` |

The profile is parameterised in `0/include/ABLConditions` (`Uref`, `Zref`, `angle`,
`z0`). `cases/tools/set_wind.py --hour H` writes the hour's wind as `Uref = |(u,v)|` and
`angle = atan2(v,u)` so `flowDir` matches the data (it auto-detects the ABL case; for
the legacy freestream `0/U` it instead sets the `(u,v,0)` vector via a
`// HOURLY WIND` marker).

**Solver robustness — 1st-order warm-up, then 2nd-order.** On this stiff terrain mesh
(470 m relief, ~72° non-orthogonality) starting fully 2nd-order diverges:
`limitedLinear` on `k`/`epsilon` lets them overshoot, `nut = Cμ·k²/ε` blows up, and the
GAMG pressure solve hits a floating-point exception (~iteration 10). So the run is
two-stage (`job_flow.sh`): converge with **`fvSchemes_1storder`** (upwind `k`/`epsilon`,
bounded), then restart from `latestTime` with **`fvSchemes_2ndorder`** for accuracy. A
`potentialFoam` step initialises `U`/`p`; `fvSolution` uses plain SIMPLE
(`consistent no`), under-relaxation, and `nNonOrthogonalCorrectors 2`.

> The earlier **freestream** inlet (k-ω SST) is kept as a fallback in
> `cases/flowCaseOldBC`. It stays bounded but its pressure residual plateaus (~0.15)
> because freestream only weakly constrains the pressure level; the ABL setup with
> `freestreamPressure` converges better.

---

## 6. Stage 2 — Dispersion (`dispersionCase`, `scalarTransportFoam`)

The converged wind (`U`, `phi`, `nut`) is **frozen** and copied in; a passive scalar
`T` is then transported by `scalarTransportFoam` with constant turbulent
diffusivity `DT` (≈1 m²/s, a crude Sc_t stand-in). `T` carries dimensions **kg/m³**,
so the solved field is an absolute concentration (×1e9 → µg/m³).

**Two pollutants = two runs.** `scalarTransportFoam` solves one scalar per run, so
CO and NOx are solved **separately** on the same frozen wind (kept distinct, never
summed). The driver loops `CO` then `NOx`, saving `T_CO` and `T_NOx`.
*(A single-run alternative — two `scalarTransport` function objects, each with an
`fvOptions` `scalarSemiImplicitSource` — is noted in §10 as the production option.)*

**Resolved:** tested on the cluster — the single `streets` non-uniform `fixedGradient` approach
ran successfully for every hour/scenario/pollutant (CO and NOx kept separate). This is the
production dispersion setup.


## 6.1 Street patch creation (carved in the FLOW case, BEFORE solving)

The roads are **not** in the mesh (only terrain + buildings are), so the road
footprint is carved out of the `Terrain` ground as a `streets` wall patch. This is
done **once in `cases/flowCase`, before the flow solve** (inside `job_flow.sh`), so
every field is written on the final `Terrain`+`streets` mesh.

> Why before the solve: `createPatch` *moves* faces out of `Terrain` (e.g.
> 570191 -> 542115), so carving AFTER the flow would leave the copied non-uniform
> boundary lists (e.g. `nut` on `Terrain`) the wrong length -> a fatal size mismatch.
> Carving first means the fields are generated on the split mesh and stay consistent.

1. `cases/tools/make_street_patches.py` finds the `Terrain` faces whose centres lie within
   `--half-width` (default 6 m) of any road polyline, tags each with its nearest
   segment (numpy-vectorised), and writes `constant/polyMesh/sets/streets`,
   `system/createPatchDict`, and `geo/streets_face_segments.csv` (face -> segment +
   area, in patch order). Any segment otherwise *starved* (always 2nd-nearest, or
   sitting under a building) is force-assigned its nearest ground face, so all 196
   segments are represented and total emission is preserved.
2. `createPatch -overwrite` splits those faces off `Terrain` into the `streets` patch.
3. `cases/tools/add_streets_bc.py` clones each field's `Terrain` entry into a `streets`
   entry in the **uniform** `0/{U,p,k,epsilon,nut}` (size-agnostic) — `createPatch`
   does not propagate the new patch into the fields by itself.

The dispersion case then **reuses** this split mesh + frozen fields +
`streets_face_segments.csv` and never carves, so field/patch sizes always match.

> Check `make_street_patches`'s `segments with faces: N/196` (now always 196/196 via
> the force-assign). The mesh must be **ASCII** for the carver; `job_flow.sh` runs
> `foamFormatConvert` first if it is binary.

### 6.2 Emission mapping (the scenario logic)
**Resolved:** all four scenarios (reference/S1/S2/S3) have been run. The S3 ID→segment mapping was
validated against the road geometry — the integers in `road_ids_reduction.txt` are the **0-based
`geo_id`** (emission-CSV row index), and under that mapping the reduced set is predominantly the
**Circular Urbana** ring plus one **EN101** troço, i.e. the Metro-Bus corridor (not the full EN101).

`cases/tools/map_emissions.py` applies the mobility-scenario scaling to the per-segment
hourly factors (this is the "correct scenario implementation" deliverable):

| Scenario | Definition | Scaling |
|---|---|---|
| reference | provided data | ×1.0 |
| S1 | 20% of gas vehicles → EV | ×0.8 all segments |
| S2 | 40% → EV | ×0.6 all segments |
| S3 | Metro Bus (N101) | ×0.5 on the 50%-list, ×0.7 on the 30%-list, ×1.0 elsewhere |

`cases/tools/set_emissions.py` then converts the scaled per-segment rate to a wall flux and
writes it as a **non-uniform `fixedGradient`** on the `streets` patch in `0/T`:

```
each face f of segment s:  gradient_f = flux_s / DT,
                           flux_s     = (E_s · unit_scale) / A_s
```
with `E_s` the scaled CSV value, `A_s` the segment's total carved street-face area,
and `unit_scale = 1/(1000·3600)` converting **g/h → kg/s**. The wall balance
`DT · gradient · area = segment emission rate [kg/s]` then holds, and `T` is an
absolute concentration. (Sanity check: a ~30 g/h segment over ~1000 m² gives
~8e-9 kg/(m²·s), squarely in the documented busy-street range.)

---

## 7. Stage 3 — Receptors & results table

**Resolved:** implemented. Two receptor metrics are available and give the same scenario
conclusions (see §11): (1) the surface `areaAverage` below, and (2) — as suggested — a **volume
average of the breathing air in a box above each receptor** (`volFieldValue` over a `cellZone`
built by `cases/tools/make_receptor_zones.py`). The **volume average is the primary reported
metric** (breathing-air exposure); the surface areaAverage is kept as a robustness cross-check
(the two agree on scenario %-changes within ~2 percentage points).

The four receptors are the four connected components of `ROI.obj`, split by
`cases/tools/split_roi.py` into `dispersionCase/constant/triSurface/receptor{1..4}.obj`
(+ `receptors.json` with each centroid in recentred and UTM coords).

`system/receptors` defines four `surfaceFieldValue` function objects, each an
**`areaAverage` of `T`** over one receptor surface; they run inside
`scalarTransportFoam` (via `controlDict` `functions{}`) and write
`postProcessing/receptorN/.../surfaceFieldValue.dat`.

`cases/tools/receptor_table.py` reads those, converts to **µg/m³**, and writes
`results/<run>/receptor_table.csv`. With `--reference <dir>` it adds absolute and
**% change vs the reference scenario** per receptor/pollutant.

> Receptor `site_name`s are resolved: receptor1 = Hospital da Senhora da Oliveira (Public
> Hospital), receptor2 = E.S. Francisco de Holanda, receptor3 = E.S. Martins Sarmento,
> receptor4 = E.B./S. de Santos Simões (in `receptors.json`).

---

## 8. Orchestration — flow precursor, then dispersion driver
**Resolved:** the single-hour driver below still works, and on top of it the **24-hour sweep and
POD-snapshot orchestration are built** (`cases/workflow/`: `Snakefile`, `Snakefile.transient`,
`Snakefile.podrun`), submitting to SLURM via Snakemake's **cluster-generic** executor. The POD
workflow additionally computes the surface + volume receptor tables and the report inputs — see
`cases/workflow/README_podrun.md` and §11.

A one-hour run is **two steps**, both launched from inside `cases/`. The flow is
solved once for the hour (it carves the `streets` patch into its own mesh *before*
solving), then the dispersion driver `cases/run_single_hour.sh` reuses that frozen
flow for each scenario / pollutant.

```bash
# (0) mesh once (per study):   cd cases/flowCase && sbatch runallgeo.sh
# (1) set the hour's wind:     python3 ../tools/set_wind.py --case . --hour 0
# (2) flow precursor:          sbatch job_flow.sh      # carve streets + 2-stage simpleFoam
# (3) dispersion + receptors (run from cases/):
cd ..                                                  # -> cases/
mkdir -p logs results                                  # SLURM needs logs/ to exist before sbatch
HOUR=0 SCENARIO=reference sbatch run_single_hour.sh    # defaults: POLLUTANTS="CO NOx" NPROCS=128 DT=1.0
HOUR=0 SCENARIO=S2        bash  run_single_hour.sh     # any hour / scenario
```

Stage 1 (`cases/flowCase/job_flow.sh`): carve `streets` → `potentialFoam` →
`simpleFoam` (1st- then 2nd-order, parallel) → frozen `U`, `phi`, `nut`.
Stages 2–3 (`cases/run_single_hour.sh`): reuse the split mesh + frozen fields, then
per pollutant `set_emissions` + `scalarTransportFoam` (parallel) → receptor table.
Outputs land in `cases/results/h<HOUR>_<SCENARIO>/` (`T_CO`, `T_NOx` in kg/m³;
`receptor_table.csv` in µg/m³; per-pollutant `pp_*` postProcessing).

---

## 9. Directory layout

```
referenceCase/
  README.md                   this file
  CLAUDE.md                   standing rules
  <provided data>             terrain_and_buildings/ canopy/ traffic/ wind_data/ ROI/
                              road_ids_reduction.txt   (read-only inputs, repo root)
  cases/
    run_single_hour.sh        STAGES 2–3 dispersion driver (SLURM), per hour/scenario
    tools/
      preprocess_geometry.py  recenter + merge geometry -> cases/flowCase/geo/
      set_wind.py             hourly (u,v) -> ABL Uref/angle (or 0/U vector)
      make_street_patches.py  carve the streets patch (in flowCase, before solve)
      add_streets_bc.py       clone Terrain BC -> streets in 0/ fields
      map_emissions.py        per-segment scenario scaling (reads repo-root traffic/, road_ids)
      set_emissions.py        per-segment non-uniform fixedGradient on streets
      split_roi.py            ROI -> 4 receptor surfaces
      receptor_table.py       receptor µg/m³ table (+ % vs reference)
      # --- reporting & analysis (see cases/tools/README.md) ---
      make_report.py          receptors_long.csv -> receptor_summary + figs + air_quality_report.pdf
      make_maps.py            spatial maps (road network + receptor concentrations, per scenario)
      make_techreport.py      polished technical_report.pdf (--compare-summary = surface vs volume)
      make_receptor_zones.py  volume-average receptor cellZones + volFieldValue FO (snapshot|solve)
      run_receptor_volumes.sh volume receptors from FINISHED snapshots (postProcess + readFields)
      collect_receptor_volumes.sh  gather volume receptors written DURING the solve
      collect_receptors.py    surface receptor postProcessing -> receptors.csv (sweep collector)
      aggregate_day.py select_hours.py clean_surface.py set_vegetation_model.py  (sweep/POD helpers)
    flowCase/                 FLOW case: ABL inlet (atmBoundaryLayerInlet*), k-epsilon
      runallgeo.sh            STAGE 0 meshing (SLURM)
      job_flow.sh             STAGE 1 flow: carve streets + 2-stage simpleFoam (SLURM)
      0/ system/ constant/ geo/
    flowCaseOldBC/            FLOW case, freestream inlet + k-omega SST (fallback)
    dispersionCase/           DISPERSION case: 0/T system/ constant/triSurface/ geo/
    flowCaseBig/  dispersionCaseBig/   BIG 25 km city4CFD domain (porous + finite-deposition canopy)
    postpro/                  ParaView figures: pv_dispersion_figures.py, pv_ground_slice.py, pv_mesh_inspect.py
    workflow/                 Snakemake sweeps (quasi-steady / transient / POD) -> receptor tables + report
    round/                    uploaded ABL template (reference only)
    results/                  per-run receptor tables + fields (regenerable)
```

Regenerable (safe to delete): `processor*/`, `postProcessing/`, `cases/results/`,
`constant/polyMesh/`, time directories.

---

## 10. Environment, gotchas & next steps

**Environment.** OpenFOAM ESI **v2512** (`module load OpenFOAM/v2512-foss-2025a`);
Python 3 with `numpy` (tools are otherwise stdlib-only). Mesh + solves run in
parallel on 96 ranks via SLURM.

**Gotchas already handled / to watch:**
- `blockMeshDict.m4` needs no Perl `Math::Trig` (inline `pi`).
- The `bottom` blockMesh patch disappears after snapping → `0/` fields list only the
  4 real patches.
- `make_street_patches.py` needs an **ASCII** `polyMesh`. If `reconstructParMesh`
  wrote binary, convert once with `foamFormatConvert` (controlDict `writeFormat
  ascii`) before carving.
- `createPatch`/field handling for `streets` on the real mesh is the one step not yet
  validated on the cluster; if `scalarTransportFoam` complains about `streets` on
  `U`/`phi`/`nut`, a one-line `zeroGradient` entry fixes it.
- Flow must start 1st-order then restart 2nd-order (`job_flow.sh`); fully 2nd-order
  from a cold start diverges (k/epsilon blow-up -> GAMG SIGFPE). ABL BCs need
  `libs (atmosphericModels)` in both flow and dispersion `controlDict`.

**Done since first draft:** receptor `site_name`s resolved · all four scenarios run · S3 mapping
validated · canopy as porous + finite-deposition zone (big domain) · 24 h→10-hour POD sweep with
daily mean/peak aggregation · **volume-average receptor metric** (breathing air) alongside the
surface areaAverage · spatial maps + ground-level concentration field · auto technical report.
Cluster gotchas fixed: ARM/x86 Snakemake interpreter mismatch, `--cluster`→cluster-generic
executor, UTF-8 locale for pvbatch, offscreen/`SkipZeroTime` for ParaView, decomposed-only
sweep scripts (no serial full-mesh decompose/reconstruct).

**Still open / could improve:** DT (constant vs nut/Sc_t) · mesh refinement vs cell count ·
Forchheimer `f` and canopy λ tuning from leaf-area data · fully-transient flow (pimpleFoam) ·
POD/PODI training on the saved snapshots.

---

## 11. Reporting, receptor metrics & post-processing

All analysis/reporting tools live in `cases/tools/` (Python: matplotlib, numpy, reportlab; stdlib
otherwise) and `cases/postpro/` (ParaView `pvbatch`). See **`cases/tools/README.md`** for the full
toolchain; the short version:

**Receptor tables → report.** Each POD dispersion run writes per-receptor concentrations; a
collector turns them into `receptors_long.csv` (`hour,scenario,pollutant,receptor,site,conc_ugm3`),
which feeds `make_report.py` → `receptor_summary.csv` + figures (grouped bars, %-change heatmap,
diurnal profiles) + `air_quality_report.pdf`; then `make_maps.py` (road-network + receptor maps)
and `make_techreport.py` build the polished `technical_report.pdf`.

**Two receptor metrics.** *Surface* `areaAverage` on the ROI surface (built into the dispersion
`system/receptors`), and *volume* `volAverage` over a box of breathing air above each receptor
(`make_receptor_zones.py` builds the cellZones + `volFieldValue` FO). Compute the volume metric
from finished runs with `run_receptor_volumes.sh` (postProcess on the `T_<poll>` snapshots at time 0,
using a `readFields` FO; `FIXHDR=0` skips the slow header fix) or, for new runs, during the solve via
`collect_receptor_volumes.sh` (wired into `Snakefile.podrun`). The two agree on scenario %-changes
within ~2 pp; **volume is the primary reported metric**, surface a robustness cross-check
(`make_techreport.py --compare-summary`).

**Concentration-field map.** `postpro/pv_ground_slice.py` renders a top-down ground-level
concentration slice (ParaView); `--extract` avoids OpenGL by resampling to a grid and drawing with
matplotlib, `--decomposed` reads `processor*/` without reconstruct. Snapshots live at **time 0**
(`--time 0`), fix the `T_<poll>` header, and on headless nodes use `--force-offscreen-rendering`
and a UTF-8 locale.

**Key result.** S1 ≈ −20 %, S2 ≈ −40 % uniformly at every receptor (linear response — a workflow
consistency check); the Metro Bus (S3) is spatially selective — ≈ −40 % at the Public Hospital
(the corridor wraps it) but only ≈ −5 % at Santos Simões (off-corridor).
