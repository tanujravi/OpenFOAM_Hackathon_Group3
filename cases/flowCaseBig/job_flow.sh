#!/bin/bash
#SBATCH --job-name=flow
#SBATCH --account=f202500001hpcvlabepicurex
#SBATCH --partition=normal-x86
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=96   # 96/node (not 128) eases memory-bandwidth contention
#SBATCH --mem=0                # full node RAM (esp. for the serial decomposePar/reconstructPar/carve steps)
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
nprocs=${SLURM_NTASKS:-384}   # match decomposition to the allocation (4x96)
module load OpenFOAM/v2512-foss-2025a
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc"

# match decomposition to the rank count
sed -i "s/numberOfSubdomains [0-9]\+;/numberOfSubdomains ${nprocs};/g" system/decomposeParDict

# --- one-time: carve the 'streets' patch into THIS (flow) mesh, BEFORE solving.
#     This splits Terrain -> Terrain + streets so every field is written on the
#     final mesh; the dispersion case then reuses this mesh + fields with matching
#     face counts (no post-solve createPatch, which would desync field sizes).
HALFWIDTH=${HALFWIDTH:-6.0}
if ! grep -qE "^[[:space:]]*streets$" constant/polyMesh/boundary 2>/dev/null; then
  echo "=== carving 'streets' patch into the flow mesh (one-time) ==="
  if head -c 4000 constant/polyMesh/points | grep -qi "format[[:space:]]*binary"; then
    foamFormatConvert -constant > log.formatConvert 2>&1 || true   # carver needs ASCII mesh
  fi
  python3 ../tools/make_street_patches.py --case .           --roads geo/snapped_road_segments_recentred.csv --half-width "$HALFWIDTH" > log.carve 2>&1
  createPatch -overwrite > log.createPatch 2>&1
  # createPatch does not propagate the new patch into the 0/ fields -> clone Terrain
  python3 ../tools/add_streets_bc.py --case . --fields U p k epsilon nut omega > log.addStreetsBC 2>&1
  echo "=== streets carved; Terrain split, uniform 0/ fields updated ==="
else
  echo "=== 'streets' patch already present in mesh; skipping carve ==="
fi

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

srun redistributePar -reconstruct -latestTime -parallel > log.reconstruct 2>&1

# restore the 1st-order set as the default active fvSchemes (tidy for re-runs)
cp system/fvSchemes_1storder system/fvSc