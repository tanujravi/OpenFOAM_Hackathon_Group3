#!/bin/bash
#SBATCH --job-name=disp
#SBATCH --account=f202500001hpcvlabepicurex
#SBATCH --partition=normal-x86
#SBATCH --nodes=1
#SBATCH --ntasks=96
#SBATCH --time=02:00:00
#SBATCH --error=logs/disp.err
#SBATCH --output=logs/disp.out
# =============================================================================
#  Single-hour DISPERSION driver (assumes the flow is already converged).
#
#  Prereq: run the flow first in cases/flowCase (job_flow.sh) so it holds a
#  converged time dir with U / phi / nut. This script then, for one hour / one
#  scenario:
#    1. copy the frozen mesh + U/phi/nut into cases/dispersionCase (+ ASCII mesh)
#    2. carve the 'streets' patch (make_street_patches.py) -> createPatch
#    3. per pollutant: set per-segment emission -> scalarTransportFoam
#       (receptor function objects sample T at the 4 ROI surfaces)
#    4. receptor_table.py -> results/.../receptor_table.csv  (ug/m^3)
#
#  Config via env: HOUR=0 SCENARIO=reference POLLUTANTS="CO NOx" HALFWIDTH=6.0
#                  NPROCS=96  DT=1.0  FLOWTIME=latestTime
#  Run:  sbatch run_single_hour.sh   |   HOUR=8 SCENARIO=S2 bash run_single_hour.sh
# =============================================================================
set -e
module load OpenFOAM/v2512-foss-2025a 2>/dev/null || true
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc" 2>/dev/null || true

ROOT="$(cd "$(dirname "$0")" && pwd)"; cd "$ROOT"
HOUR=${HOUR:-0}; SCENARIO=${SCENARIO:-reference}; POLLUTANTS=${POLLUTANTS:-"CO NOx"}
HALFWIDTH=${HALFWIDTH:-6.0}; NPROCS=${NPROCS:-96}; DT=${DT:-1.0}
FLOW=cases/flowCase; DISP=cases/dispersionCase; TOOLS=tools
RESULTS="results/h${HOUR}_${SCENARIO}"; mkdir -p "$RESULTS" logs
log(){ echo "[$(date +%H:%M:%S)] $*"; }

[ -d "$FLOW/constant/polyMesh" ] || { echo "ERROR: no mesh in $FLOW -- run runallgeo.sh."; exit 1; }
FLOWTIME=${FLOWTIME:-$(foamListTimes -case "$FLOW" -latestTime)}
[ -n "$FLOWTIME" ] && [ "$FLOWTIME" != "0" ] || {
    echo "ERROR: $FLOW has no converged time dir (run the flow / job_flow.sh first)."; exit 1; }
[ -f "$FLOW/$FLOWTIME/U" ] || { echo "ERROR: $FLOW/$FLOWTIME/U missing."; exit 1; }
log "using frozen flow from $FLOW/$FLOWTIME"

# ----------------------------------------------- STAGE 1: prep dispersion + carve
log "STAGE 1  mesh + frozen fields -> $DISP, then carve streets"
rm -rf "$DISP/constant/polyMesh"
cp -r "$FLOW/constant/polyMesh" "$DISP/constant/"
cp "$FLOW/$FLOWTIME/U"   "$DISP/0/U"
cp "$FLOW/$FLOWTIME/phi" "$DISP/0/phi"
[ -f "$FLOW/$FLOWTIME/nut" ] && cp "$FLOW/$FLOWTIME/nut" "$DISP/0/nut"

# the carver needs an ASCII polyMesh; convert in place if it came out binary
if head -c 4000 "$DISP/constant/polyMesh/points" | grep -qi "format *binary"; then
    log "  polyMesh is binary -> foamFormatConvert to ASCII"
    foamDictionary -entry writeFormat -set ascii "$DISP/system/controlDict" >/dev/null 2>&1 || true
    ( cd "$DISP" && foamFormatConvert -constant > "$ROOT/logs/formatConvert.log" 2>&1 )
fi

python3 "$TOOLS/make_street_patches.py" --case "$DISP" \
        --roads "$DISP/geo/snapped_road_segments_recentred.csv" \
        --half-width "$HALFWIDTH" | tee "$ROOT/logs/carve.log"
( cd "$DISP"; createPatch -overwrite > "$ROOT/logs/createPatch.log" 2>&1 )
# createPatch may not propagate the new patch into the 0/ fields -> ensure it
python3 "$TOOLS/add_streets_bc.py" --case "$DISP" --fields U phi nut T | tee "$ROOT/logs/add_streets_bc.log"

# --------------------------------------------- STAGE 2: dispersion per pollutant
for POLL in $POLLUTANTS; do
  log "STAGE 2  $POLL  (scenario=$SCENARIO hour=$HOUR)"
  python3 "$TOOLS/set_emissions.py" --case "$DISP" --pollutant "$POLL" \
          --hour "$HOUR" --scenario "$SCENARIO" --DT "$DT" | tee "$ROOT/logs/emit_$POLL.log"
  ( cd "$DISP"
    foamListTimes -rm > /dev/null 2>&1 || true     # drop previous scalar solution
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

# ----------------------------------------------------- STAGE 3: receptor table
log "STAGE 3  receptor table"
python3 "$TOOLS/receptor_table.py" --results "$RESULTS" --pollutants "$POLLUTANTS" \
        --triSurface "$DISP/constant/triSurface" | tee "$RESULTS/receptor_table.txt"

log "DONE. flow=$FLOWTIME -> $RESULTS/ (T_CO,T_NOx [kg/m^3], receptor_table.csv [ug/m^3])"
#------------------------------------------------------------------------------
