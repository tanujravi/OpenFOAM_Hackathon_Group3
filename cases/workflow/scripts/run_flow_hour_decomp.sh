#!/bin/bash
# One hour's flow in its OWN folder, sharing the frozen decomposed mesh by SYMLINK
# (no copy, no re-decompose). Runs independently -> parallel-safe, no clobbering.
# args: HOUR MASTER TOOLS WORK NP IT2 PYTHON
set -euo pipefail
HOUR="$1"; MASTER="$2"; TOOLS="$3"; WORK="$4"; NP="$5"; IT2="${6:-2000}"; PY="${7:-python3}"
HDIR="$WORK/flow/h$HOUR"
[ -d "$MASTER/processor0/constant/polyMesh" ] || { echo "ERROR: $MASTER not decomposed."; exit 1; }
[ -f "$MASTER/constant/polyMesh/points" ] || { echo "ERROR: $MASTER has no serial mesh (needed for decomposePar -fields)."; exit 1; }

rm -rf "$HDIR"; mkdir -p "$HDIR/constant"
cp -r "$MASTER/system" "$HDIR/system"
cp -r "$MASTER/0" "$HDIR/0"
for f in transportProperties turbulenceProperties fvOptions; do
  [ -f "$MASTER/constant/$f" ] && cp "$MASTER/constant/$f" "$HDIR/constant/"
done
ln -s "$(readlink -f "$MASTER/constant/polyMesh")" "$HDIR/constant/polyMesh"      # serial mesh (for -fields)
for d in "$MASTER"/processor*; do p=$(basename "$d"); mkdir -p "$HDIR/$p"
  ln -s "$(readlink -f "$MASTER/$p/constant")" "$HDIR/$p/constant"               # decomposed mesh + addressing + cellZones
done

"$PY" "$TOOLS/set_wind.py" --case "$HDIR" --hour "$HOUR"

cd "$HDIR"
foamDictionary -entry numberOfSubdomains -set "$NP" system/decomposeParDict >/dev/null
decomposePar -fields -force > log.decompfields 2>&1            # scatter only the 0/ fields (no scotch)
cp system/fvSchemes_1storder system/fvSchemes
srun potentialFoam -parallel > log.potentialFoam        2>&1 || true
srun simpleFoam    -parallel > log.simpleFoam.1storder  2>&1
cp system/fvSchemes_2ndorder system/fvSchemes
latest=$(foamListTimes -processor -latestTime 2>/dev/null | tail -1)
foamDictionary -entry endTime -set $(( latest + IT2 )) system/controlDict >/dev/null
srun simpleFoam -parallel > log.simpleFoam.2ndorder 2>&1
echo "flow h$HOUR done -> $HDIR (latest=$(foamListTimes -processor -latestTime 2>/dev/null | tail -1))"
