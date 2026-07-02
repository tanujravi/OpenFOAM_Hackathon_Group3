#!/bin/bash
# =====================================================================
# run_export_and_collect.sh
# ---------------------------------------------------------------------
# Two stages, for the air-quality PODI pipeline on an HPC cluster:
#
#   STAGE 1  export : run `foamToNumpy -parallel` on every decomposed
#                     CO/NOx OpenFOAM case  ->  writes <case>/exported_data/*.npy
#   STAGE 2  collect: run collect_cases.py  ->  parameters.csv + staging/
#
# Submit:   sbatch run_export_and_collect.sh
# Or run directly on an interactive node:   bash run_export_and_collect.sh
# =====================================================================

#SBATCH --job-name=foam2numpy
#SBATCH --account=f202500001hpcvlabepicurea
#SBATCH --partition=normal-arm
#SBATCH --nodes=8                  # 384 ranks / 128 per node = 3 nodes
#SBATCH --ntasks=384              # MUST equal the case decomposition (processor* count)
#SBATCH --ntasks-per-node=48     # node limit
#SBATCH --time=01:00:00
#SBATCH --output=foam2numpy.out
#SBATCH --error=foam2numpy.err

set -euo pipefail
set +u
# CRITICAL: purge inherited modules first. This job is submitted from an x86
# login node but runs on ARM (normal-arm) nodes. Without a purge, the x86
# module state (LOADEDMODULES, EBROOTGCCCORE, /eb/x86_64/* in LD_LIBRARY_PATH)
# is carried into the ARM job. `module load GCC` then becomes a no-op for the
# arch switch, EBROOTGCCCORE stays pointed at the x86 GCCcore, and foamToNumpy
# falls back to the ancient system /lib64/libstdc++.so.6 -> GLIBCXX_3.4.29/3.4.32
# and CXXABI_1.3.15 "not found". Purging forces a clean ARM-only environment.
module --force purge 2>/dev/null || module purge 2>/dev/null || true
module load OpenFOAM/v2512-foss-2025a
module load SciPy-bundle/2025.06-gfbf-2025a   # brings Python 3.13 + numpy/scipy
module load PyYAML/6.0.2-GCCcore-14.2.0       # 'import yaml' for config parsing (not in SciPy-bundle)
source "$FOAM_INST_DIR/OpenFOAM-v2512/etc/bashrc"
module load GCC/14.2.0                          # GCC 14.2 libstdc++ (GLIBCXX_3.4.32) after bashrc
set -u

# ----------------------------- config -------------------------------- #
CONFIG="${CONFIG:-config.yaml}"    # single source of truth (also read by collector)
DATADIR="exported_data"            # foamToNumpy output subdir (per case)
FORCE="${FORCE:-0}"                # 1 = re-export even if output exists
MPIRUN="${MPIRUN:-srun}"         # set MPIRUN=srun if your site requires it
EXPORT_TIME="${EXPORT_TIME:-0}"    # time directory to export ("0", a value, or "latest")

# Transported scalar field name inside each pollutant case.
# Folder (CO/NOx) is the key; value is the OpenFOAM field actually solved for.
declare -A FIELD=( [CO]="T_CO" [NOx]="T_NOx" )
# --------------------------------------------------------------------- #

# ---- pull root + scenario folder list from config.yaml -------------- #
[[ -f "$CONFIG" ]] || { echo "ERROR: config not found: $CONFIG"; exit 1; }
CFG_ROOT=$(python3 -c "import yaml;print(yaml.safe_load(open('$CONFIG')).get('root','.'))")
ROOT="${ROOT:-$CFG_ROOT}"          # env ROOT overrides; else config 'root'; else '.'

SCENARIOS=()
while IFS= read -r s; do [[ -n "$s" ]] && SCENARIOS+=("$s"); done < <(
    python3 -c "import yaml;print('\n'.join(yaml.safe_load(open('$CONFIG'))['scenarios'].keys()))"
)
(( ${#SCENARIOS[@]} > 0 )) || { echo "ERROR: no 'scenarios' in $CONFIG"; exit 1; }
echo "Scenario folders from config: ${SCENARIOS[*]}"

# ---- OpenFOAM environment (ADJUST to your cluster) ------------------ #
# module load OpenFOAM/v2312
# source "$FOAM_ETC/bashrc"   ||  source "$WM_PROJECT_DIR/etc/bashrc"
command -v foamToNumpy >/dev/null 2>&1 || {
    echo "ERROR: foamToNumpy not on PATH. Load the OpenFOAM module and build the utility first."
    exit 1
}

# ---- write a foamToNumpyDict for one case --------------------------- #
write_dict() {   # $1 = case dir, $2 = field name, $3 = export time
    cat > "$1/system/foamToNumpyDict" <<EOF
FoamFile { version 2.0; format ascii; class dictionary; object foamToNumpyDict; }
dataDir       ${DATADIR};
fields        { names ($2); dataType float64; }
exportData    { cellCentre false; cellVolumes true; writeTimes false; dataType float32; }
storageOrder  F;
time          { startTime $3; endTime $3; every 1; }
EOF
}

# ---- export one pollutant case -------------------------------------- #
export_one() {
    local case="$1" pol="$2"
    local field="${FIELD[$pol]:-$pol}"

    [[ -d "$case/system" ]]      || { echo "  [skip] no system/ in $case"; return; }
    [[ -d "$case/processor0" ]]  || { echo "  [skip] not decomposed: $case"; return; }
    local nproc; nproc=$(find "$case" -maxdepth 1 -type d -name 'processor*' | wc -l)

    if [[ -d "$case/$DATADIR" && "$FORCE" != "1" ]]; then
        echo "  [have] $case/$DATADIR (set FORCE=1 to redo)"; return
    fi
    [[ "$FORCE" == "1" ]] && rm -rf "$case/$DATADIR"

    # time directory to export (default "0"; "latest" auto-detects)
    local t="$EXPORT_TIME"
    if [[ "$t" == "latest" ]]; then
        t=$(ls -1 "$case/processor0" | grep -E '^[0-9]+(\.[0-9]+)?$' | sort -g | tail -1 || true)
    fi
    [[ -n "$t" && -d "$case/processor0/$t" ]] || {
        echo "  [skip] time '$EXPORT_TIME' not in $case/processor0"; return; }

    if [[ ! -f "$case/processor0/$t/$field" ]]; then
        echo "  [warn] field '$field' not in processor0/$t of $case; available:"
        ls "$case/processor0/$t" | sed 's/^/        /'
        echo "         -> fix the FIELD[] mapping; skipping."
        return
    fi

    write_dict "$case" "$field" "$t"
    echo "  [export] $(basename "$(dirname "$case")")/$(basename "$case")  field=$field  nproc=$nproc  time=$t"
    ( cd "$case" && "$MPIRUN" -n "$nproc" foamToNumpy -parallel ) \
        || echo "  [FAIL] foamToNumpy in $case"
}

# ============================ STAGE 1 ================================ #
echo "=== STAGE 1: foamToNumpy export (ROOT=$ROOT) ==="
shopt -s nullglob
n_cases=0
for scen in "${SCENARIOS[@]}"; do
    sdir="$ROOT/$scen"
    [[ -d "$sdir" ]] || { echo "[skip] scenario folder not found: $sdir"; continue; }
    for case in "$sdir"/runs_pod*/disp/h*/*/ ; do
        case="${case%/}"
        pol="$(basename "$case")"
        export_one "$case" "$pol"
        n_cases=$((n_cases + 1))
    done
done
echo "Processed $n_cases pollutant case(s)."

# ============================ STAGE 2 ================================ #
echo ""
echo "=== STAGE 2: collect into parameters.csv + staging ==="
python3 collect_cases.py "$CONFIG"

echo ""
echo "=== DONE.  Next: run podi_linear.py per pollutant (see commands above). ==="
