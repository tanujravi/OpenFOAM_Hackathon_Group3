# CLAUDE.md — Guimarães Air-Quality / Mobility-Scenario Hackathon

Standing rules for any session working in this folder — the short, always-loaded version.
The **authoritative, up-to-date sources are `PROJECT_MEMORY.md`** (running log of everything
built + every gotcha hit) **and the READMEs** (`README.md`, `cases/tools/README.md`,
`cases/workflow/README_podrun.md`, `cases/postpro/README.md`). Where this file disagrees with
those, they win — a few notes below were early assumptions the work later superseded (flagged).

> **Status: the pipeline is COMPLETE and has run end-to-end on the cluster.** All four scenarios
> (reference/S1/S2/S3), the 24 h→10 representative-hour POD sweep, receptor tables (surface **and**
> volume metrics), spatial maps, a ground-level concentration field, and an auto-generated technical
> report are done. Remaining work is tuning/interpretation/writing, not building.
> **New account / fresh session?** See "Resuming …" at the bottom and `NEW_ACCOUNT_PROMPT.md`.

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
- **Real 3-D terrain geometry** from OBJ surfaces → `snappyHexMesh` (blockMesh only builds
  the COST-732 background cylinder, not the terrain). The same mesh, BCs, solver settings and
  temporal strategy MUST be reused across reference + 3 scenarios; only emission scaling
  changes between scenarios.
- **Scenario definitions** (verify the emission mapping against the CSVs):
  - S1 = 20% gas-vehicle traffic removed (→ EV) ⇒ scale ALL segment emissions ×0.8.
  - S2 = 40% removed ⇒ ×0.6.
  - S3 = Metro Bus (Guimarães–Braga, N101) ⇒ apply `road_ids_reduction.txt`:
    ×0.5 on the 50%-list segments, ×0.7 on the 30%-list segments, others unchanged.
- **Objective metric is receptor concentration** at the `ROI.obj` locations, per pollutant,
  vs reference (absolute + % change). Implemented with TWO metrics: a surface `areaAverage`
  (dispersion `system/receptors`) and — now the **PRIMARY** reported metric — a **volume
  `volAverage` of the breathing air in a box above each receptor** (`cases/tools/make_receptor_zones.py`).
  They agree on scenario %-changes within ~2 pp. (An earlier draft said "not a breathing-plane
  average"; the volume-box average is the current, more defensible choice.)

## Environment (assumed already set up — do NOT install/rebuild)
- OpenFOAM (ESI/openfoam.com) sourced in any CFD shell (`snappyHexMesh`, solvers,
  `postProcess`, `decomposePar`/`reconstructPar`, `foamDictionary`, `mpirun`).
- Python with `numpy`, `pyyaml`, `snakemake` (+ `pulp<2.8`), `matplotlib`; and
  geometry/IO helpers (`trimesh`/`pyproj`/`shapely`) for the OBJ/CSV/geojson data.
- Snakemake runs a non-interactive shell: set `python_bin:` to the ABSOLUTE python
  that has the needed packages.

## OpenFOAM gotchas (current — supersede the earlier prototype notes)
- **Inlet: `atmBoundaryLayerInletVelocity` (k-ε ABL) IS used** on the all-round cylindrical
  `inletOutlet` patch (needs `libs (atmosphericModels)`). The old `exprFixedValue`/freestream
  approach is kept only as the `flowCaseOldBC` fallback. (Earlier this file said to avoid the
  ABL inlet — superseded.)
- **`atmNutkWallFunction`/`atmEpsilonWallFunction` DO work** (Terrain, z0=0.25 m); plain
  `nutkWallFunction`/`epsilonWallFunction` on Buildings. (Earlier "they error" note superseded.)
- ESI **v2512** fvOption constraint is `scalarFixedValueConstraint` (typed), not the bare
  `fixedValueConstraint`. The canopy scalar sink is now a finite `scalarSemiImplicitSource` (−λT),
  not the perfect-sink (T=0) trial.
- Snapshot post-processing: `postProcess` does NOT auto-read fields → use a `readFields` FO; POD
  snapshots live at **time 0** as `T_<poll>` (header still says `T`). pvbatch on headless nodes
  needs a UTF-8 locale + `--force-offscreen-rendering` (or `--extract`, GL-free).
- **Sweep scripts are decomposed-only** (no serial full-mesh `decomposePar`/`reconstructPar`):
  symlink the pre-decomposed mesh, `decomposePar -fields`, `redistributePar -reconstruct -parallel`.
- Snakemake ≥ 8 dropped `--cluster` → use the **cluster-generic** executor; run the controller on
  an **aarch64** node (its interpreter is re-invoked on the compute nodes).
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

## Tooling (already built — reuse, don't reinvent)
The flow→dispersion chain, receptor sampling (surface + volume), the sweep/POD orchestration and
the reporting toolchain are already built here — `cases/`, `cases/tools/`, `cases/workflow/`,
`cases/postpro/`; start from `cases/tools/README.md`. (The original prototype lived at
`D:\OPWHackhaton\ofTraficTest`; no longer needed and may be absent on other machines.) Never reuse
`pod.npz`/`pod_rom.pkl`/`snapshots/` across meshes or decompositions.

## Working conventions
- Keep reusable Python/Snakemake tooling separate from the OpenFOAM case tree, and
  separate from this provided-data folder.
- Treat `runs_pod*/`, `snapshots/`, `processor*/`, `postProcessing/`, `results*/`, `*.npz`,
  `*.pkl`, `__pycache__/`, `.snakemake/`, `constant/polyMesh/` as regenerable.
- Don't expose internal session paths to the user; refer to "the folder you selected".

## Resuming in a new Cowork session or a different Claude account
This project is self-contained in this folder. To continue in a fresh Cowork session (any account):
1. Open Cowork, **select this folder** (`referenceCase`) — plus `results_pod/` if you keep the
   compiled results there. Same machine: just select it. Different machine: `git clone`/copy the
   folder but SKIP the regenerable heavy dirs (`runs_pod*/`, `processor*/`, `postProcessing/`,
   `snapshots/`, `.snakemake/`, `constant/polyMesh/`, `*.npz/.pkl`) — they rebuild on the cluster.
2. Have the new session **read first**: `PROJECT_MEMORY.md`, this file, `README.md`,
   `cases/tools/README.md`, `cases/workflow/README_podrun.md`. That is the full state.
3. The CFD runs on the HPC cluster (Deucalion) over SSH/tmux, NOT through Cowork — Cowork edits this
   local repo, which you git-sync to the cluster. This project needs **no MCP connectors**.
4. **Environment knobs to check per account/allocation:**
   - `cases/workflow/run_podrun.sh`: `ACCOUNT` (SLURM allocation), `ARMPART` (ARM partition).
   - `cases/workflow/config_pod.yaml`: `python_bin` (ABSOLUTE aarch64 numpy python), `nprocs`.
   - Cluster modules: `OpenFOAM/v2512-foss-2025a`; an aarch64 `snakemake` +
     `snakemake-executor-plugin-cluster-generic`; ParaView `5.11.2-foss-2023a`; `reportlab`.
5. A ready-to-paste bootstrap prompt is in **`NEW_ACCOUNT_PROMPT.md`**.
