#!/bin/bash
# One-time: carve the 'streets' patch into the SHARED flow mesh (idempotent).
# Mirrors job_flow.sh's carve block so the 24h sweep reuses one carved mesh.
# args: FLOWCASE TOOLS HALFWIDTH PYTHON
set -euo pipefail
FLOW="$1"; TOOLS="$2"; HALF="$3"; PY="${4:-python3}"
cd "$FLOW"
if grep -qE '^[[:space:]]*streets$' constant/polyMesh/boundary 2>/dev/null; then
  echo "carve_mesh: 'streets' already present in $FLOW mesh; skipping"; exit 0
fi
if head -c 4000 constant/polyMesh/points | grep -qi 'format[[:space:]]*binary'; then
  foamFormatConvert -constant > log.formatConvert 2>&1 || true   # carver needs ASCII
fi
"$PY" "$TOOLS/make_street_patches.py" --case . \
      --roads geo/snapped_road_segments_recentred.csv --half-width "$HALF" > log.carve 2>&1
createPatch -overwrite > log.createPatch 2>&1
"$PY" "$TOOLS/add_streets_bc.py" --case . --fields U p k epsilon nut omega > log.addStreetsBC 2>&1
echo "carve_mesh: carved 'streets' into $FLOW (Terrain split)"
