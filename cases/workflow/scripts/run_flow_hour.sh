#!/bin/bash
# Steady ABL flow for ONE hour on the shared carved mesh; export frozen U/phi/nut.
# The mesh (constant/polyMesh) is SYMLINKED from the carved flow case, so the 24
# per-hour runs don't each duplicate the mesh.
#
# ARM-safe: the MESH is NEVER decomposed or reconstructed in serial. Its
# decomposition is built ONCE (e.g. flowCase*/runallgeo.sh) and shared by symlink;
# only FIELDS move -- decomposePar -fields scatters the 0/ fields onto the existing
# decomposition (no scotch), and redistributePar -reconstruct -parallel gathers the
# frozen fields back (NEVER serial reconstructPar / reconstructParMesh).
# args: HOUR FLOWCASE TOOLS WORK NPROCS PARALLEL ITERS2 PYTHON
set -euo pipefail
HOUR="$1"; FLOW="$2"; TOOLS="$3"; WORK="$4"; NP="$5"; PAR="$6"; IT2="$7"; PY="${8:-python3}"
die(){ echo "ERROR: $*" >&2; exit 1; }

MESH="$(readlink -f "$FLOW/constant/polyMesh")"
[ -d "$MESH" ] || die "no mesh at $FLOW/constant/polyMesh (mesh first)"
grep -qE '^[[:space:]]*streets$' "$MESH/boundary" || die "'streets' not carved; run carve_mesh"

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

if [ "$PAR" = "true" ]; then
  # ---- parallel, fully decomposed (ARM memory-safe): mesh stays decomposed ----
  [ -d "$FLOW/processor0/constant/polyMesh" ] || die "$FLOW not pre-decomposed; decompose the mesh ONCE (runallgeo.sh)"
  [ -f "$FLOW/constant/polyMesh/points" ]     || die "$FLOW has no serial mesh (needed for decomposePar -fields)"
  npr=$(ls -d "$FLOW"/processor* 2>/dev/null | wc -l)
  [ "$npr" -eq "$NP" ] || die "NP=$NP but $FLOW has $npr processor dirs; NP must equal the mesh decomposition"
  for d in "$FLOW"/processor*; do
    p=$(basename "$d"); mkdir -p "$HDIR/$p"
    ln -s "$(readlink -f "$FLOW/$p/constant")" "$HDIR/$p/constant"   # decomposed mesh + cellZones
  done
  decomposePar -fields -force > log.decompfields 2>&1               # scatter ONLY 0/ fields (no scotch)
  # Stage A: 1st-order warm-up (bounded)
  cp system/fvSchemes_1storder system/fvSchemes
  srun -n "$NP" potentialFoam -parallel > log.potentialFoam       2>&1 || true
  srun -n "$NP" simpleFoam    -parallel > log.simpleFoam.1storder 2>&1
  # Stage B: 2nd-order restart (accurate)
  cp system/fvSchemes_2ndorder system/fvSchemes
  latest=$(foamListTimes -processor -latestTime 2>/dev/null | tail -1)
  foamDictionary -entry endTime -set $((latest + IT2)) system/controlDict >/dev/null
  srun -n "$NP" simpleFoam -parallel > log.simpleFoam.2ndorder 2>&1
  # gather frozen fields in PARALLEL (never serial reconstructPar/reconstructParMesh)
  srun -n "$NP" redistributePar -reconstruct -latestTime -parallel > log.redistribute 2>&1
  latest=$(foamListTimes -latestTime 2>/dev/null | tail -1)
else
  # ---- serial (small domain / x86): no decomposition at all ----
  cp system/fvSchemes_1storder system/fvSchemes
  potentialFoam > log.potentialFoam       2>&1 || true
  simpleFoam    > log.simpleFoam.1storder 2>&1
  cp system/fvSchemes_2ndorder system/fvSchemes
  latest=$(foamListTimes -latestTime)
  foamDictionary -entry endTime -set $((latest + IT2)) system/controlDict
  simpleFoam > log.simpleFoam.2ndorder 2>&1
  latest=$(foamListTimes -latestTime)
fi

[ -n "$latest" ] || die "hour $HOUR produced no flow time dir"
mkdir -p frozen
cp "$latest/U"   frozen/U
cp "$latest/phi" frozen/phi
[ -f "$latest/nut" ] && cp "$latest/nut" frozen/nut || true
echo "flow_hour: h$HOUR done (latest=$latest) -> $HDIR/frozen"
