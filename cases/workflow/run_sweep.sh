#!/bin/bash
#SBATCH --job-name=sweep24
#SBATCH --account=f202500001hpcvlabepicurex
#SBATCH --partition=normal-x86
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --time=24:00:00
#SBATCH --output=sweep.out
#SBATCH --error=sweep.err
# ---------------------------------------------------------------------------
#  Launch the 24-hour Snakemake sweep INSIDE one SLURM allocation. The per-solve
#  `srun -n NPROCS` calls inside the rules use this allocation's ranks, so run
#  Snakemake with --cores 1 (ONE OpenFOAM solve at a time; each already uses all
#  ranks). For many hours truly in parallel, use a Snakemake SLURM profile
#  instead (one sbatch per rule) -- see README.md.
#
#  Quasi-steady (default):  sbatch run_sweep.sh
#  Transient:               SMK=Snakefile.transient sbatch run_sweep.sh
# ---------------------------------------------------------------------------
module load OpenFOAM/v2512-foss-2025a
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc"
cd "${SLURM_SUBMIT_DIR:-.}"
SMK="${SMK:-Snakefile}"
snakemake -s "$SMK" --cores "${CORES:-1}" -p --keep-going
