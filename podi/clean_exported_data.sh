#!/bin/bash
# =====================================================================
# clean_exported_data.sh
# ---------------------------------------------------------------------
# Remove every `exported_data/` folder produced by foamToNumpy from the
# pollutant case folders under the scenarios listed in config.yaml.
#
# Case layout (same discovery as run_export_and_collect.sh):
#     <root>/<scenario>/runs_pod*/disp/h<N>/<pollutant>/exported_data/
#
# SAFETY: dry-run by default (only lists what would be removed).
#         Set CONFIRM=1 (or pass --force) to actually delete.
#
# Usage:
#     bash clean_exported_data.sh              # dry run, prints targets
#     CONFIRM=1 bash clean_exported_data.sh    # actually delete
#     bash clean_exported_data.sh --force      # actually delete
# =====================================================================
set -euo pipefail

# ----------------------------- config -------------------------------- #
CONFIG="${CONFIG:-config.yaml}"    # single source of truth
DATADIR="exported_data"            # foamToNumpy output subdir (per case)
CONFIRM="${CONFIRM:-0}"            # 1 = actually delete; 0 = dry run

[[ "${1:-}" == "--force" ]] && CONFIRM=1

# ---- pull root + scenario folder list from config.yaml -------------- #
[[ -f "$CONFIG" ]] || { echo "ERROR: config not found: $CONFIG"; exit 1; }
CFG_ROOT=$(python3 -c "import yaml;print(yaml.safe_load(open('$CONFIG')).get('root','.'))")
ROOT="${ROOT:-$CFG_ROOT}"          # env ROOT overrides; else config 'root'; else '.'

SCENARIOS=()
while IFS= read -r s; do [[ -n "$s" ]] && SCENARIOS+=("$s"); done < <(
    python3 -c "import yaml;print('\n'.join(yaml.safe_load(open('$CONFIG'))['scenarios'].keys()))"
)
(( ${#SCENARIOS[@]} > 0 )) || { echo "ERROR: no 'scenarios' in $CONFIG"; exit 1; }

echo "ROOT=$ROOT"
echo "Scenario folders from config: ${SCENARIOS[*]}"
(( CONFIRM == 1 )) && echo ">>> DELETE mode" || echo ">>> DRY RUN (set CONFIRM=1 or pass --force to delete)"
echo

# ---- find and remove exported_data folders -------------------------- #
shopt -s nullglob
n_found=0
n_removed=0
for scen in "${SCENARIOS[@]}"; do
    sdir="$ROOT/$scen"
    [[ -d "$sdir" ]] || { echo "[skip] scenario folder not found: $sdir"; continue; }
    for ed in "$sdir"/runs_pod*/disp/h*/*/"$DATADIR"/ ; do
        ed="${ed%/}"
        [[ -d "$ed" ]] || continue
        n_found=$((n_found + 1))
        if (( CONFIRM == 1 )); then
            rm -rf "$ed" && { echo "  [removed] $ed"; n_removed=$((n_removed + 1)); } \
                || echo "  [FAIL] could not remove $ed"
        else
            echo "  [would remove] $ed"
        fi
    done
done

echo
if (( CONFIRM == 1 )); then
    echo "Removed $n_removed of $n_found '$DATADIR' folder(s)."
else
    echo "Found $n_found '$DATADIR' folder(s). Nothing deleted (dry run)."
fi
