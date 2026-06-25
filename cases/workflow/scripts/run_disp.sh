#!/bin/bash
# Dispersion for ONE (hour, scenario, pollutant) on the frozen flow; sample receptors.
# Shares the carved mesh (symlink) + frozen U/phi/nut from the hour's flow run.
# args: HOUR SCN POL FLOWCASE DISPCASE TOOLS WORK NPROCS PARALLEL DT PYTHON
set -euo pipefail
HOUR="$1"; SCN="$2"; POL="$3"; FLOW="$4"; DISP="$5"; TOOLS="$6"; WORK="$7"; NP="$8"; PAR="$9"; DT="${10}"; PY="${11:-python3}"

FROZEN="$WORK/flow/h$HOUR/frozen"
[ -f "$FROZEN/U" ] || { echo "ERROR: frozen flow for h$HOUR missing ($FROZEN/U)"; exit 1; }
MESH="$(readlink -f "$FLOW/constant/polyMesh")"

DDIR="$WORK/disp/h$HOUR/$SCN/$POL"
rm -rf "$DDIR"; mkdir -p "$DDIR/constant" "$DDIR/geo"
cp -r "$DISP/0" "$DDIR/0"
cp -r "$DISP/system" "$DDIR/system"
for f in "$DISP"/constant/*; do
  b=$(basename "$f")
  if [ "$b" = polyMesh ]; then ln -s "$MESH" "$DDIR/constant/polyMesh"
  else cp -r "$f" "$DDIR/constant/"; fi
done
cp "$FROZEN/U" "$DDIR/0/U"; cp "$FROZEN/phi" "$DDIR/0/phi"
[ -f "$FROZEN/nut" ] && cp "$FROZEN/nut" "$DDIR/0/nut" || true
cp "$FLOW/geo/streets_face_segments.csv" "$DDIR/geo/"

"$PY" "$TOOLS/set_emissions.py" --case "$DDIR" --pollutant "$POL" --hour "$HOUR" --scenario "$SCN" --DT "$DT"

cd "$DDIR"
sed -i "s/numberOfSubdomains [0-9]\+;/numberOfSubdomains $NP;/g" system/decomposeParDict
if [ "$PAR" = "true" ]; then
  decomposePar -force > log.decompose 2>&1
  srun -n "$NP" scalarTransportFoam -parallel > log.scalarTransportFoam 2>&1
  reconstructPar -latestTime > log.reconstruct 2>&1; rm -rf processor*
else
  scalarTransportFoam > log.scalarTransportFoam 2>&1
fi
cd - >/dev/null

"$PY" "$TOOLS/collect_receptors.py" --disp "$DDIR" --triSurface "$DISP/constant/triSurface" \
      --hour "$HOUR" --scenario "$SCN" --pollutant "$POL" --out "$DDIR/receptors.csv"
echo "disp: h$HOUR $SCN $POL done -> $DDIR/receptors.csv"
