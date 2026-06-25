#!/bin/bash
# Steady ABL flow for ONE hour on the shared carved mesh; export frozen U/phi/nut.
# The mesh (constant/polyMesh) is SYMLINKED from the carved flow case, so the 24
# per-hour runs don't each duplicate the ~1.7 M-cell mesh.
# args: HOUR FLOWCASE TOOLS WORK NPROCS PARALLEL ITERS2 PYTHON
set -euo pipefail
HOUR="$1"; FLOW="$2"; TOOLS="$3"; WORK="$4"; NP="$5"; PAR="$6"; IT2="$7"; PY="${8:-python3}"

MESH="$(readlink -f "$FLOW/constant/polyMesh")"
[ -d "$MESH" ] || { echo "ERROR: no mesh at $FLOW/constant/polyMesh (mesh first)"; exit 1; }
grep -qE '^[[:space:]]*streets$' "$MESH/boundary" || { echo "ERROR: 'streets' not carved; run carve_mesh"; exit 1; }

HDIR="$WORK/flow/h$HOUR"
rm -rf "$HDIR"; mkdir -p "$HDIR/constant"
cp -r "$FLOW/0" "$HDIR/0"
cp -r "$FLOW/system" "$HDIR/system"
for f in "$FLOW"/constant/*; do
  b=$(basename "$f")
  if [ "$b" = polyMesh ]; then ln -s "$MESH" "$HDIR/constant/polyMesh"
  else cp -r "$f" "$HDIR/constant/"; fi
done

"$PY" "$TOOLS/set_wind.py" --case "$HDIR" --hour "$HOUR"

cd "$HDIR"
sed -i "s/numberOfSubdomains [0-9]\+;/numberOfSubdomains $NP;/g" system/decomposeParDict
RUN(){ if [ "$PAR" = "true" ]; then srun -n "$NP" "$@" -parallel; else "$@"; fi; }

# Stage A: 1st-order warm-up (bounded)
cp system/fvSchemes_1storder system/fvSchemes
[ "$PAR" = "true" ] && decomposePar -force > log.decompose 2>&1 || true
RUN potentialFoam > log.potentialFoam       2>&1 || true
RUN simpleFoam    > log.simpleFoam.1storder 2>&1
# Stage B: 2nd-order restart (accurate)
cp system/fvSchemes_2ndorder system/fvSchemes
latest=$(foamListTimes -latestTime)
foamDictionary -entry endTime -set $((latest + IT2)) system/controlDict
RUN simpleFoam > log.simpleFoam.2ndorder 2>&1
if [ "$PAR" = "true" ]; then reconstructPar -latestTime > log.reconstruct 2>&1; rm -rf processor*; fi

latest=$(foamListTimes -latestTime)
[ -n "$latest" ] || { echo "ERROR: hour $HOUR produced no flow time dir"; exit 1; }
mkdir -p frozen
cp "$latest/U"   frozen/U
cp "$latest/phi" frozen/phi
[ -f "$latest/nut" ] && cp "$latest/nut" frozen/nut || true
echo "flow_hour: h$HOUR done (latest=$latest) -> $HDIR/frozen"
