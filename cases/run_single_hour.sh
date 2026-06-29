#!/bin/bash
#SBATCH --job-name=disp
#SBATCH --account=f202500001hpcvlabepicurex
#SBATCH --partition=normal-x86
#SBATCH --nodes=1
#SBATCH --ntasks=128
#SBATCH --mem=0                # full node RAM
#SBATCH --time=02:00:00
#SBATCH --error=logs/disp.err
#SBATCH --output=logs/disp.out
# =============================================================================
#  Single-hour DISPERSION driver. Prereq: the flow is solved in $FLOW (job_flow.sh),
#  which carves the 'streets' patch BEFORE solving so the frozen U/phi/nut already
#  match the Terrain+streets mesh.
#
#  TWO handoff modes, auto-detected from whether $FLOW is left decomposed:
#
#   * DECOMPOSED  (if $FLOW/processor0 exists)  -- for the big mesh.
#       Reuse the flow's decomposed mesh + frozen fields. The expensive mesh
#       decomposition (scotch) is NEVER repeated. Per (hour,scenario,pollutant)
#       only the changing T field is distributed onto the existing decomposition
#       with `decomposePar -fields` (no scotch, no mesh partition). Receptor values
#       come from the parallel surfaceFieldValue FOs, so the volume T need not be
#       reconstructed (set RECONSTRUCT_T=1 to also reconstruct T for ParaView).
#       NEEDS a serial constant/polyMesh in $FLOW (decomposePar -fields reads it):
#       reconstruct the mesh ONCE with redistributePar -reconstruct -constant.
#       The SBATCH ntasks MUST equal the flow's decomposition count.
#
#   * SERIAL  (fallback, no processor0)  -- original path; fine for the small domain.
#
#  Config via env: HOUR=1 SCENARIO=reference POLLUTANTS="CO NOx" DT=1.0
#                  FLOW=./flowCaseBig DISP=./dispersionCaseBig  RECONSTRUCT_T=0
#  Run:  HOUR=8 SCENARIO=S2 FLOW=./flowCaseBig DISP=./dispersionCaseBig sbatch run_single_hour.sh
# =============================================================================
set -e
module load OpenFOAM/v2512-foss-2025a 2>/dev/null || true
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc" 2>/dev/null || true
ROOT="${SLURM_SUBMIT_DIR:-$(cd "$(dirname "$0")" && pwd)}"; cd "$ROOT"
echo "[run_single_hour] ROOT=$ROOT"

HOUR=${HOUR:-1}; SCENARIO=${SCENARIO:-reference}; POLLUTANTS=${POLLUTANTS:-"CO NOx"}
DT=${DT:-1.0}; RECONSTRUCT_T=${RECONSTRUCT_T:-0}
FLOW=${FLOW:-./flowCase}; DISP=${DISP:-./dispersionCase}; TOOLS=${TOOLS:-./tools}
RESULTS="./results/h${HOUR}_${SCENARIO}"; mkdir -p "$RESULTS" logs
log(){ echo "[$(date +%H:%M:%S)] $*"; }

[ -d "$FLOW/constant/polyMesh" ] || { echo "ERROR: no mesh dir in $FLOW."; exit 1; }
grep -qE "^[[:space:]]*streets$" "$FLOW/constant/polyMesh/boundary" 2>/dev/null \
  || grep -qrE "^[[:space:]]*streets$" "$FLOW"/processor0/constant/polyMesh/boundary 2>/dev/null \
  || { echo "ERROR: no 'streets' patch in $FLOW mesh (run job_flow.sh)."; exit 1; }

if [ -d "$FLOW/processor0" ]; then MODE=decomposed; else MODE=serial; fi
log "handoff mode: $MODE   (FLOW=$FLOW  DISP=$DISP)"

# =============================================================================
if [ "$MODE" = "decomposed" ]; then
  # --------------------- DECOMPOSED handoff (big mesh) -----------------------
  NP=$(ls -d "$FLOW"/processor* 2>/dev/null | wc -l)
  FLOWTIME=${FLOWTIME:-$(foamListTimes -case "$FLOW" -processor -latestTime 2>/dev/null | tail -1)}
  [ -n "$FLOWTIME" ] && [ "$FLOWTIME" != "0" ] || { echo "ERROR: $FLOW has no converged decomposed time."; exit 1; }
  [ -f "$FLOW/processor0/$FLOWTIME/U" ] || { echo "ERROR: $FLOW/processor0/$FLOWTIME/U missing."; exit 1; }
  log "reuse $FLOW decomposition: $NP procs, frozen flow at t=$FLOWTIME (no re-decompose)"

  # decomposePar -fields scatters the SERIAL T, so it needs a serial mesh to read.
  if [ ! -f "$FLOW/constant/polyMesh/points" ]; then
    echo "ERROR: $FLOW has no SERIAL mesh (constant/polyMesh/points) -- decomposePar -fields needs it."
    echo "       Reconstruct the flow mesh ONCE (memory-distributed):"
    echo "         (cd $FLOW && srun redistributePar -reconstruct -constant -parallel)"
    exit 1
  fi
  # serial mesh + streets map into DISP (idempotent)
  if [ ! -f "$DISP/constant/polyMesh/points" ]; then
    rm -rf "$DISP/constant/polyMesh"; cp -r "$FLOW/constant/polyMesh" "$DISP/constant/"
  fi
  mkdir -p "$DISP/geo"; cp -f "$FLOW/geo/streets_face_segments.csv" "$DISP/geo/"
  # decomposed mesh + addressing into DISP (once)
  if [ ! -d "$DISP/processor0/constant/polyMesh" ]; then
    log "  (first run) cloning decomposed mesh + addressing from $FLOW"
    for d in "$FLOW"/processor*; do p=$(basename "$d")
      mkdir -p "$DISP/$p/constant"; cp -r "$FLOW/$p/constant/." "$DISP/$p/constant/"
    done
  fi
  # decomposePar -fields checks numberOfSubdomains == existing processor count
  foamDictionary -entry numberOfSubdomains -set "$NP" "$DISP/system/decomposeParDict" >/dev/null

  # this hour's frozen carrier fields, straight into the decomposed time 0 (per processor)
  for d in "$FLOW"/processor*; do p=$(basename "$d"); mkdir -p "$DISP/$p/0"
    cp "$FLOW/$p/$FLOWTIME/U"   "$DISP/$p/0/U"
    cp "$FLOW/$p/$FLOWTIME/phi" "$DISP/$p/0/phi"
    [ -f "$FLOW/$p/$FLOWTIME/nut" ] && cp "$FLOW/$p/$FLOWTIME/nut" "$DISP/$p/0/nut"
  done

  for POLL in $POLLUTANTS; do
    log "STAGE 2  $POLL  (scenario=$SCENARIO hour=$HOUR) [decomposed]"
    python3 "$TOOLS/set_emissions.py" --case "$DISP" --pollutant "$POLL" \
            --hour "$HOUR" --scenario "$SCENARIO" --DT "$DT" | tee "$ROOT/logs/emit_$POLL.log"
    ( cd "$DISP"
      # clear previous SOLVER time dirs (keep 0/ + constant -> keeps already-stashed T_<otherPoll>)
      for p in processor*; do find "$p" -mindepth 1 -maxdepth 1 -type d ! -name 0 ! -name constant -exec rm -rf {} + ; done
      rm -rf postProcessing
      decomposePar -fields -force > "$ROOT/logs/disp_${POLL}_decompfields.log" 2>&1   # scatter only 0/T
      srun scalarTransportFoam -parallel > "$ROOT/logs/disp_${POLL}_solve.log" 2>&1
      # Stash the converged field under its own name in time 0 of the DECOMPOSED case,
      # so EVERY pollutant stays visualisable together (ParaView 'Decomposed Case', time 0).
      dl=$(foamListTimes -processor -latestTime 2>/dev/null | tail -1)
      if [ -n "$dl" ] && [ "$dl" != "0" ]; then
        for p in processor*; do [ -f "$p/$dl/T" ] && mv "$p/$dl/T" "$p/0/T_${POLL}"; done
      fi
      for p in processor*; do find "$p" -mindepth 1 -maxdepth 1 -type d ! -name 0 ! -name constant -exec rm -rf {} + ; done )
    rm -rf "$RESULTS/pp_${POLL}"; cp -r "$DISP/postProcessing" "$RESULTS/pp_${POLL}"
    log "  $POLL done: receptors -> $RESULTS/pp_${POLL} ; field kept as 0/T_${POLL} (decomposed)"
  done
  log "VISUALISE both pollutants: open $DISP on the DECOMPOSED case (ParaView Case Type 'Decomposed'),"
  log "  at time 0 colour by T_CO / T_NOx -- no reconstruct needed (each is a global field across processor*/)."

# =============================================================================
else
  # --------------------- SERIAL handoff (small mesh, original) ---------------
  NPROCS=${NPROCS:-128}
  FLOWTIME=${FLOWTIME:-$(foamListTimes -case "$FLOW" -latestTime)}
  [ -n "$FLOWTIME" ] && [ "$FLOWTIME" != "0" ] || { echo "ERROR: $FLOW has no converged time dir."; exit 1; }
  [ -f "$FLOW/$FLOWTIME/U" ] || { echo "ERROR: $FLOW/$FLOWTIME/U missing."; exit 1; }
  log "reuse $FLOW serial mesh + frozen flow at t=$FLOWTIME"
  rm -rf "$DISP/constant/polyMesh"; cp -r "$FLOW/constant/polyMesh" "$DISP/constant/"
  cp "$FLOW/$FLOWTIME/U" "$DISP/0/U"; cp "$FLOW/$FLOWTIME/phi" "$DISP/0/phi"
  [ -f "$FLOW/$FLOWTIME/nut" ] && cp "$FLOW/$FLOWTIME/nut" "$DISP/0/nut"
  mkdir -p "$DISP/geo"; cp "$FLOW/geo/streets_face_segments.csv" "$DISP/geo/"

  for POLL in $POLLUTANTS; do
    log "STAGE 2  $POLL  (scenario=$SCENARIO hour=$HOUR) [serial]"
    python3 "$TOOLS/set_emissions.py" --case "$DISP" --pollutant "$POLL" \
            --hour "$HOUR" --scenario "$SCENARIO" --DT "$DT" | tee "$ROOT/logs/emit_$POLL.log"
    ( cd "$DISP"
      foamListTimes -rm > /dev/null 2>&1 || true
      rm -rf processor* postProcessing
      decomposePar -force > "$ROOT/logs/disp_${POLL}_decompose.log" 2>&1
      srun scalarTransportFoam -parallel > "$ROOT/logs/disp_${POLL}_solve.log" 2>&1
      reconstructPar -latestTime > "$ROOT/logs/disp_${POLL}_reconstruct.log" 2>&1
      rm -rf processor* )
    DLATEST=$(foamListTimes -case "$DISP" -latestTime)
    [ -n "$DLATEST" ] || { echo "ERROR: $DISP produced no time dir for $POLL."; exit 1; }
    cp "$DISP/$DLATEST/T" "$RESULTS/T_${POLL}"
    rm -rf "$RESULTS/pp_${POLL}"; cp -r "$DISP/postProcessing" "$RESULTS/pp_${POLL}"
    log "  saved $RESULTS/T_${POLL} + receptor samples (solver time $DLATEST)"
  done
fi

# ----------------------------------------------------- STAGE 3: receptor table
log "STAGE 3  receptor table"
python3 "$TOOLS/receptor_table.py" --results "$RESULTS" --pollutants "$POLLUTANTS" \
        --triSurface "$DISP/constant/triSurface" | tee "$RESULTS/receptor_table.txt"

log "DONE ($MODE). flow=$FLOWTIME -> $RESULTS/  (receptor_table.csv [ug/m^3])"
#------------------------------------------------------------------------------
