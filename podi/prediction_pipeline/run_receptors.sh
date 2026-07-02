#!/bin/bash
# =====================================================================
# run_receptors.sh
# ---------------------------------------------------------------------
# Predict the 24-hour pollutant field for each scenario with the PODI
# models, reconstruct it into the decomposed OpenFOAM template with
# numpyToFoam, sample the 4 receptors with postProcess, and collect the
# receptor concentrations into a CSV.  Fields are deleted after each
# scenario -- only receptor values are kept.
#
# Decomposition is 384 -> numpyToFoam/postProcess need 384 MPI ranks:
#   8 x normal-arm nodes (48 cores each).  numpyToFoam is built for ARM too.
#
# Test one iteration first:
#   POLLUTANTS="CO" SCENARIOS="full" sbatch run_receptors.sh
# Full sweep (default = all):
#   sbatch run_receptors.sh
# =====================================================================
#SBATCH --job-name=podi_receptors
#SBATCH --account=f202500001hpcvlabepicurea
#SBATCH --partition=normal-arm
#SBATCH --nodes=8
#SBATCH --ntasks=384
#SBATCH --ntasks-per-node=48
#SBATCH --mem=0
#SBATCH --time=04:00:00
#SBATCH --output=receptors.out
#SBATCH --error=receptors.err

set -uo pipefail

DIR=/projects/F202500001HPCVLABEPICURE/tanuj/PODI/receptor_pipeline
PODI=/projects/F202500001HPCVLABEPICURE/tanuj/PODI
TPL=${TPL:-$DIR/template_case}
CONFIG=${CONFIG:-$PODI/config.yaml}
CSV=${CSV:-$DIR/receptor_results.csv}
RESULTS=${RESULTS:-$DIR/results}
PLOTS=${PLOTS:-$PODI/receptor_plots}
NHOURS=24

# scenario -> "G L"  (Reference + the three reductions)
declare -A GL=( [full]="1.0 1.0" [S1]="0.8 1.0" [S2]="0.6 1.0" [S3]="1.0 0.5" )
# pollutant -> model pickle ; field written into the case is always T
declare -A MODEL=( [CO]="$PODI/models/model_CO.pkl" [NOx]="$PODI/models/model_NOx.pkl" )

POLLUTANTS=${POLLUTANTS:-"CO NOx"}
SCENARIOS=${SCENARIOS:-"full S1 S2 S3"}

log(){ echo "[$(date +%H:%M:%S)] $*"; }

# ---- module environments (separate: OpenFOAM vs Python/SciPy) ------- #
# set +u: OpenFOAM's bashrc references unset vars; keep it subshell-local.
of_env() { set +u; module purge 2>/dev/null; module load OpenFOAM/v2512-foss-2025a 2>/dev/null || true
           source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc" 2>/dev/null || true; }
py_env() { set +u; module purge 2>/dev/null
           module load SciPy-bundle/2025.07-gfbf-2025b 2>/dev/null || true
           module load PyYAML/6.0.2-GCCcore-14.3.0 2>/dev/null || true
           module load matplotlib/3.10.5-gfbf-2025b 2>/dev/null || true
           export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-8} OPENBLAS_NUM_THREADS=${SLURM_CPUS_PER_TASK:-8}; }

# ---- template (build once) ------------------------------------------ #
if [ ! -d "$TPL/processor0/constant/polyMesh" ]; then
    log "building template case ..."
    bash "$DIR/build_template.sh"
fi
NP=$(ls -d "$TPL"/processor* | wc -l)
log "template ready: $NP processors  (SLURM ntasks=${SLURM_NTASKS:-?})"

mkdir -p "$RESULTS"
rm -f "$CSV"      # fresh master CSV for this run

for POLL in $POLLUTANTS; do
  MDL=${MODEL[$POLL]}
  [ -f "$MDL" ] || { log "SKIP $POLL: no model $MDL"; continue; }
  for SCEN in $SCENARIOS; do
    read -r G L <<< "${GL[$SCEN]}"
    log "==== $POLL / $SCEN  (G=$G L=$L) ===="

    # 1) predict 24-hour field stack -> template_case/data/T/*.npy
    rm -rf "$TPL/data"
    ( py_env; python3 "$DIR/predict_day.py" --model "$MDL" --config "$CONFIG" \
        --G "$G" --L "$L" --out-dir "$TPL/data" --field T ) || { log "predict FAILED"; exit 1; }

    # 2) reconstruct T at times 1..24 (parallel)
    ( of_env; cd "$TPL"
      for t in $(seq 1 $NHOURS); do rm -rf processor*/"$t"; done   # clean any prior fields
      rm -rf postProcessing
      srun numpyToFoam -parallel ) || { log "numpyToFoam FAILED"; exit 1; }

    # 3) sample the 4 receptors (controlDict functions{}) over times 1..24.
    #    -fields '(T)' makes postProcess LOAD T from disk into the registry so
    #    the surfaceFieldValue FOs can find it (else "field T not found").
    ( of_env; cd "$TPL"; srun postProcess -parallel -noZero -fields '(T)' ) || { log "postProcess FAILED"; exit 1; }

    # 4) collect receptor values -> master CSV, archive the tiny .dat set
    ( py_env; python3 "$DIR/parse_receptors.py" --case "$TPL" \
        --pollutant "$POLL" --scenario "$SCEN" --out-csv "$CSV" ) || { log "parse FAILED"; exit 1; }
    rm -rf "$RESULTS/${POLL}_${SCEN}"; cp -r "$TPL/postProcessing" "$RESULTS/${POLL}_${SCEN}"

    # 5) free the big temporaries before the next scenario
    ( cd "$TPL"; for t in $(seq 1 $NHOURS); do rm -rf processor*/"$t"; done; rm -rf postProcessing data )
    log "  $POLL/$SCEN done."
  done
done

# ---- plots ---------------------------------------------------------- #
log "plotting -> $PLOTS"
( py_env; python3 "$DIR/plot_receptors.py" --csv "$CSV" --out-dir "$PLOTS" ) || log "plotting FAILED"
log "ALL DONE. CSV=$CSV  plots=$PLOTS"
