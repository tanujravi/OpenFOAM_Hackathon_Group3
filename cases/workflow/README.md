# 24-hour mobility-scenario sweep (Snakemake)

**Work in progress.** Extends the validated one-hour pipeline (`../README` files,
`../run_single_hour.sh`) to the full day: all **24 hours x 4 scenarios x 2
pollutants**, with daily aggregation and cross-scenario comparison at the four
receptors. Two temporal strategies are provided (CLAUDE.md asks us to *choose and
document* one and keep it identical across scenarios):

| Strategy | Snakefile | What it does | Cost |
|---|---|---|---|
| **Quasi-steady** (24 states) | `Snakefile` | Per hour: one steady flow; each hour's scalar solved to steady state **independently** (no carryover). | 24 flow + 192 dispersion solves |
| **Transient** (chained day) | `Snakefile.transient` | Marches real time: 24 hourly segments chained on one case, carrier flow + emission refreshed each hour, pollutant **carried over** (build-up captured). Flow stays piecewise-steady. | 24 flow + 8 chained 24h scalar runs |

Both reuse **one mesh** (carved once) and **one frozen flow per hour** across all
scenarios/pollutants, so only the emission scaling differs between scenarios —
the fairness requirement.

> **POD-snapshot run (decomposed, ARM).** For the fully-decomposed multi-hour run that
> produces `T_CO`/`T_NOx` snapshots for POD/PODI — one `sbatch` job per hour/pollutant,
> no reconstruct/decompose — see **`README_podrun.md`** + `Snakefile.podrun`, and pick
> the hours with `../tools/select_hours.py`. (POD training itself is left to you.)

## Layout
```
workflow/
  config.yaml              hours, scenarios, pollutants, paths, nprocs, DT, python_bin
  Snakefile                quasi-steady DAG  (default)
  Snakefile.transient      transient DAG
  rules/common.smk         shared rules: carve_mesh (once) + flow_hour[h]
  scripts/
    carve_mesh.sh          carve the shared 'streets' patch into the flow mesh (idempotent)
    run_flow_hour.sh       set_wind(h) + 2-stage simpleFoam -> frozen U/phi/nut  (mesh symlinked)
    run_disp.sh            set_emissions(h,scn,pol) + scalarTransportFoam -> receptors.csv
    run_transient_day.sh   chained 24h transient scalarTransportFoam for one (scn,pol)
  transient/
    controlDict.transient  transient solver control (Euler, runTime writing)
    fvSchemes.transient    Euler ddt schemes
  run_sweep.sh             SLURM launcher (runs snakemake inside one allocation)
```
Outputs (regenerable, git-ignored): `runs/` (per-hour flow + per-cell solves),
`results/` (quasi-steady tables), `results_transient/` (transient tables).

## DAG
```
carve_mesh ──┬─ flow_hour[h=0..23] ──┬─ disp[h,scn,pol]  ──┐         (quasi-steady)
             │                       └─ (24x4x2 = 192)     ├─ aggregate -> results/
             └─ flow_hour[h=0..23] ───  transient_day[scn,pol] (8) ─┘  (transient -> results_transient/)
```
Job counts (dry-run verified): quasi-steady **219**, transient **35**.

## Configure
Edit `config.yaml`. The one setting you MUST get right on the cluster:

```yaml
python_bin: "/ABSOLUTE/path/to/python3"   # a python with numpy; see note below
```
Snakemake's shell does not see conda/aliases, so set `python_bin` to the output of
`python3 -c "import sys; print(sys.executable)"` **in the env where the tools run**.
`nprocs` must match the rank count you launch with; `DT` is the scalar diffusivity.

## Run
Prerequisite: the mesh exists in `../flowCase/constant/polyMesh` (`sbatch
../flowCase/runallgeo.sh` once). `carve_mesh` then carves `streets` into it.

```bash
# from cases/workflow/
snakemake -n --cores 1                      # dry run: print the 219-job plan
snakemake -s Snakefile.transient -n --cores 1   # transient plan (35 jobs)

# on the cluster, inside one allocation (each solve uses all NPROCS ranks):
sbatch run_sweep.sh                         # quasi-steady
SMK=Snakefile.transient sbatch run_sweep.sh # transient
```
For many hours genuinely in parallel (one SLURM job per rule), drop `run_sweep.sh`
and use a Snakemake SLURM profile: `snakemake --profile <slurm-profile> --jobs 24`.
The rules already `srun -n NPROCS ... -parallel`, so a profile that grants each job
its own node works without edits.

## Outputs (the deliverable)
`results/` (and `results_transient/`):
- `hourly_long.csv` — tidy `hour,scenario,pollutant,receptor,site,conc_ugm3`.
- `receptor_daily_summary.csv` — per scenario/pollutant/receptor: daily **mean**,
  **peak**, peak-hour, n_hours.
- `scenario_comparison.csv` — per pollutant/receptor/metric: the reference value,
  each scenario's value, and **% change vs reference** (the headline result).

Re-aggregate without re-solving: `python3 ../tools/aggregate_day.py --work runs --out results`.

## The heaviest option (not wired)
A **fully transient flow** (`pimpleFoam` over 24 h with time-varying ABL inlet)
would also capture wind unsteadiness, not just pollutant carryover. It is far more
expensive and needs a new flow case; the transient strategy here deliberately keeps
the flow piecewise-steady (hourly frozen fields) as the practical middle ground.

## Clean
```bash
snakemake clean                              # rm runs/ results/ .snakemake/
snakemake -s Snakefile.transient clean       # rm runs/trans results_transient/ .snakemake/
```

## Updates (2026-07)

- **ARM-safe scripts.** `run_flow_hour.sh`, `run_disp.sh`, `run_transient_day.sh` no longer do a
  full **serial** mesh `decomposePar`/`reconstructPar` (which OOMs the ~40 M-cell big mesh on ARM).
  In the parallel (`PAR=true`) path the pre-decomposed mesh is **symlinked** and only FIELDS move:
  `decomposePar -fields` scatters, and `redistributePar -reconstruct -parallel` gathers the frozen
  flow (dispersion needs no gather — receptors come from the parallel FOs). Requires `$FLOW`
  pre-decomposed (`processor*/constant`) + a serial mesh; `NP` must equal the decomposition. The
  `frozen/U` output contract is unchanged, so these Snakefiles need no edits.
- **Snakemake ≥ 8 (cluster).** `--cluster "sbatch …"` was removed from core; use
  `--executor cluster-generic --cluster-generic-submit-cmd "sbatch … --parsable …"` (needs
  `snakemake-executor-plugin-cluster-generic`). See `README_podrun.md` for the same fix in
  `run_podrun.sh`, plus the ARM/x86 interpreter and locale gotchas.
- **Receptor volume metric.** The POD workflow (`Snakefile.podrun`) also builds a *volume-average*
  receptor table alongside the surface one — see `README_podrun.md` and `../tools/README.md`.
