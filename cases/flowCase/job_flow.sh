#!/bin/bash
#SBATCH --job-name=flow
#SBATCH --account=f202500001hpcvlabepicurex
#SBATCH --partition=normal-x86
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --time=02:00:00
#SBATCH --error=flow.err
#SBATCH --output=flow.out
# =============================================================================
#  Flow precursor (ABL inlet, k-epsilon). Two-stage for robustness on the stiff
#  terrain mesh:
#    Stage A  potentialFoam init + simpleFoam with 1st-ORDER turbulence (bounded)
#    Stage B  switch to 2nd-ORDER schemes, restart from latestTime for accuracy
#  (jumping straight to 2nd order diverges -> k/epsilon blow up -> GAMG SIGFPE.)
# =============================================================================
nprocs=128
module load OpenFOAM/v2512-foss-2025a
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc"

# match decomposition to the rank count
sed -i "s/numberOfSubdomains [0-9]\+;/numberOfSubdomains ${nprocs};/g" system/decomposeParDict

decomposePar -force

# ----------------------------- Stage A: 1st order ----------------------------
cp system/fvSchemes_1storder system/fvSchemes
srun potentialFoam -parallel > log.potentialFoam        2>&1
srun simpleFoam    -parallel > log.simpleFoam.1storder  2>&1
echo "=== Stage A (1st order) done; latestTime = $(foamListTimes -latestTime) ==="

# ----------------------------- Stage B: 2nd order ----------------------------
# continue from the converged 1st-order field (controlDict: startFrom latestTime)
cp system/fvSchemes_2ndorder system/fvSchemes
latest=$(foamListTimes -latestTime)
foamDictionary -entry endTime -set $(( latest + 2000 )) system/controlDict
srun simpleFoam -parallel > log.simpleFoam.2ndorder 2>&1
echo "=== Stage B (2nd order) done; latestTime = $(foamListTimes -latestTime) ==="

reconstructPar -latestTime

# restore the 1st-order set as the default active fvSchemes (tidy for re-runs)
cp system/fvSchemes_1storder system/fvSchemes
