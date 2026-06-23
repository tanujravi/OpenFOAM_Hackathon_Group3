#!/bin/bash
# Remove everything left over from the snappyHexMesh run that would interfere
# with runflow.sh, while keeping the reconstructed mesh and initial conditions.
#
# Safe to run immediately after runallgeo.sh finishes.
# After this script: constant/polyMesh/ and 0/ are untouched; just run runflow.sh.

set -euo pipefail

DRY=0
[ "${1:-}" = "-dry-run" ] && DRY=1

remove() {
    for t in "$@"; do
        if [ -e "$t" ] || compgen -G "$t" > /dev/null 2>&1; then
            for match in $t; do
                [ -e "$match" ] || continue
                if [ "$DRY" -eq 1 ]; then
                    echo "  [dry] rm -rf $match"
                else
                    echo "  removing $match"
                    rm -rf "$match"
                fi
            done
        fi
    done
}

cd "$(dirname "$0")"
echo "=== prep_flow: clearing post-mesh artefacts ==="

# Parallel processor dirs from snappyHexMesh — runflow.sh redoes decomposePar
echo "-- processor dirs --"
remove processor*

# snappyHexMesh root-level time dirs (castellated=1, snapped=2)
echo "-- snappy time dirs (1/ 2/) --"
remove 1 2

# Stale postProcessing output from any previous flow run
echo "-- postProcessing --"
remove postProcessing

echo "=== done — mesh in constant/polyMesh/ and 0/ are untouched ==="
echo "    → submit the flow run with:  sbatch runflow.sh"
