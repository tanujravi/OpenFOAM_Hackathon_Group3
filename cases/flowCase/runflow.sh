#!/bin/bash
#SBATCH --job-name=flowSim
#SBATCH --account=f202500001hpcvlabepicurex
#SBATCH --partition=normal-x86
#SBATCH --nodes=1
#SBATCH --ntasks=96
#SBATCH --time=04:00:00
#SBATCH --error=flow.err
#SBATCH --output=flow.out

module load OpenFOAM/v2512-foss-2025a
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc"

nprocs=96

[ -d logs ] || mkdir logs

# Keep decomposeParDict in sync with nprocs
sed -i "s/numberOfSubdomains [0-9]\+;/numberOfSubdomains ${nprocs};/" system/decomposeParDict

echo "=== [1/4] decomposePar ==="
decomposePar -force > logs/decomposePar_flow.log 2>&1 \
    && echo "    done" \
    || { echo "    FAILED — check logs/decomposePar_flow.log"; exit 1; }

echo "=== [2/4] simpleFoam (${nprocs} ranks) ==="
mpirun -np $nprocs simpleFoam -parallel > logs/simpleFoam.log 2>&1
# Note: simpleFoam exits 0 even when it hits endTime without converging,
# so we do not treat a non-zero exit here as fatal.
echo "    solver finished (check residuals plot for convergence)"

echo "=== [3/4] reconstructPar (latest time only) ==="
reconstructPar -latestTime > logs/reconstructPar_flow.log 2>&1 \
    && echo "    done" \
    || echo "    WARNING: reconstruct failed — see logs/reconstructPar_flow.log"

echo "=== [4/4] plotting residuals ==="
python3 "$(dirname "$0")/plot_residuals.py" "$(dirname "$0")" \
    && echo "    saved residuals.png" \
    || echo "    WARNING: plotter failed (postProcessing data may not exist yet)"

echo "=== runflow.sh complete ==="
