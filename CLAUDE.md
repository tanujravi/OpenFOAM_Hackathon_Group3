# CLAUDE.md — Guimarães Air-Quality / Mobility-Scenario Hackathon

Standing rules for any session working in this folder. Read `PROJECT_HANDOFF.md`
for the full picture; this file is the short, always-loaded version.

## What this project is
OpenFOAM Hackathon Challenge (OFW21, Guimarães, Portugal). Quantify how four
sustainable-mobility scenarios change **air quality (CO and NOx)** at four
sensitive receptors, relative to the provided reference case. Receptors
(`ROI/ROI.obj`): Martins Sarmento HS, Francisco de Holanda HS, Santos Simões HS,
Public Hospital. This is a **scenario comparison**, not a continuous optimisation.

## Hard dates (Portugal time, WEST)
- Deliverables submitted: **2026-07-02, 14:00**.
- Final presentation (15 min + 5 min Q&A): **afternoon of 2026-07-03**, at OFW21.

## Assessment weights (optimise effort against these)
Workflow/tool quality 30% · correct scenario implementation 25% · receptor
air-quality assessment 20% · presentation clarity 15% · post-processing &
visualisation 10%. A robust, reproducible workflow is worth more than any single
result.

## This folder = the PROVIDED reference data (treat as read-only inputs)
- `terrain_and_buildings/` — `Mesh_Terrain.obj` (6.3×6.3 km, z 143–613 m, real
  relief) + `Mesh_Buildings_0..5` (ROI buildings) + `Mesh_Buildings_6` (far field).
- `canopy/merged.obj` — vegetation/canopy surface (porous-media / momentum-sink
  candidate; do not mesh as a solid wall).
- `bigger_terrain_results/city4CFD/` — larger 25×25 km domain incl. vegetation,
  produced with city4CFD; alternative/extended domain.
- `traffic/` — per-segment hourly emission factors `emission_factor_per_segment_{CO,NOx}.csv`
  (196 segments × 24 hourly columns), road geometry `road_segments.csv` /
  `snapped_road_segments.csv` (LINESTRING Z, snapped to terrain), geojson + html previews.
- `wind_data/wind_velocity_time.csv` — hourly horizontal wind as (u, v) components,
  24 bins 07:00→07:00, spatially uniform reference for the ABL inlet.
- `road_ids_reduction.txt` — TWO lists: a **50% reduction** set (19 road IDs) and
  a **30% reduction** set (28 road IDs). See Scenario 3 below — do not assume a
  single flat 50%.

## Project-specific rules (different from the ofTraficTest prototype)
- **Two pollutants** (CO, NOx) → two passive scalars; keep separate, report each
  at every receptor.
- **Time-varying** inputs: emission and wind are hourly over a full day. Choose
  and document a temporal strategy (24 quasi-steady hourly states vs a transient
  run) and keep it IDENTICAL across all four scenarios so comparisons are fair.
- **Wind direction changes hour to hour** (u and v both vary, sign flips) — the
  domain/BC setup must accept inflow from varying directions (rotate inflow patch
  or use all-round inlet handling); a single fixed inlet face is not enough.
- **Real 3-D terrain geometry** from OBJ surfaces → `snappyHexMesh` (or
  equivalent), NOT `blockMesh`. The same mesh, BCs, solver settings, and temporal
  strategy MUST be reused across reference + 3 scenarios; only emission scaling
  changes between scenarios.
- **Scenario definitions** (verify the emission mapping against the CSVs):
  - S1 = 20% gas-vehicle traffic removed (→ EV) ⇒ scale ALL segment emissions ×0.8.
  - S2 = 40% removed ⇒ ×0.6.
  - S3 = Metro Bus (Guimarães–Braga, N101) ⇒ apply `road_ids_reduction.txt`:
    ×0.5 on the 50%-list segments, ×0.7 on the 30%-list segments, others unchanged.
- **Objective metric is receptor concentration**, sampled at the `ROI.obj`
  locations (probes / surfaceFieldValue), reported per pollutant and compared to
  the reference (absolute and % change). NOT the prototype's breathing-plane area
  average — do not copy that objective.

## Environment (assumed already set up — do NOT install/rebuild)
- OpenFOAM (ESI/openfoam.com) sourced in any CFD shell (`snappyHexMesh`, solvers,
  `postProcess`, `decomposePar`/`reconstructPar`, `foamDictionary`, `mpirun`).
- Python with `numpy`, `pyyaml`, `snakemake` (+ `pulp<2.8`), `matplotlib`; and
  geometry/IO helpers (`trimesh`/`pyproj`/`shapely`) for the OBJ/CSV/geojson data.
- Snakemake runs a non-interactive shell: set `python_bin:` to the ABSOLUTE python
  that has the needed packages.

## Carried-over OpenFOAM gotchas (from the prototype — keep applying)
- Inlet wind via a **phi-free Dirichlet BC** (`exprFixedValue`), not
  `codedFixedValue` (recompiles per fresh case) nor `atmBoundaryLayerInletVelocity`
  (needs the face-flux field `phi`).
- Smooth `nutkWallFunction` on walls unless the atmospheric library is confirmed
  (`nutkAtmRoughWallFunction` threw "Unknown patchField type").
- `foamToNumpyInternal` runs only on **decomposed (parallel)** cases; its dict must
  **quote** an absolute `dataDir` (unquoted leading `/` ⇒ parser error).
- Any POD/ROM step needs an **identical decomposition across snapshots** (fixed
  `decomposeParDict`, same `--np`) or cell ordering misaligns.
- Write float configs as `1.0e+9`, not `1.0e9` (PyYAML).
- Path-resolving tools (e.g. `validate_rom.py`) resolve `--case`/`--precursor`/
  `--runner` relative to the **`--config` file's folder** — always pass `--config`.

## ROM / optimisation caveats
- A POD-ROM is OPTIONAL here (no continuous design space; 4-scenario comparison).
  It only earns its place to make the 24-hour temporal sweep cheap. If used,
  **re-derive everything from this case's snapshots** and re-test the prototype
  finding (objective ≈ direct GP on design vars) — that was specific to the old
  thin-receptor metric and may not hold.
- **Never reuse `pod.npz` / `pod_rom.pkl` / `snapshots/` across cases** — they are
  bound to one mesh and decomposition.

## Reuse, don't reinvent
The prototype at `D:\OPWHackhaton\ofTraficTest` (`pitzDaily/` + `numpyToFoam-main/`)
has a working flow→dispersion chain, the numpy exporters, the POD-ROM toolchain,
and the Snakemake orchestration. Copy and adapt the **tooling**; rebuild all
**case files and ROM artefacts** from scratch. See `PROJECT_HANDOFF.md` §"Reuse map".

## Working conventions
- Keep reusable Python/Snakemake tooling separate from the OpenFOAM case tree, and
  separate from this provided-data folder.
- Treat `snapshots/`, `processor*/`, `postProcessing/`, `*.npz`, `*.pkl`,
  `__pycache__/`, `.snakemake/` as regenerable.
- Don't expose internal session paths to the user; refer to "the folder you selected".
