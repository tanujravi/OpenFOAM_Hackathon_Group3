#!/bin/bash
# Render dispersion figures headlessly with ParaView 6.0.1 pvbatch.
#   bash run_pv_figures.sh CASE LABEL [TRISURFACE] [OUT]
# CASE = a case dir (or .foam) holding constant/polyMesh + a time dir with T_CO/T_NOx.
set -euo pipefail
CASE="${1:?usage: run_pv_figures.sh CASE LABEL [TRISURFACE] [OUT]}"
LABEL="${2:-run}"
TRI="${3:-$CASE/constant/triSurface}"
OUT="${4:-figs/$LABEL}"
HERE="$(cd "$(dirname "$0")" && pwd)"
module load ParaView/6.0.1 2>/dev/null || module load ParaView 2>/dev/null || true  # adjust to your cluster
pvbatch "$HERE/pv_dispersion_figures.py" \
    --case "$CASE" --label "$LABEL" --fields T_CO T_NOx \
    --triSurface "$TRI" --out "$OUT"
echo "figures -> $OUT"
