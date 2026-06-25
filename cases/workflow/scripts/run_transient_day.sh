#!/bin/bash
# TRANSIENT day for ONE (scenario, pollutant): chain 24 hourly scalarTransportFoam
# segments on a SINGLE case. Each hour h: refresh the carrier U/phi/nut with that
# hour's frozen flow, set the streets emission gradient for (h,scenario,pollutant),
# and march 3600 s of REAL time -- so the pollutant T is carried over and
# accumulates across the day (the physics a quasi-steady sweep cannot capture).
# The flow itself stays piecewise-steady (hourly frozen fields); a fully transient
# flow is the heavier option noted in workflow/README.md.
#
# args: SCN POL FLOWCASE DISPCASE TOOLS WORK NPROCS PARALLEL DT DELTAT SPH TRANSDIR PYTHON
set -euo pipefail
SCN="$1"; POL="$2"; FLOW="$3"; DISP="$4"; TOOLS="$5"; WORK="$6"; NP="$7"; PAR="$8"
DT="$9"; DELTAT="${10}"; SPH="${11}"; TRANS="${12}"; PY="${13:-python3}"

MESH="$(readlink -f "$FLOW/constant/polyMesh")"
[ -d "$MESH" ] || { echo "ERROR: no carved mesh at $FLOW/constant/polyMesh"; exit 1; }

CDIR="$WORK/trans/$SCN/$POL"
rm -rf "$CDIR"; mkdir -p "$CDIR/constant" "$CDIR/geo"
cp -r "$DISP/0" "$CDIR/0"
cp -r "$DISP/system" "$CDIR/system"
for f in "$DISP"/constant/*; do
  b=$(basename "$f")
  if [ "$b" = polyMesh ]; then ln -s "$MESH" "$CDIR/constant/polyMesh"
  else cp -r "$f" "$CDIR/constant/"; fi
done
cp "$FLOW/geo/streets_face_segments.csv" "$CDIR/geo/"
# overlay TRANSIENT solver dicts (Euler ddt, runTime writing)
cp "$TRANS/controlDict.transient" "$CDIR/system/controlDict"
cp "$TRANS/fvSchemes.transient"   "$CDIR/system/fvSchemes"
( cd "$CDIR" && foamDictionary -entry deltaT -set "$DELTAT" system/controlDict >/dev/null )

COMBINED="$CDIR/receptors.csv"
echo "hour,scenario,pollutant,receptor,site,conc_ugm3" > "$COMBINED"

HOURS_N=24
for ((h=0; h<HOURS_N; h++)); do
  t0=$(( h * SPH )); t1=$(( (h+1) * SPH ))
  TD="$CDIR/$t0"                       # segment start time dir (0/ for h=0)
  [ -d "$TD" ] || { echo "ERROR: expected start dir $TD (previous segment did not produce it)"; exit 1; }

  # refresh the carrier flow for this hour
  cp "$WORK/flow/h$h/frozen/U"   "$TD/U"
  cp "$WORK/flow/h$h/frozen/phi" "$TD/phi"
  [ -f "$WORK/flow/h$h/frozen/nut" ] && cp "$WORK/flow/h$h/frozen/nut" "$TD/nut" || true
  # set this hour's emission gradient on the (carried-over) T at this time dir
  "$PY" "$TOOLS/set_emissions.py" --case "$CDIR" --field "$TD/T" \
        --pollutant "$POL" --hour "$h" --scenario "$SCN" --DT "$DT" >/dev/null

  ( cd "$CDIR"
    foamDictionary -entry startTime -set "$t0" system/controlDict >/dev/null
    foamDictionary -entry endTime   -set "$t1" system/controlDict >/dev/null
    if [ "$PAR" = "true" ]; then
      decomposePar -force -time "$t0" > "log.decompose.$t0" 2>&1
      srun -n "$NP" scalarTransportFoam -parallel > "log.scalar.$t0" 2>&1
      reconstructPar -latestTime > "log.reconstruct.$t0" 2>&1
      rm -rf processor*
    else
      scalarTransportFoam > "log.scalar.$t0" 2>&1
    fi )

  # sample receptors at end of this hour -> append rows tagged with hour h
  "$PY" "$TOOLS/collect_receptors.py" --disp "$CDIR" --triSurface "$DISP/constant/triSurface" \
        --hour "$h" --scenario "$SCN" --pollutant "$POL" --out "$CDIR/.row.csv" >/dev/null
  tail -n +2 "$CDIR/.row.csv" >> "$COMBINED"
done
rm -f "$CDIR/.row.csv"
echo "transient day done: $SCN/$POL -> $COMBINED ($(($(wc -l < "$COMBINED")-1)) rows)"
