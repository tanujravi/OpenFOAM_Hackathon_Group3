# PROJECT MEMORY — Guimarães Air-Quality / Mobility CFD (OFW21)

Reconciled working memory, written 2026-06-30 from the **READMEs (authoritative)** and
cross-checked against `CLAUDE.md` (now refreshed). This is a **running log** of everything
built and every gotcha hit across the session — read it in full when resuming. Some entries
are specific to the Cowork environment they were hit in (bash-mount lag, read-only mount,
outputs paths) and may not apply identically elsewhere; the CFD/HPC gotchas do. **Resuming in a
new Cowork session or a different Claude account: see `CLAUDE.md` → "Resuming …" and
`NEW_ACCOUNT_PROMPT.md`.**

---

## 0. The task (unchanged, both sources agree)
Quantify how four sustainable-mobility scenarios change **CO and NOx** at **four
sensitive receptors**, vs a reference case, on Guimarães' real 3-D terrain.
Scenario *comparison*, not optimisation. Deliverables due **2026-07-02 14:00 WEST**;
talk (15+5 min) **afternoon of 2026-07-03**. Weights: workflow/tool quality 30% ·
scenario implementation 25% · receptor assessment 20% · presentation 15% · post-pro 10%.

**Ricardo's current focus (from README notes):** get the **reference case** working
first; ignore the scenario scaling and the full 24h orchestration (§8) for now.

---

## 1. WHERE CLAUDE.md IS STALE (README is correct)

1. **Inlet velocity BC — REVERSED.** CLAUDE.md says use a phi-free `exprFixedValue`
   and *avoid* `atmBoundaryLayerInletVelocity` (needs `phi`). The current `flowCase`
   **does use `atmBoundaryLayerInletVelocity`** on a cylindrical all-round `inletOutlet`
   patch, via the `atmosphericModels` library (`libs (atmosphericModels);` in
   controlDict). The old freestream approach is now the **fallback** in `flowCaseOldBC`.
   ⚠️ Ricardo flagged "check if this velocity BC makes sense" — open question.
2. **Wall functions — atm library now CONFIRMED working.** CLAUDE.md says
   `atmNutkWallFunction` threw "Unknown patchField type", use plain `nutkWallFunction`.
   Current setup uses **`atmNutkWallFunction` on Terrain** (z0 = 0.25 m) and
   `nutkWallFunction` on Buildings; `atmEpsilonWallFunction` on Terrain similarly.
3. **Turbulence model.** Current `flowCase` = **k-ε** (neutral-ABL, Hargreaves & Wright).
   `flowCaseOldBC` fallback = **k-ω SST** + freestream.
4. **"snappyHexMesh NOT blockMesh"** is misleading. Background domain **is** a
   `blockMesh` (m4-generated COST732 **cylinder**); terrain + buildings are then snapped
   with `snappyHexMesh`. So blockMesh is used for the background block only.
5. **Receptor metric.** CLAUDE.md says use probes/`surfaceFieldValue` at ROI points and
   *not* an area average. Current code uses **`areaAverage(T)` via `surfaceFieldValue`**
   over each receptor surface. ⚠️ Ricardo note: it "should probably be, for each street,
   an area average of the pollution of the air **above** it" — open design question.
6. **Receptor names are now KNOWN** (CLAUDE.md/README said `TBD`). From the existing
   `h1_reference` result table:
   - receptor1 = **Hospital da Senhora da Oliveira** (Public Hospital), UTM (−14414.0, 197031.4)
   - receptor2 = **E.S. Francisco de Holanda**, UTM (−12879.1, 197339.1)
   - receptor3 = **E.S. Martins Sarmento**, UTM (−13685.7, 197293.2)
   - receptor4 = **E.B./S. de Santos Simões**, UTM (−11592.8, 198070.1)
7. **`canopy/merged.obj` is NOT in this folder** (1.5 GB, not uploaded — Ricardo note).
   CLAUDE.md treats it as present. The small domain does not mesh canopy anyway; canopy
   only matters on the big domain (porous zone).
8. **`PROJECT_HANDOFF.md` referenced by CLAUDE.md does not exist** in this folder.
9. **OpenFOAM version is specific:** ESI **v2512** (`module load OpenFOAM/v2512-foss-2025a`).

---

## 2. WHERE BOTH AGREE (firm facts)
- **Two pollutants** CO + NOx → two passive scalars, solved **separately**, never
  summed, reported per receptor.
- **Scenario scaling:** reference ×1.0 · **S1 ×0.8** (20%→EV) · **S2 ×0.6** (40%→EV) ·
  **S3** Metro Bus N101: **×0.5** on the 19-ID 50%-list, **×0.7** on the 28-ID 30%-list,
  ×1.0 elsewhere (lists in `road_ids_reduction.txt`, the two tiers don't overlap).
- **Time-varying inputs:** 24 hourly wind `(u,v)` bins (07:00→07:00) + 196-segment
  hourly emission factors. Wind direction flips hour to hour → all-round inlet handles it.
- Pick ONE temporal strategy and keep it identical across all four scenarios (fairness).
- **Mesh is built once and reused** across all hours/scenarios; only emission scaling
  changes between scenarios.
- **Recentred frame** = pure translation (no rotation). Small domain:
  X0 = −13152.617, Y0 = 197434.738, Z0 = 142.676. Big domain: same X/Y, Z0 = 74.29.
  Inverse in `geo/transform.json`. Wind vectors and emission factors are NOT transformed.
- Emission CSV row order == segment order == 0-based road ID. **Units = g/h.**

---

## 3. PIPELINE (flow → dispersion → receptors)

**Stage 0 — Mesh** (`cases/flowCase/runallgeo.sh`, SLURM):
`surfaceFeatureExtract → blockMesh (m4 cylinder, R=3000 m) → decomposePar →
snappyHexMesh -parallel → reconstructParMesh → checkMesh`. ~**1.71 M cells**.
The flat `bottom` floor is carved away by snapping → live mesh has **4 patches**:
`inletOutlet` (cylinder side), `top` (symmetry), `Terrain`, `Buildings` (walls).
m4 defines `pi` inline (no Perl `Math::Trig`). checkMesh: max non-ortho ~70–72°,
skewness ~5 (normal for urban terrain) → `nNonOrthogonalCorrectors 2`.

**Stage 1 — Wind precursor** (`cases/flowCase`, `simpleFoam`, k-ε ABL):
- BCs: `U` = `atmBoundaryLayerInletVelocity`; `p` = `freestreamPressure`;
  `k`/`epsilon` = `atmBoundaryLayerInletK/Epsilon`; `nut` = `calculated`. Walls noSlip /
  atm wall functions; `top` symmetry. Profile params in `0/include/ABLConditions`.
- Per-hour wind: `tools/set_wind.py --case . --hour H` → `Uref=|(u,v)|`,
  `angle=atan2(v,u)`. (For the legacy `0/U` vector case it writes `(u,v,0)` instead.)
- **Two-stage solve** (fully 2nd-order from cold diverges → k/ε blow-up → GAMG SIGFPE):
  `potentialFoam` init → `simpleFoam` with `fvSchemes_1storder` (upwind warm-up) →
  restart from latestTime with `fvSchemes_2ndorder`. Driven by `job_flow.sh`.
  Plain SIMPLE (`consistent no`), under-relaxation, `nNonOrthogonalCorrectors 2`.
- Output: frozen `U`, `phi`, `nut`.

**Stage 1.5 — Street patch carved in flowCase BEFORE the solve** (§6.1):
Roads aren't in the mesh; carve them out of `Terrain` as a single `streets` wall patch.
`foamFormatConvert`→ASCII if needed → `tools/make_street_patches.py` (faces within
`--half-width`, default 6 m, of a road polyline; tags nearest segment; force-assigns
starved segments so **all 196** are represented) → `createPatch -overwrite` →
`tools/add_streets_bc.py` (clones `Terrain` BC entry into `streets` in uniform 0/ fields).
Must carve BEFORE solving so frozen fields are written on the final Terrain+streets mesh
(carving after shrinks `Terrain` → boundary-list size mismatch crash). Produces
`geo/streets_face_segments.csv` (face→segment+area), reused downstream.

**Stage 2 — Dispersion** (`cases/dispersionCase`, `scalarTransportFoam`):
Copies in the **already-split** mesh + frozen `U`/`phi`/`nut` + `streets_face_segments.csv`
(never carves). Solves one scalar `T` per run, dims **kg/m³** (×1e9 = µg/m³), constant
`DT ≈ 1 m²/s`. controlDict loads `atmosphericModels` (copied `nut` carries the atm wall
fn). Emissions: `tools/map_emissions.py` (scenario scaling) → `tools/set_emissions.py`
writes the `streets` block in `0/T` as a **non-uniform `fixedGradient`**:
`gradient_f = (E_s · unit_scale)/A_s / DT`, `unit_scale = 1/3.6e6` (g/h→kg/s). Wall
balance `DT·grad·area = segment rate [kg/s]`. ⚠️ This streets-patch handling is the one
step **not yet validated on the cluster**.

**Stage 3 — Receptors** (`system/receptors`):
4 × `surfaceFieldValue` `areaAverage(T)` over `constant/triSurface/receptor{1..4}.obj`
(from `tools/split_roi.py`), run inside the solver → `postProcessing/receptorN/...`.
`tools/receptor_table.py` → `results/<run>/receptor_table.csv` in µg/m³, with
absolute + **% change vs reference** when `--reference` is passed.

**Driver:** `flowCase/job_flow.sh` (carve+flow), then from `cases/`:
`HOUR=0 SCENARIO=reference sbatch run_single_hour.sh` (defaults POLLUTANTS="CO NOx",
NPROCS=128, DT=1.0). Outputs → `cases/results/h<HOUR>_<SCENARIO>/`.

**Existing result (`h1_reference`, sanity baseline):** CO 7.3–15.8 µg/m³,
NOx 10.3–23.0 µg/m³ across the 4 receptors; Martins Sarmento (receptor3) highest.

---

## 4. BIG DOMAIN (`flowCaseBig` / `dispersionCaseBig`)
25.2 × 25.2 km city4CFD terrain, same 196 roads + 4 receptors (directly comparable).
Domain-influence study. Differences: cylinder R=12500, floor z0=−150, **`bottom`
patch is KEPT** (slip — cylinder reaches past terrain at far edges). ~30–45 M cells,
ROI refined (~4.7 m streets, ~2.3 m buildings), far terrain coarse (~37.5 m). Buildings
auto-cleaned (1247 dup/degenerate tris) via `clean_surface.py`. **Vegetation = porous
canopy zone** (Darcy-Forchheimer momentum sink, `constant/fvOptions` +
`system/topoSetDict` `vegetationZone`), or optionally a `wall` — choose with
`tools/set_vegetation_model.py` BEFORE meshing (different meshes). Dispersion pins
`T=0` in the veg zone (perfect-uptake trial). Meshing on **ARM** (`--mem=0`,
~12 ranks/node, `redistributePar -reconstruct`, no serial reconstruct). Flow on x86
(4 nodes × 96 ranks).

---

## 5. 24h SWEEP & POD (`cases/workflow`, Snakemake) — WIP, deferred for now
- **Quasi-steady** (`Snakefile`, **219** jobs): 24 steady flows; each hour's scalar
  solved to steady state independently. 24 flow + 192 dispersion solves.
- **Transient** (`Snakefile.transient`, **35** jobs): chained 24h day, pollutant
  carried over, flow piecewise-steady.
- **POD run** (`README_podrun.md`, `Snakefile.podrun`): decomposed end-to-end (no
  reconstruct → no ARM OOM), one sbatch per hour/pollutant, `select_hours.py` maximin.
  POD/PODI training itself is NOT included. ROM is OPTIONAL here (CLAUDE.md caveat).
  **Full mechanics in §9 below.**
- `config.yaml`: set `python_bin` to an ABSOLUTE python with numpy; `nprocs` must equal
  the mesh decomposition; `DT` = scalar diffusivity. Outputs: `hourly_long.csv`,
  `receptor_daily_summary.csv`, `scenario_comparison.csv`.

---

## 6. POST-PROCESSING (`cases/postpro`, ParaView 6.0.1 `pvbatch`)
First fix `T_CO`/`T_NOx` FoamFile `object` header (still says `T`) via sed. Then
`run_pv_figures.sh <case> <label>` → volume render, isosurfaces, per-receptor surfaces,
optional z-slice (all ×1e9 → µg/m³). `pv_mesh_inspect.py` inspects the **decomposed**
big mesh by `cellLevel` without reconstructing.

---

## 7. TOOLS (`cases/tools/`)
`preprocess_geometry.py` (recenter+merge buildings 0–5, exclude _6; `--vegetation` for
canopy) · `set_wind.py` · `make_street_patches.py` · `add_streets_bc.py` ·
`map_emissions.py` · `set_emissions.py` · `split_roi.py` · `split_inlet_outlet.py` ·
`receptor_table.py` · `collect_receptors.py` · `aggregate_day.py` · `select_hours.py` ·
`clean_surface.py` · `set_vegetation_model.py`. Tools are otherwise stdlib + numpy.

---

## 8. PERSISTENT GOTCHAS
- Mesh must be **ASCII** for `make_street_patches.py` (`foamFormatConvert` if binary).
- `streets` patch on the real mesh is the main unvalidated step; if `scalarTransportFoam`
  complains about `streets` on `U/phi/nut`, add a one-line `zeroGradient` entry.
- Flow must warm up 1st-order then restart 2nd-order; ABL BCs need
  `libs (atmosphericModels)` in BOTH flow and dispersion controlDict.
- Big-mesh: avoid serial `reconstructParMesh` (OOM) — use `redistributePar -reconstruct`.
- Keep flow + dispersion on the SAME decomposition for the big domain.
- Treat `processor*/`, `postProcessing/`, `results/`, `polyMesh/`, `*.npz/.pkl`,
  `snapshots/`, `__pycache__/`, `.snakemake/` as regenerable.
- Don't expose internal session paths to the user; say "the folder you selected".
- **Snakemake `--cluster` cross-arch trap (HIT 2026-06-30).** Login node is **x86_64**,
  compute is **ARM (aarch64)**. In `--cluster` mode Snakemake writes a per-job script
  that **re-invokes its own interpreter** (`sys.executable -m snakemake …`) on the
  compute node. If you launch `run_podrun.sh` on the x86 login with an x86 EasyBuild
  Snakemake, that hardcoded path (`/eb/x86_64/software/Python/.../bin/python`) does NOT
  exist on ARM nodes → slurm_script fails: `… /bin/python: No such file or directory`.
  **Fix:** run the Snakemake controller itself in an ARM context (interactive `salloc`
  on the ARM partition, or an ARM login node, kept alive in tmux/screen) with an
  **aarch64-native** Snakemake (ARM module, or a venv built from an ARM `python3`), so
  `sys.executable` resolves on the compute nodes. This is SEPARATE from `config_pod.yaml`
  `python_bin:`, which must ALSO be an aarch64 numpy python (tools run on ARM too) —
  not the x86 `/eb/x86_64/...` path; `/usr/bin/python3` is native per-arch and works if
  it has numpy. Caveat: the interactive approach needs compute→controller `sbatch` to be
  allowed; if not, drive from an ARM login node.
- **Snakemake 9 removed `--cluster` (HIT 2026-06-30, after the arch fix).** On Deucalion
  the ARM module is **snakemake/9.14.0-foss-2025a**. `--cluster "sbatch …"` was removed
  from core in v8; on 9.14 the submitted job re-enters the scheduler as a non-main
  process and crashes with `assert self.workflow.is_main_process` → `AssertionError`
  (traceback in `job_scheduler.py`). **Fix applied in `run_podrun.sh`:** submit via the
  **cluster-generic executor** — `--executor cluster-generic --cluster-generic-submit-cmd
  "sbatch … --parsable …"` (the `--cluster "X"` → `--executor cluster-generic
  --cluster-generic-submit-cmd "X"` swap). Needs the plugin
  (`pip install snakemake-executor-plugin-cluster-generic`; min snakemake 8.6) and
  `sbatch --parsable` so only the job ID is returned. **Do NOT use `--executor slurm`
  here:** it wraps each job in its own `srun`, which nests inside the `srun … -parallel`
  calls already in `run_flow_hour_decomp.sh` / `run_disp_decomp.sh` (step-overlap), and
  `--ntasks-per-node` isn't a first-class slurm-executor resource. cluster-generic
  preserves the existing design: each `sbatch` grabs the 8×48 allocation and the job
  script's own `srun` uses all 384 ranks. Optional `--cluster-generic-status-cmd` adds
  robust SLURM status polling.

---

## 9. POD-RUN DEEP DIVE (`cases/workflow`, `Snakefile.podrun` + `run_podrun.sh`)

**Purpose.** Generate decomposed `T_CO`/`T_NOx` snapshots for a chosen subset of hours
(default **10 of 24**) on the **big domain**, to feed a POD/PODI **later**. POD training
is deliberately NOT part of this workflow — it only produces the snapshot set.

**Core design = decomposed end-to-end, never reconstruct.** The ~40 M-cell big mesh is
frozen ONCE in a decomposition (e.g. **384 ranks = 8 nodes × 48**). Every run shares
that one decomposed mesh by **symlink** and only `decomposePar -fields` (scatters field
files onto the existing addressing — no `scotch`, no geometric re-decompose, no serial
reconstruct → no ARM OOM). Each hour's flow and each (hour,pollutant) dispersion lives
in its **own folder** under `runs_pod/`, so they're independent SLURM jobs: parallel,
no clobbering, pending-safe.

**Launcher `run_podrun.sh`** (run from `cases/workflow/`):
`SMK_JOBS=20 ARMPART=<arm-part> bash run_podrun.sh`.
1. `module load OpenFOAM/v2512-foss-2025a`; `mkdir -p logs`.
2. **Vegetation-model preflight** (aborts on mismatch): reads `mesh_case`/`disp_case`
   from `config_pod.yaml`; asserts their `.veg_model` markers agree; then verifies the
   **frozen mesh actually matches** — `wall` ⇒ a `Vegetation` patch must exist in
   `…/constant/polyMesh/boundary`; `porous` ⇒ a `vegetationZone` must exist in
   `…/constant/polyMesh/cellZones`. Prevents running porous `fvOptions` on a wall mesh.
3. Defaults: `SMK_JOBS=20`, `ARMPART=normal-arm`, `ACCOUNT=f202500001hpcvlabepicurex`
   (hardcoded HPC allocation — change for another account).
4. Runs `snakemake -s Snakefile.podrun --jobs $SMK_JOBS --latency-wait 120 --keep-going
   --cluster "sbatch --account=… --partition=$ARMPART --nodes=8 --ntasks-per-node=48
   --mem=0 --time=06:00:00 …"`. So **each rule instance = one 384-rank sbatch**;
   `SMK_JOBS` caps concurrent submissions (rest queue). Snakemake ≥ 8: swap `--cluster`
   for `--executor slurm` / a SLURM profile.

**`Snakefile.podrun`** (self-contained — does NOT use `rules/common.smk`):
- Globals from `config_pod.yaml`: `MASTER=../flowCaseBig`, `DISPSRC=../dispersionCaseBig`,
  `TOOLS=../tools`, `WORK=runs_pod`, `RES=results_pod`, `PY=python_bin`, `NP=nprocs`,
  `DT`, `SCEN=reference`, `IT2=flow_2ndorder_iters`, `POLL=[CO, NOx]`.
- `HOURS` from `selected_hours.txt` (`"0,1,3,5,8,9,11,14,17,23"`; strips a `HOURS=`
  prefix), else config `hours`.
- DAG: `rule flow_hour[h]` → `FLOW_DONE`; `rule disp[h,poll]` (depends ONLY on its own
  hour's `FLOW_DONE`) → `DISP_DONE`; `rule snapshots` gathers all **HOURS×POLL = 10×2 =
  20** `DISP_DONE` and writes `results_pod/snapshots.txt` listing decomposed field paths
  `processor*/0/T_<poll>`. **No POD computed here.**

**`scripts/run_flow_hour_decomp.sh`** (HOUR MASTER TOOLS WORK NP IT2 PY):
requires MASTER both **decomposed** (`processor0/constant/polyMesh`) **and serial**
(`constant/polyMesh/points` — needed by `decomposePar -fields`). Builds `runs_pod/flow/
h<H>/`: copies `system/`, `0/`, `constant/{transportProperties,turbulenceProperties,
fvOptions}`; **symlinks** the serial polyMesh and every `processor*/constant`;
`set_wind.py --hour H`; sets `numberOfSubdomains=NP`; `decomposePar -fields -force`;
then the **two-stage solve** — `fvSchemes_1storder` → `potentialFoam` (‖ true) +
`simpleFoam` warm-up, then `fvSchemes_2ndorder`, `endTime = latest+IT2`, restart
`simpleFoam`. Output: decomposed frozen `U/phi/nut` at latest time.

**`scripts/run_disp_decomp.sh`** (HOUR POLL MASTER DISPSRC TOOLS WORK NP DT SCEN PY):
requires the hour's flow converged (`FL = latestTime ≠ 0`). Builds `runs_pod/disp/h<H>/
<POLL>/`: copies disp `system/`, `constant/triSurface` (receptors), `0/`,
`constant/{transportProperties,fvOptions}`, and `streets_face_segments.csv` from
`MASTER/geo`; symlinks serial polyMesh + each `processor*/constant`; copies the frozen
`U/phi/nut` from the flow's `processor*/<FL>/` into `processor*/0/`; `set_emissions.py
--pollutant POLL --hour H --scenario SCEN --DT`; `decomposePar -fields -force` (only
`0/T`); `srun scalarTransportFoam -parallel`; then **stashes** the converged
`processor*/<dl>/T` → `processor*/0/T_<POLL>` so all pollutants/hours coexist
decomposed. Receptor numbers come from the parallel `surfaceFieldValue` FOs (no
reconstruct needed).

**Hard constraints / risks to remember:**
- `nprocs` (384) **MUST equal** the frozen mesh's decomposition, or addressing
  misaligns. `config_pod.yaml` and the sbatch `--nodes×--ntasks-per-node` must agree.
- MASTER needs BOTH a serial mesh and `processor*/constant` present.
- `python_bin` must be an **absolute** numpy python (Snakemake shell sees no conda).
- `select_hours.py --n N` picks hours by maximin over wind speed/direction + CO/NOx
  totals; rerun to change N (then update `selected_hours.txt`).
- This path runs on the **big/ARM** cases with the porous (or wall) vegetation model
  chosen via `set_vegetation_model.py` **before** meshing.

---

## 10. ARM-SAFE SWEEP SCRIPTS (converted 2026-06-30)

The quasi-steady (`Snakefile`) and transient (`Snakefile.transient`) sweeps used
**full serial mesh** `decomposePar -force` + `reconstructPar`, which OOMs on the
~40 M-cell big mesh on ARM. All three backing scripts were rewritten so the **mesh is
never decomposed/reconstructed in serial** — only FIELDS move on the pre-decomposed,
symlinked mesh (matching the POD `_decomp` scripts):
- `scripts/run_flow_hour.sh` — `PAR=true`: symlink `$FLOW/processor*/constant`,
  `decomposePar -fields` (no scotch), 2-stage `simpleFoam -parallel`, then
  `redistributePar -reconstruct -latestTime -parallel` to write serial `frozen/{U,phi,nut}`
  (NEVER serial `reconstructPar`). `PAR=false` = pure serial, no decompose.
- `scripts/run_disp.sh` — `PAR=true`: symlink mesh, `decomposePar -fields` only
  (`0/{U,phi,nut,T}`), `scalarTransportFoam -parallel`; receptors come from the parallel
  `surfaceFieldValue` FOs (postProcessing at case root) → **no reconstruct at all**.
- `scripts/run_transient_day.sh` — per hour: `decomposePar -fields -time t0` then
  `redistributePar -reconstruct -latestTime -parallel` for the carried-over T (NEVER
  serial `reconstructPar`); mesh symlinked once.
- Requirements added (guarded with `die()`): `$FLOW` must be **pre-decomposed**
  (`processor*/constant`) AND have a **serial mesh** (`constant/polyMesh/points`, needed
  by `decomposePar -fields`); `NP` must equal the processor-dir count. The `frozen/U`
  Snakemake output contract is preserved, so the Snakefiles + `common.smk` are unchanged.
- Allowed ops recap: `decomposePar -fields` (field scatter, OK) and
  `redistributePar -reconstruct -parallel` (parallel field gather, OK, per big README).
  Forbidden: `decomposePar` without `-fields` (builds mesh decomp via scotch) and
  serial `reconstructPar`/`reconstructParMesh`. The `_decomp` POD scripts were already
  compliant.

## 12. SCENARIO REPORT TOOL (`cases/tools/make_report.py`, added 2026-06-30)

Generates the air-quality scenario report the Guidelines ask for (PDF deliverable +
quantitative receptor comparison). Reads the four scenario runs, computes per-receptor /
per-pollutant **mean & peak over the sampled hours**, **% change vs reference** for
S1/S2/S3, and writes: `receptor_summary.csv`, `scenario_comparison.csv`,
`figs/{bar_mean_<poll>,heatmap_pct,diurnal_<poll>}.png`, and a multi-page
`air_quality_report.pdf` (auto findings + tables + figures). Dependency-light
(matplotlib + numpy + stdlib). Each `--run LABEL=PATH` accepts either a
`receptors_long.csv`/`receptors.csv` OR a run dir (scans
`disp/h*/<poll>/postProcessing/<receptor>/*/surfaceFieldValue.dat`, needs
`--triSurface .../constant/triSurface`). Validated on synthetic data: S1≈−20%, S2≈−40%
uniform (linearity check), S3 heterogeneous (largest at the N101-adjacent receptor).
Guidelines framing baked in: focus on the 4 named receptors, relative comparison is the
robust deliverable; NOx plots show EU/WHO NO2 context lines with a caveat (modelled NOx
≠ ambient NO2, no background). Example run:
`python3 tools/make_report.py --run reference=workflow/results_pod/receptors_long.csv
--run S1=workflow_S1/results_pod_S1/receptors_long.csv --run S2=... --run S3=... --out report`.

## 13. REPORTING / DELIVERABLE PIPELINE (added 2026-07-01)

Reproducible chain that turns the four scenario runs into the PDF deliverable (all
paths via CLI, no hard-coding). Dependency-light: matplotlib, numpy, reportlab, stdlib.
1. **`tools/make_report.py`** — receptor tables + `figs/` (bars, %-change heatmap,
   diurnal) + `air_quality_report.pdf` (its `text_page` now wraps/paginates, so the
   first page no longer truncates).
2. **`tools/make_maps.py`** — spatial maps from provided data + results:
   `map_pollution.png` (road network, width ∝ pollutant emission, S3 corridor in blue,
   receptors coloured by concentration) and `map_scenarios.png` (receptors per scenario,
   shared scale). Args: `--repo --disp <dispersionCaseBig> --report --pollutant --out`.
   Overlay is exact — receptor `centroid_utm` (receptors.json) shares the road geojson
   frame.
3. **`postpro/pv_ground_slice.py`** — ParaView **pvbatch** top-down ground-level
   concentration-field map (horizontal slice at `--z`, log colour, receptors overlaid) →
   `<label>_<field>_ground.png`. **The POD run stashes the converged field into TIME 0 as
   `processor*/0/T_<POLL>`** (run_disp_decomp.sh line 35: `mv processor*/$dl/T →
   processor*/0/T_<POLL>`), NOT the latest time dir — so read `--time 0` (now the
   script default) and reconstruct that time (`redistributePar -reconstruct -time 0
   -parallel`). A normally-solved dispersion (run_disp.sh) instead has it in the latest
   time dir → `--time latest`. Either way the FoamFile `object` header inside `T_CO`/
   `T_NOx` still says `T`, so fix it first (on the `0/` files for POD snapshots).
   **`--decomposed` renders straight from `processor*/0/` with NO reconstruct** (ARM-safe):
   launch parallel pvbatch (`srun pvbatch …` or `mpirun -np N pvbatch --mpi …`, N need not
   equal the decomposition) and fix the header on every `processor*/0/T_<poll>`. Each POD
   disp dir holds ONE pollutant, and `--case` is the RUN dir, not the template.
   **Cluster ParaView is 5.11.2-foss-2023a (aarch64), not 6.0.1.** Headless pvbatch
   **SIGSEGVs on OpenGL** — run `pvbatch --force-offscreen-rendering …` (or `xvfb-run -a
   pvbatch …`). If offscreen GL is unavailable at all, use **`--extract`** (added): the
   script builds NO RenderView — pvbatch `ResampleToImage` the slice → `servermanager.Fetch`
   → numpy → matplotlib draws the map (receptors from `receptors.json` `centroid_recentred`).
   Immune to the headless-OpenGL crash; serial or `--decomposed` parallel (Fetch → rank 0).
   The matplotlib half is verified; the PV extraction half is standard API — smoke-test on
   the cluster.
   **"T_<poll> not found" reading POD snapshots:** two causes, and `location "535"` is NOT
   one (cosmetic; OpenFOAM/ParaView use the directory, not `location`). (a) the FoamFile
   `object` entry inside `T_NOx` still says `T` (the `mv` didn't rewrite it) — fix on every
   `processor*/0/T_NOx`; (b) ParaView's OpenFOAM reader **skips time 0 by default**
   (`SkipZeroTime`), and the snapshot lives in `0/` → set `SkipZeroTime=0` (now in the
   script). Both needed. The script prints `point fields available: [...]` — if it shows
   `T` not `T_NOx`, the object header is the problem; if empty, the reader still isn't
   seeing time 0.
   **Two more non-fatal runtime messages:** (a) `Error reading … processor*/0/sedmXXXX …
   non-digit character` = a leftover `sed -i` temp file in a `0/` dir (interrupted sed) —
   the reader tries to read it as a field and continues; `find "$D"/processor*/0 -name
   'sed*' -delete` and re-run the header sed on all processors. (b) `Bad table range for
   log scale: [-6.4e-10, 5.3], adjusting to [1,10]` = scalarTransportFoam leaves a tiny
   NEGATIVE undershoot, so a log LUT clamps to [1,10] and wrecks the colours. Render path
   now sets a POSITIVE range BEFORE enabling log; the `--extract` path already floors it
   (`vpos=finite[finite>0]`, `LogNorm(max(vmin, vmax*1e-4), vmax)`) — so `--extract` is
   robust to the undershoot and needs no GL.
   Also: **"Fatal vtkpython error: unable to decode the command line argument"** = node
   locale not UTF-8 → `export LC_ALL=C.UTF-8; export LANG=C.UTF-8` before pvbatch (above
   `srun` in the sbatch script; one line per MPI rank in the error = it's all ranks).
4. **`tools/make_techreport.py`** — assembles the polished **`technical_report.pdf`**
   (reportlab): exec summary + methodology + scenarios + results (data-driven tables +
   Fig 1 bar, Fig 2 heatmap, Fig 3/4 maps, optional Fig 5 ground slice) + conclusions +
   limitations. Headline numbers are computed from `receptor_summary.csv`; narrative is
   authored for the current results. Args: `--report --maps --slice <png> --out`.

Key results embedded (10 sampled hours): S1 −20% / S2 −40% uniform at every receptor
(linearity check); S3 ≈ −40% at the Public Hospital (corridor wraps it) but only ≈ −5%
at Santos Simões (off-corridor). Santos Simões is the most exposed at baseline (NOx mean
6.5 µg/m³). CO negligible vs guideline; all levels far below EU/WHO NO2.

Note: the Cowork report-folder mount can be **read-only to the shell** (and refreshes to
empty) — write PDFs to the outputs dir and deliver via `present_files`; the file-tool
`Write` can write text there but not binary.

## 14. VOLUME-AVERAGE RECEPTOR METRIC (added 2026-07-01)

Better receptor metric than the `surfaceFieldValue areaAverage` on the ROI surface:
**volume-average the air concentration in a box above each receptor** (breathing air, not
the surface skin). Two tools, run on the saved POD snapshots — NO re-solve:
1. **`tools/make_receptor_zones.py`** — reads `receptors.json` `centroid_recentred`, writes
   into a `system/` dir: `topoSetDict` (cellSet `boxToCell` + `cellZoneSet` per receptor →
   `roiNZone`), `receptorsVolume` (a `volFieldValue` `volAverage` FO per zone, field token
   `__FIELD__`), and `receptor_zone_map.json` (fo→receptor id/site). Box = centroid ±
   `--halfwidth` (30 m) in x/y, `[z-below, z+height]` (−2..+12 m). ROI cells ~5 m, so keep
   the box a few cells tall or the zone is empty.
2. **`tools/run_receptor_volumes.sh`** (cluster) — `topoSet -parallel` builds the zones ONCE
   in the shared mesh (`flowCaseBig`; visible to every disp dir via the symlinked
   `processor*/constant`), then per (hour,pollutant): `sed __FIELD__→T_<poll>`,
   `postProcess -dict system/receptorsVolume -time 0 -parallel` on the decomposed snapshot
   (falls back to a controlDict `#include` if `-dict` is rejected), parse
   `postProcessing/roiN_vol/*/volFieldValue.dat`, ×1e9 → µg/m³ → **`receptors_long.csv`**.
   One scenario per call (matches `make_report --run`).

The output CSV is the SAME schema `make_report.py` already consumes
(`hour,scenario,pollutant,receptor,site,conc_ugm3`), so `make_report → make_maps →
make_techreport` are unchanged — only the input numbers switch from surface areaAverage to
volume volAverage. Collector + generator verified here on synthetic data; the OpenFOAM
`topoSet`/`postProcess`/`volFieldValue` calls are standard but untested here — smoke-test
on the cluster (esp. whether `postProcess -dict` runs the bare FO dict, else the controlDict
fallback kicks in). Because dispersion is linear, the %-change conclusions won't move; the
absolute values become more exposure-representative.
**Gotcha (hit 2026-07-01): volAverage came out exactly 0** — the REAL cause (logs)
was NOT the canopy (the `--exclude-zone vegetationZone` subtraction removed 0 cells; the
breathing boxes sit in open air, 383–618 cells each). It was that **`postProcess` never
loaded the field**: `volFieldValue`/`surfaceFieldValue` only *look up* a field from the
registry, `postProcess` didn't auto-read it ("Reading fields:" empty → "T_CO not found"),
and the snapshot's FoamFile `object` header still said `T`. **Fix (snapshot, no re-solve):**
`make_receptor_zones.py` now prepends a **`readFields`** FO that loads the field, and
`run_receptor_volumes.sh` (a) fixes the `object` header on every `processor*/0/T_<poll>`
(`sed object T; -> object T_<poll>;`), (b) substitutes the `__FIELD__` token to `T_<poll>`,
(c) `#include`s `receptorsVolume` into the run-dir controlDict, (d) `postProcess -time 0
-parallel`, (e) collects `postProcessing/roiN_vol` → `receptors_long.csv`. Always rebuilds
zones (`topoSet action new`) and wipes stale `roi*_vol` output. `--exclude-zone` is optional
(removed 0 cells here). The canopy perfect-sink is still worth replacing with the finite
`scalarSemiImplicitSource` (−λT, now wired in `dispersionCaseBig/constant/fvOptions`) for
physical in-canopy concentrations, but that needs a re-solve and is independent of the
receptor-zero bug. controlDict `#include "receptorsVolume"` was REVERTED from the canonical
dispersion case (it would break future solves with the unsubstituted `__FIELD__` token).
**DURING-SOLVE mode (for the finite-deposition re-runs):** `make_receptor_zones.py
--field T --no-readfields --wire-controldict <disp>/system/controlDict` writes the
solve-variant FO (`fields (T)`, no readFields — T is live) and atomically adds the
`#include`. Then `topoSet` the zones into the shared mesh ONCE (before the solves), run
the dispersion (run_disp_decomp copies `system/` so the FO rides along and writes
`postProcessing/roiN_vol` on the live T, surviving the T→T_<poll> stash), and gather with
**`tools/collect_receptor_volumes.sh`** (no postProcess — just reads the solve output) →
`receptors_long.csv`. Same FO works for CO and NOx runs (each solves T). `run_receptor_
volumes.sh` stays for the SNAPSHOT path (readFields + header fix + postProcess on already-
run cases).
**Snakemake integration (`Snakefile.podrun`):** `rule roi_zones` (no input →
`MASTER/.roi_zones_done`) runs `make_receptor_zones.py --field T --no-readfields
--wire-controldict` + `topoSet -parallel` once in the shared mesh; `rule disp` depends on
that marker so every solve computes the FO; `rule receptors_volume` (localrule, deps all
`DISP_DONE`) runs `collect_receptor_volumes.sh` → `results_pod/receptors_long_vol.csv`;
`rule all` requires it. Box knobs in `config_pod.yaml` (`roi_halfwidth/height/below`,
optional `roi_exclude_zone`). Finite-deposition `fvOptions` rides along via the copied
`constant/`. Caveats: to re-solve with the new canopy delete `runs_pod/disp` (old DISP_DONE
skipped → NA); `.roi_zones_done` is shared across scenario workflows (first builds, rest
skip — launch reference first to avoid a topoSet race); delete the marker to rebuild zones
after changing box params.
**Two-metric report (2026-07-01):** surface areaAverage and volume volAverage give the
SAME scenario %-changes (S1 −20, S2 −40 by linearity; S3 agrees within ~2 pp at every
receptor) but different absolute levels — volume even flips the most-exposed site (Public
Hospital ~6.4 vs Santos Simões ~5.2 µg/m³ NOx, opposite of surface). So: **report VOLUME
as the primary metric, SURFACE as a robustness cross-check** (strong for the 30%/10%
criteria). `make_techreport.py` gained `--compare-summary <surface receptor_summary.csv>
--compare-label --primary-label` → adds a "4.4 Sensitivity to the sampling method" table
(NOx ref + S3% for both metrics). Build: `make_report` on the four `receptors_long_vol_*.csv`
→ `make_maps` → `make_techreport --compare-summary report/receptor_summary.csv`.
(The compiled `results_pod/` folder is read-only to the Cowork shell → deliver via outputs.)

## 11. ENVIRONMENT GOTCHAS (Cowork bash mount + Snakemake)
- **Bash mount serves a STALE/TRUNCATED view of just-written files.** After writing via
  the file tools, the Linux mount (`/sessions/.../mnt/...`, both `mnt/cases` and
  `mnt/referenceCase/cases`) may show a file cut off mid-line with a wrong (days-old)
  mtime, so `bash -n` falsely fails. The file tool (Read) is the canonical D:\ view. To
  syntax-check reliably, reproduce content into `/tmp` (tmpfs) and `bash -n` there, or
  re-Read the file's tail to confirm it ends correctly. Pre-existing files parse fine —
  it only affects fresh writes.
- **Snakemake "Provided cores: 48 / Rules claiming more threads will be scaled down" is
  HARMLESS.** It's the inner per-job Snakemake seeing one node's 48 cores; it caps the
  rule's `threads` bookkeeping but does NOT limit the run, because the scripts launch MPI
  via `srun -n $NP` (NP=nprocs, e.g. 384), not Snakemake's `{threads}`. Verify real rank
  count in the solver log header (`nProcs : 384`).
