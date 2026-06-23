#!/bin/bash
#SBATCH --job-name=oneHour
#SBATCH --account=f202500001hpcvlabepicurex
#SBATCH --partition=normal-x86
#SBATCH --nodes=1
#SBATCH --ntasks=96
#SBATCH --time=02:00:00
#SBATCH --error=logs/oneHour.err
#SBATCH --output=logs/oneHour.out
# =============================================================================
#  Single-hour driver: WIND (simpleFoam) -> DISPERSION (scalarTransportFoam) for
#  CO and NOx, one hour, one scenario, on an ALREADY-MESHED initialCase, then
#  sample CO/NOx at the four ROI receptors and write a results table.
#
#  Mesh ONCE first with runallgeo.sh. Stages:
#    1. set hourly wind, run simpleFoam (parallel)
#    2. copy frozen mesh+U/phi/nut into dispersionCase, carve 'streets' patch
#    3. per pollutant: inject emission, scalarTransportFoam (receptor FOs sample
#       T at the 4 ROI surfaces), save field + postProcessing
#    4. receptor_table.py -> results/.../receptor_table.csv  (ug/m^3)
#
#  Config via env: HOUR=0 SCENARIO=reference POLLUTANTS="CO NOx" HALFWIDTH=6.0
#                  NPROCS=96 SKIP_FLOW=0
#  Run:  sbatch run_single_hour.sh   |   HOUR=8 SCENARIO=S2 bash run_single_hour.sh
# =============================================================================
set -e
module load OpenFOAM/v2512-foss-2025a 2>/dev/null || true
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc" 2>/dev/null || true

ROOT="$(cd "$(dirname "$0")" && pwd)"; cd "$ROOT"
HOUR=${HOUR:-0}; SCENARIO=${SCENARIO:-reference}; POLLUTANTS=${POLLUTANTS:-"CO NOx"}
HALFWIDTH=${HALFWIDTH:-6.0}; NPROCS=${NPROCS:-96}; SKIP_FLOW=${SKIP_FLOW:-0}
FLOW=initialCase; DISP=dispersionCase; TOOLS=tools
RESULTS="results/h${HOUR}_${SCENARIO}"; mkdir -p "$RESULTS" logs
log(){ echo "[$(date +%H:%M:%S)] $*"; }

[ -f "$FLOW/constant/polyMesh/faces" ] || { echo "ERROR: no mesh in $FLOW -- run runallgeo.sh first."; exit 1; }

# ---------------------------------------------------------------- STAGE 1: flow
if [ "$SKIP_FLOW" != "1" ]; then
  log "STAGE 1  wind hour=$HOUR -> simpleFoam ($NPROCS ranks)"
  python3 "$TOOLS/set_wind.py" --case "$FLOW" --hour "$HOUR"
  ( cd "$FLOW"; rm -rf processor*
    decomposePar -force        > "$ROOT/logs/flow_decompose.log" 2>&1
    mpirun -np "$NPROCS" simpleFoam -parallel > "$ROOT/logs/flow_simpleFoam.log" 2>&1
    reconstructPar -latestTime > "$ROOT/logs/flow_reconstruct.log" 2>&1
    rm -rf processor* )
else
  log "STAGE 1  skipped (SKIP_FLOW=1)"
fi
LATEST=$(foamListTimes -case "$FLOW" -latestTime)
[ -n "$LATEST" ] || { echo "ERROR: $FLOW produced no time directory."; exit 1; }
log "flow converged at time=$LATEST"

# ----------------------------------------------- STAGE 2: prep dispersion + carve
log "STAGE 2  prepare dispersion (mesh + frozen fields + streets patch)"
rm -rf "$DISP/constant/polyMesh"; cp -r "$FLOW/constant/polyMesh" "$DISP/constant/"
cp "$FLOW/$LATEST/U" "$DISP/0/U"; cp "$FLOW/$LATEST/phi" "$DISP/0/phi"
[ -f "$FLOW/$LATEST/nut" ] && cp "$FLOW/$LATEST/nut" "$DISP/0/nut"
python3 "$TOOLS/make_street_patches.py" --case "$DISP" \
        --roads "$DISP/geo/snapped_road_segments_recentred.csv" \
        --half-width "$HALFWIDTH" | tee "$ROOT/logs/carve.log"
( cd "$DISP"; createPatch -overwrite > "$ROOT/logs/createPatch.log" 2>&1 )

# --------------------------------------------- STAGE 3: dispersion per pollutant
for POLL in $POLLUTANTS; do
  log "STAGE 3  $POLL  (scenario=$SCENARIO hour=$HOUR)"
  python3 "$TOOLS/set_emissions.py" --case "$DISP" --pollutant "$POLL" \
          --hour "$HOUR" --scenario "$SCENARIO" --DT 1.0 | tee "$ROOT/logs/emit_$POLL.log"
  ( cd "$DISP"
    foamListTimes -rm > /dev/null 2>&1 || true
    rm -rf processor* postProcessing
    decomposePar -force                     > "$ROOT/logs/disp_${POLL}_decompose.log" 2>&1
    mpirun -np "$NPROCS" scalarTransportFoam -parallel > "$ROOT/logs/disp_${POLL}_solve.log" 2>&1
    reconstructPar -latestTime              > "$ROOT/logs/disp_${POLL}_reconstruct.log" 2>&1
    rm -rf processor* )
  DLATEST=$(foamListTimes -case "$DISP" -latestTime)
  [ -n "$DLATEST" ] || { echo "ERROR: $DISP produced no time dir for $POLL."; exit 1; }
  cp "$DISP/$DLATEST/T" "$RESULTS/T_${POLL}"
  rm -rf "$RESULTS/pp_${POLL}"; cp -r "$DISP/postProcessing" "$RESULTS/pp_${POLL}"
  log "  saved $RESULTS/T_${POLL} + receptor samples (solver time $DLATEST)"
done

# ----------------------------------------------------- STAGE 4: receptor table
log "STAGE 4  receptor table"
python3 "$TOOLS/receptor_table.py" --results "$RESULTS" --pollutants "$POLLUTANTS" \
        --triSurface "$DISP/constant/triSurface" | tee "$RESULTS/receptor_table.txt"

log "DONE. flow=$LATEST  ->  $RESULTS/ (T_CO,T_NOx [kg/m^3], receptor_table.csv [ug/m^3])"
#------------------------------------------------------------------------------
