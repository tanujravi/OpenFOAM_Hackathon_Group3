#!/bin/bash
#SBATCH --job-name=disp
#SBATCH --account=f202500001hpcvlabepicurex
#SBATCH --partition=normal-x86
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --mem=0                # full node RAM (esp. for the serial decomposePar/reconstructPar/carve steps)
#SBATCH --time=02:00:00
#SBATCH --error=logs/disp.err
#SBATCH --output=logs/disp.out
# =============================================================================
#  Single-hour DISPERSION driver (assumes the flow is already converged).
#
#  Prereq: run the flow first in cases/flowCase (job_flow.sh). job_flow.sh carves
#  the 'streets' patch into the flow mesh BEFORE solving, so Terrain is already
#  split and the frozen U/phi/nut match the Terrain+streets face counts. This
#  script then, for one hour / one scenario:
#    1. reuse that split mesh + frozen U/phi/nut (no carve) + streets map
#    2. per pollutant: set per-segment emission on 'streets' -> scalarTransportFoam
#       (receptor function objects sample T at the 4 ROI surfaces)
#    3. receptor_table.py -> results/.../receptor_table.csv  (ug/m^3)
#
#  Config via env: HOUR=0 SCENARIO=reference POLLUTANTS="CO NOx"
#                  NPROCS=96  DT=1.0  FLOWTIME=latestTime
#  Run:  sbatch run_single_hour.sh   |   HOUR=8 SCENARIO=S2 bash run_single_hour.sh
# =============================================================================
set -e
module load OpenFOAM/v2512-foss-2025a 2>/dev/null || true
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc" 2>/dev/null || true
# Under sbatch, $0 is the spooled copy in /var/spool/slurm/... -- so anchor on
# SLURM_SUBMIT_DIR (the dir you ran `sbatch` from); fall back to $0 for plain bash.
ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")" && pwd)}"; cd "$ROOT"
echo "[run_single_hour] ROOT=$ROOT"
[ -d "./flowCase" ] || { echo "ERROR: flowCase not under ROOT=$ROOT. Submit from the repo root (sbatch run_single_hour.sh)."; exit 1; }
HOUR=${HOUR:-1}; SCENARIO=${SCENARIO:-reference}; POLLUTANTS=${POLLUTANTS:-"CO NOx"}
HALFWIDTH=${HALFWIDTH:-28.0}; NPROCS=${NPROCS:-128}; DT=${DT:-1.0}
FLOW=${FLOW:-./flowCase}; DISP=${DISP:-./dispersionCase}; TOOLS=${TOOLS:-./tools}
RESULTS="./results/h${HOUR}_${SCENARIO}"; 
mkdir -p "$RESULTS" logs
log(){ echo "[$(date +%H:%M:%S)] $*"; }

[ -d "$FLOW/constant/polyMesh" ] || { echo "ERROR: no mesh in $FLOW -- run runallgeo.sh."; exit 1; }
FLOWTIME=${FLOWTIME:-$(foamListTimes -case "$FLOW" -latestTime)}
[ -n "$FLOWTIME" ] && [ "$FLOWTIME" != "0" ] || {
    echo "ERROR: $FLOW has no converged time dir (run the flow / job_flow.sh first)."; exit 1; }
[ -f "$FLOW/$FLOWTIME/U" ] || { echo "ERROR: $FLOW/$FLOWTIME/U missing."; exit 1; }
log "using frozen flow from $FLOW/$FLOWTIME"

# --------------------------------------------- STAGE 1: reuse split mesh + fields
# The 'streets' patch is carved ONCE in the flow case (job_flow.sh) BEFORE the flow
# solve, so Terrain is already split there and the frozen U/phi/nut are written on
# the Terrain+streets mesh. We reuse that mesh + fields directly (face counts match)
# -- no carve/createPatch here, which would desync the copied field sizes.

log "STAGE 1  reuse split mesh + frozen fields from $FLOW"
grep -qE "^[[:space:]]*streets$" "$FLOW/constant/polyMesh/boundary" || {
  echo "ERROR: no 'streets' patch in $FLOW mesh. Run job_flow.sh (it carves streets"
  echo "       into the flow mesh before solving)."; exit 1; }
rm -rf "$DISP/constant/polyMesh"
cp -r "$FLOW/constant/polyMesh" "$DISP/constant/"
cp "$FLOW/$FLOWTIME/U"   "$DISP/0/U"
cp "$FLOW/$FLOWTIME/phi" "$DISP/0/phi"
[ -f "$FLOW/$FLOWTIME/nut" ] && cp "$FLOW/$FLOWTIME/nut" "$DISP/0/nut"
mkdir -p "$DISP/geo"
cp "$FLOW/geo/streets_face_segments.csv" "$DISP/geo/"   # face->segment map (from the flow carve)
# 0/T (authored, 4 patches) gains its 'streets' entry from set_emissions below.

# --------------------------------------------- STAGE 2: dispersion per pollutant
for POLL in $POLLUTANTS; do
  log "STAGE 2  $POLL  (scenario=$SCENARIO hour=$HOUR)"
  python3 "$TOOLS/set_emissions.py" --case "$DISP" --pollutant "$POLL" \
          --hour "$HOUR" --scenario "$SCENARIO" --DT "$DT" | tee "$ROOT/logs/emit_$POLL.log"
  ( cd "$DISP"
    foamListTimes -rm > /dev/null 2>&1 || true     # drop previous scalar solution
    rm -rf processor* postProcessing
    decomposePar -force                     > "$ROOT/logs/disp_${POLL}_decompose.log" 2>&1
    srun scalarTransportFoam -parallel > "$ROOT/logs/disp_${POLL}_solve.log" 2>&1
    reconstructPar -latestTime              > "$ROOT/logs/disp_${POLL}_reconstruct.log" 2>&1
    rm -rf processor* )
  DLATEST=$(foamListTimes -case "$DISP" -latestTime)
  [ -n "$DLATEST" ] || { echo "ERROR: $DISP produced no time dir for $POLL."; exit 1; }
  cp "$DISP/$DLATEST/T" "$RESULTS/T_${POLL}"
  rm -rf "$RESULTS/pp_${POLL}"; cp -r "$DISP/postProcessing" "$RESULTS/pp_${POLL}"
  log "  saved $RESULTS/T_${POLL} + receptor samples (solver time $DLATEST)"
done

# ----------------------------------------------------- STAGE 3: receptor table
log "STAGE 3  receptor table"
python3 "$TOOLS/receptor_table.py" --results "$RESULTS" --pollutants "$POLLUTANTS" \
        --triSurface "$DISP/constant/triSurface" | tee "$RESULTS/receptor_table.txt"

log "DONE. flow=$FLOWTIME -> $RESULTS/ (T_CO,T_NOx [kg/m^3], receptor_table.csv [ug/m^3])"
#------------------------------------------------------------------------------
