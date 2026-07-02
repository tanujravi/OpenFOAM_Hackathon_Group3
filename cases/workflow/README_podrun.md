# POD-snapshot run (decomposed, ARM) - Snakefile.podrun

Produces the `T_CO`/`T_NOx` fields for a set of selected hours (default 10 of 24),
to feed a POD/PODI **later** (POD training is intentionally NOT part of this).

Everything stays **decomposed end-to-end** (no full reconstruct/decompose → no ARM
OOM). Each hour's flow and each (hour,pollutant) dispersion runs in **its own folder**
under `runs_pod/`, sharing the one frozen decomposed mesh by **symlink** - so the jobs
are independent (parallel, pending-safe, no clobbering, no waiting).

## Prerequisites (one-time, on x86)
1. **Re-mesh once with the porous canopy and freeze the decomposition.** On x86 (RAM
   for scotch), run `flowCaseBig/runallgeo.sh`: it meshes (snappy `-overwrite`), makes
   the serial mesh (`redistributePar -reconstruct -constant`), and builds the
   `vegetationZone` cellZone (`topoSet -parallel`). Decompose to the run rank count
   (e.g. **384** = 8 nodes × 48). The result - `flowCaseBig/{constant/polyMesh,
   processor*/constant}` with the cellZone - is the frozen mesh used by every run.
   (Vegetation is a **porous zone**, not snapped: `constant/fvOptions` +
   `system/topoSetDict`; tune the Forchheimer `f` and topoSet `nearDistance`.)
2. **Pick the vegetation model** (before re-meshing - the modes give *different* meshes):
   `python3 ../tools/set_vegetation_model.py --flow ../flowCaseBig --disp ../dispersionCaseBig
   --model porous|wall`. It stamps a `.veg_model` marker on both cases.
3. **Pick the hours:** `python3 ../tools/select_hours.py --n 10 --out selected_hours.txt`
   (maximin over wind speed/direction + CO/NOx totals). Works for any `--n`.
4. Set `python_bin`, `nprocs` (= the mesh's decomposition), pollutants in `config_pod.yaml`.

## Run (ARM)
```bash
# from cases/workflow/ :
SMK_JOBS=20 ARMPART=<your-arm-partition> bash run_podrun.sh
```
Snakemake submits **one `sbatch` per flow/disp job** (8 nodes × 48, `--mem=0`).
`SMK_JOBS` caps how many are submitted at once; the rest queue (pending is fine).
Dependency: each dispersion waits only for *its own* hour's flow.

> **Vegetation-model guard:** `run_podrun.sh` preflights before submitting - it checks the
> frozen mesh matches the configured model (`wall` ⇒ a `Vegetation` patch; `porous` ⇒ a
> `vegetationZone` cellZone) and aborts with a clear message on mismatch, so you never run
> e.g. porous `fvOptions` against a wall mesh.
(Snakemake ≥ 8: swap `--cluster` for a SLURM profile / `--executor slurm`.)

## How a single run works (no scotch, no reconstruct)
- **flow[h]**: symlink the frozen decomposed mesh, `set_wind --hour h`,
  `decomposePar -fields` the `0/` fields (no scotch), `simpleFoam -parallel`
  (1st→2nd order). Output: that hour's decomposed `U/phi/nut`.
- **disp[h,poll]**: symlink the mesh, copy the hour's frozen `U/phi/nut` into
  `processor*/0/`, `set_emissions` → `decomposePar -fields` only `T`,
  `scalarTransportFoam -parallel`. The converged field is stashed as
  `processor*/0/T_<poll>` so all pollutants/hours coexist for POD.
- Receptor numbers come from the parallel `surfaceFieldValue` FOs (no reconstruct).

## Outputs
- `runs_pod/disp/h<H>/<poll>/processor*/0/T_<poll>` - the decomposed snapshots.
- `results_pod/snapshots.txt` - the list of snapshots (POD input set).
- Visualise without reconstructing: ParaView **Decomposed Case** on a run dir
  (`pvserver`/`pvbatch -parallel`), time 0, fields `T_CO`/`T_NOx`.

## Notes / to tune
- `nprocs` MUST equal the frozen mesh's decomposition count.
- Canopy drag (`flowCaseBig/constant/fvOptions` Forchheimer `f`) and the canopy band
  (`system/topoSetDict` `nearDistance`) are physics knobs - set from leaf-area density
  and tree height.
- POD/PODI training is a separate step you run on `T_<poll>` (not in this workflow).

## Updates (2026-07)

`Snakefile.podrun` now also produces the **receptor tables and report inputs**, not just POD
snapshots. Added rules (`localrules` for the light ones):
- `receptors` → `results_pod/receptors_long.csv` - **surface** areaAverage, via
  `collect_receptors.py` on each disp run's `postProcessing`.
- `roi_zones` (once, marker `MASTER/.roi_zones_done`) - `make_receptor_zones.py --field T
  --no-readfields --wire-controldict` + `topoSet` the breathing-air `roiNZone` cellZones into the
  shared mesh, so every `disp` solve computes a `volFieldValue`. `disp` now depends on it.
- `receptors_volume` → `results_pod/receptors_long_vol.csv` - **volume** volAverage, via
  `collect_receptor_volumes.sh` (reads the FO output written during the solve). Box knobs in
  `config_pod.yaml`: `roi_halfwidth/height/below`, optional `roi_exclude_zone`.

Both CSVs feed the report pipeline in `../tools/` (see `../tools/README.md`); volume is the
primary metric, surface the cross-check.

**Canopy dispersion sink - two implementations.** `dispersionCaseBig/constant/fvOptions` supports
two canopy sinks in `vegetationZone`, selectable per run: a total sink (`scalarFixedValueConstraint`,
T=0, complete uptake) and a finite first-order dry deposition (`scalarSemiImplicitSource`, -λT,
λ≈1e-3 s⁻¹, so canopy cells hold realistic concentrations). To re-solve after switching, delete
`runs_pod/disp` (old `DISP_DONE` would be skipped).

**Cluster launcher.** `run_podrun.sh` submits via Snakemake's **cluster-generic** executor
(`--executor cluster-generic --cluster-generic-submit-cmd "sbatch … --parsable …"`;
`--cluster` was removed in Snakemake ≥ 8). Gotchas fixed: run the controller on an **aarch64**
node with an aarch64-native Snakemake (its `sys.executable` is re-invoked on the compute nodes);
`config_pod.yaml` `python_bin` must be an aarch64 numpy Python. To reuse converged flows for a new
scenario, symlink `runs_pod/flow` into a fresh `work_dir` and run with `--rerun-triggers mtime`.
