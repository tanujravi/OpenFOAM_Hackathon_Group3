# PODI Air-Quality Surrogate Pipeline

A two-phase pipeline that builds a **Proper Orthogonal Decomposition Interpolation (PODI)** surrogate from OpenFOAM urban-dispersion CFD runs, then uses it to predict pollutant concentration fields for new traffic scenarios and sample them at receptor locations — at a fraction of the cost of running new simulations.

---

## What it does

Given a set of OpenFOAM dispersion simulations (CO and NOx, across wind hours and traffic scenarios), the pipeline:

1. **Trains a PODI surrogate model** that can reconstruct any 3D concentration field from a compact set of parameters: wind components (u, v) and emission scalings (G for gasoline vehicles, L for light-duty/bus traffic).

2. **Predicts 24-hour field stacks** for new scenarios by evaluating the surrogate — orders of magnitude faster than running the full CFD solver.

3. **Reconstructs fields into OpenFOAM format** and samples them at 4 urban receptor locations, producing hourly concentration time series for each scenario.

4. **Generates comparison plots** of all scenarios at each receptor.

---

## Scenarios

| ID   | Description                | G (gasoline) | L (light-duty) |
|------|----------------------------|:---:|:---:|
| full | Reference (full traffic)   | 1.0 | 1 |
| S1   | −20% gasoline vehicles     | 0.8 | 1 |
| S2   | −40% gasoline vehicles     | 0.6 | 1 |
| S3   | Metro Bus (−50% N101 route)| 1.0 | 0 |

---

## Pipeline Phases

### Phase 1 — Data export and collection

```
run_export_and_collect.sh   →   foamToNumpy -parallel   (all CO / NOx cases)
                            →   collect_cases.py         (staging/ + parameters.csv)
```

- `run_export_and_collect.sh` — SLURM job (8 ARM nodes, 384 MPI ranks) that exports each decomposed OpenFOAM case to per-processor `.npy` arrays via `foamToNumpy`, then calls `collect_cases.py`.
- `collect_cases.py` — Scans the simulation tree (`workflow{,_S1,_S2,_S3}/runs_pod*/disp/h<N>/<pollutant>`), creates `parameters.csv` (one row per case: `u, v, G, L`), and builds a `staging/` tree of symlinks — no data copying.

### Phase 2 — PODI model training

```
podi_big.py         (Method of Snapshots Gram matrix, in-memory or streaming)
podi_validate.py    (cross-validation, mode selection, model pickle export)
```

- `podi_big.py` — Trains a linear PODI model using the **Method of Snapshots** to avoid ever materialising an `nCells × nModes` basis. Supports a streaming mode for meshes with tens of millions of cells. Run once per pollutant.
- `podi_validate.py` — Performs 75/25 stratified train/test split, sweeps mode count to minimise test error, saves diagnostic plots (`pod_spectrum.png`, `parity.png`, `mode_selection.png`, etc.), and exports the final model fitted on all data as `model_CO.pkl` / `model_NOx.pkl`.

The model separates **shape** (normalised spatial distribution, handled by POD + linear regression over features of u, v, G, L) from **magnitude** (scalar concentration level, handled by RBF interpolation), covering the ~50× dynamic range driven by wind speed and emission rate.

### Phase 3 — Prediction and receptor sampling

```
build_template.sh        (lightweight OpenFOAM template, mesh symlinks only)
run_receptors.sh  (SLURM)
  ├─ predict_day.py      (PODI → 24 × nCells field per processor as .npy)
  ├─ numpyToFoam         (write fields into OpenFOAM case, parallel)
  ├─ postProcess         (surfaceFieldValue at 4 receptors, parallel)
  ├─ parse_receptors.py  (receptor .dat → master CSV)
  └─ plot_receptors.py   (concentration vs time plots, all scenarios)
```

- `build_template.sh` — Creates a reusable OpenFOAM case by symlinking the 384-processor mesh from the reference case (no multi-GB copy), configuring binary field writes and a `numpyToFoamDict` for times 1–24.
- `run_receptors.sh` — Main SLURM job (8 ARM nodes, 384 ranks, up to 4 h). For every `(pollutant, scenario)` combination:
  1. `predict_day.py` evaluates the PODI model for the full 24-hour wind profile and writes per-processor `.npy` stacks.
  2. `numpyToFoam -parallel` loads the predicted data into the decomposed OpenFOAM case as time directories 1–24.
  3. `postProcess -parallel` samples the 4 receptor surfaces (area-averaged concentration).
  4. `parse_receptors.py` appends rows to `receptor_results.csv` (`pollutant, scenario, receptor_key, receptor_name, hour, clock, conc_kgm3, conc_ugm3`).
  5. Large temporaries (time directories, field files) are deleted before the next iteration.
- `plot_receptors.py` — Reads `receptor_results.csv` and saves one PNG per receptor (all 4 scenario curves) plus a 2×2 overview per pollutant.

---

## Outputs

| File / Directory         | Contents |
|--------------------------|----------|
| `parameters.csv`         | Training parameter table (u, v, G, L per case) |
| `staging/<pol>/<case>/`  | Symlink tree of per-processor `.npy` snapshots |
| `models/model_CO.pkl`    | Trained PODI surrogate for CO |
| `models/model_NOx.pkl`   | Trained PODI surrogate for NOx |
| `receptor_results.csv`   | Hourly receptor concentrations for all pollutant/scenario combinations |
| `receptor_plots/`        | Per-receptor and overview PNG concentration plots |
| `results/<pol>_<scen>/`  | Archived `postProcessing/` for each combination |

---

## Dependencies

| Component       | Version / Module |
|-----------------|-----------------|
| OpenFOAM        | v2512 (`OpenFOAM/v2512-foss-2025a`) |
| Python          | 3.13 via `SciPy-bundle/2025.07-gfbf-2025b` |
| numpy, scipy    | via SciPy-bundle |
| PyYAML          | `PyYAML/6.0.2-GCCcore-14.3.0` |
| matplotlib      | `matplotlib/3.10.5-gfbf-2025b` |
| numpyToFoam     | Custom OpenFOAM utility (ARM build required) |
| foamToNumpy     | Custom OpenFOAM utility (ARM build required) |

HPC target: SLURM cluster with ARM nodes (`normal-arm` partition), 384 MPI ranks (8 nodes × 48 cores/node).

---

## Quick start

```bash
# 1. Export CFD snapshots and build the staging tree
sbatch run_export_and_collect.sh

# 2. Train the surrogate (once per pollutant)
python3 podi_big.py --cases-dir staging/CO --parameters parameters.csv --field T_CO
python3 podi_validate.py --cases-dir staging/CO --parameters parameters.csv \
    --field T_CO --out-model models/model_CO.pkl

python3 podi_big.py --cases-dir staging/NOx --parameters parameters.csv --field T_NOx
python3 podi_validate.py --cases-dir staging/NOx --parameters parameters.csv \
    --field T_NOx --out-model models/model_NOx.pkl

# 3. Run the receptor prediction pipeline
bash prediction_pipeline/build_template.sh          # build template once
sbatch prediction_pipeline/run_receptors.sh         # full sweep (CO+NOx, all scenarios)

# Test a single combination first
POLLUTANTS="CO" SCENARIOS="full" sbatch prediction_pipeline/run_receptors.sh
```
