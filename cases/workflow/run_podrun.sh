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

# Snakemake >=8 removed --cluster from core; use the cluster-generic executor plugin.
# (one-time install if missing:  pip install snakemake-executor-plugin-cluster-generic)
python -c 'import snakemake_executor_plugin_cluster_generic' 2>/dev/null \
  || { echo "ERROR: missing plugin -- run: pip install snakemake-executor-plugin-cluster-generic"; exit 1; }

snakemake -s Snakefile.podrun --jobs "$SMK_JOBS" --latency-wait 120 --keep-going \
  --executor cluster-generic \
  --cluster-generic-submit-cmd "sbatch --account=$ACCOUNT --partition=$ARMPART \
     --nodes=8 --ntasks-per-node=48 --mem=0 --time=06:00:00 \
     --parsable --job-name=pod_{rule} --output=logs/{rule}.%j.out"
# Keeps your design: each sbatch grabs the 8x48 allocation, the job script's own
# `srun ... -parallel` then uses all 384 ranks (do NOT use --executor slurm here -- it
# would wrap jobs in its own srun and nest inside your scripts' srun calls).
# Optional, more robust SLURM status polling (avoids false "missing output" under load):
#   --cluster-generic-status-cmd "<a sacct/squeue status script>"
