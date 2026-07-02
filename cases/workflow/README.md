# Workflow (Snakemake) - POD-snapshot run

Snakemake orchestration for the big-domain **POD-snapshot run**: it produces the decomposed
`T_CO`/`T_NOx` fields for the selected representative hours across the four scenarios (the
snapshots that train the PODI surrogate), and computes the receptor tables and report inputs.

Full prerequisites, the launch command and the run mechanics are in **`README_podrun.md`**
(`Snakefile.podrun` + `run_podrun.sh`). In short:

- `Snakefile.podrun` - per-hour flow + per-(hour,pollutant) dispersion, decomposed end-to-end
  (no serial reconstruct/decompose, so no ARM OOM); each run in its own folder, parallel-safe.
- `run_podrun.sh` - cluster launcher (Snakemake cluster-generic executor, one sbatch per job);
  it preflights the vegetation model against the frozen mesh before submitting.
- `config_pod.yaml` - `python_bin` (absolute aarch64 numpy python), `nprocs` (must equal the
  frozen mesh's decomposition), pollutants, selected hours, and the receptor-box knobs.
- `../tools/select_hours.py` picks the representative hours (maximin over wind + emissions).

Outputs: the decomposed snapshots (`runs_pod/disp/h*/<poll>/processor*/0/T_<poll>`), the surface
and volume receptor tables (`results_pod/receptors_long*.csv`), and `snapshots.txt`. The receptor
metrics and the report pipeline are described in `README_podrun.md` and `../tools/README.md`.

Regenerable (safe to delete): `runs_pod*/`, `results_pod*/`, `.snakemake/`, `processor*/`.
