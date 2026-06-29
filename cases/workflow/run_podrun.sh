#!/bin/bash
# Launch the POD-snapshot run. Snakemake submits ONE sbatch per flow/disp job
# (8 nodes x 48 each), so they run in parallel in their own folders; jobs over the
# concurrency cap simply queue (pending). Run from cases/workflow/.
#   SMK_JOBS=20 ARMPART=<arm-partition> bash run_podrun.sh
set -euo pipefail
module load OpenFOAM/v2512-foss-2025a 2>/dev/null || true
mkdir -p logs

# ---- preflight: the frozen mesh must match the configured vegetation model ----
MASTER=$(awk -F'[:#]' '/^mesh_case:/{gsub(/[" ]/,"",$2);print $2}' config_pod.yaml)
DISPC=$(awk  -F'[:#]' '/^disp_case:/{gsub(/[" ]/,"",$2);print $2}' config_pod.yaml)
VMF=$(tr -d '[:space:]' < "$MASTER/.veg_model" 2>/dev/null || echo unset)
VMD=$(tr -d '[:space:]' < "$DISPC/.veg_model" 2>/dev/null || echo unset)
[ "$VMF" = "$VMD" ] || { echo "ERROR: flow(.veg_model=$VMF) vs disp($VMD) disagree -- re-run tools/set_vegetation_model.py."; exit 1; }
BND="$MASTER/processor0/constant/polyMesh/boundary"; [ -f "$BND" ] || BND="$MASTER/constant/polyMesh/boundary"
CZ="$MASTER/processor0/constant/polyMesh/cellZones"; [ -f "$CZ" ] || CZ="$MASTER/constant/polyMesh/cellZones"
case "$VMF" in
  wall)   grep -qiE '^[[:space:]]*Vegetation' "$BND" 2>/dev/null || { echo "ERROR: model=wall but no 'Vegetation' patch in the frozen mesh ($BND). Re-mesh in wall mode."; exit 1; } ;;
  porous) grep -qi 'vegetationZone' "$CZ" 2>/dev/null || { echo "ERROR: model=porous but no 'vegetationZone' cellZone in the frozen mesh ($CZ). Re-mesh in porous mode (runallgeo runs topoSet)."; exit 1; } ;;
  *) echo "ERROR: vegetation model not set -- run tools/set_vegetation_model.py before meshing."; exit 1 ;;
esac
echo "[preflight] vegetation model = $VMF (frozen mesh matches)."
SMK_JOBS=${SMK_JOBS:-20}        # max jobs submitted at once (rest pend); set as high as you like
ARMPART=${ARMPART:-normal-arm}  # your ARM partition name
ACCOUNT=${ACCOUNT:-f202500001hpcvlabepicurex}

snakemake -s Snakefile.podrun --jobs "$SMK_JOBS" --latency-wait 120 --keep-going \
  --cluster "sbatch --account=$ACCOUNT --partition=$ARMPART --nodes=8 --ntasks-per-node=48 \
             --mem=0 --time=06:00:00 --job-name=pod_{rule} --output=logs/{rule}.%j.out"
# snakemake>=8: replace --cluster with a SLURM profile / --executor slurm (see workflow README).
