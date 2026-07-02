#!/bin/bash
# =====================================================================
# run_validate.sh
# ---------------------------------------------------------------------
# PODI validation study + model export for ALL pollutants (podi_validate.py).
# This is a SINGLE-PROCESS NumPy job (not MPI) -> 1 task, no mpirun.
# Run AFTER run_export_and_collect.sh has produced staging/ + parameters.csv.
#
#   sbatch run_validate.sh
# =====================================================================

#SBATCH --job-name=podi_fit
#SBATCH --account=f202500001hpcvlabepicurea
#SBATCH --partition=normal-arm
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=48        # BLAS/OMP threads for the matmuls (x86 node has 128)
#SBATCH --mem=28G                  # peak ~10 GB (unit-norm snapshots + one m x r matmul); node has 30 GB
#SBATCH --time=01:00:00
#SBATCH --output=podi_fit.out
#SBATCH --error=podi_fit.err

set -euo pipefail

CONFIG="${CONFIG:-config.yaml}"

# Thread the linear algebra across the allocated CPUs.
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-8}"
export OPENBLAS_NUM_THREADS="$OMP_NUM_THREADS"
export MKL_NUM_THREADS="$OMP_NUM_THREADS"

# ---- Python environment --------------------------------------------- #
# EasyBuild stack (x86_64). All from the gfbf-2023a / GCCcore-12.3.0
# generation -> Python 3.11.3, mutually compatible.
module purge
module load SciPy-bundle/2025.07-gfbf-2025b   # numpy 1.25, scipy, pandas
module load matplotlib/3.10.5-gfbf-2025b
module load PyYAML/6.0.2-GCCcore-14.3.0
command -v python3 >/dev/null || { echo "python3 not on PATH"; exit 1; }
python3 -c "import numpy, yaml, matplotlib" 2>/dev/null || {
    echo "Missing a Python dep (numpy / pyyaml / matplotlib). Load your Python module."; exit 1; }

echo "=== PODI validation + model export (config=$CONFIG) ==="
python3 podi_validate.py "$CONFIG"
echo "=== done: models/ + plot/<pollutant>/ written ==="
