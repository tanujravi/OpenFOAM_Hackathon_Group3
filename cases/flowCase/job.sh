#!/bin/bash
#SBATCH --job-name=flow
#SBATCH --account=f202500001hpcvlabepicurex
#SBATCH --partition=normal-x86
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --time=01:00:00
#SBATCH --error=flow.err
#SBATCH --output=flow.out
# Source OpenFOAM (Define the bashrc of your local openfoam location)
nprocs=128
module load OpenFOAM/v2512-foss-2025a
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc"

sed_command="s/numberOfSubdomains [0-9]\+;/numberOfSubdomains ${nprocs};/g"
eval "sed -i \"$sed_command\" system/decomposeParDict"

decomposePar -force 

srun potentialFoam -parallel > log.potentialFoam 2>&1

srun simpleFoam -parallel > log.simpleFoam 2>&1

echo "=== simpleFoam 128 cores DONE ==="

reconstructPar -latestTime