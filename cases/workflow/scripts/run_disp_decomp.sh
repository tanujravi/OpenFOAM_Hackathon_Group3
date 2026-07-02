#!/bin/bash
# One (hour,pollutant) dispersion in its OWN folder, reusing the frozen decomposed
# mesh (symlink) + this hour's frozen flow fields. Only T is scattered (decomposePar
# -fields). Receptors come from the parallel FOs. T stashed as 0/T_<POLL> (decomposed).
# args: HOUR POLL MASTER DISPSRC TOOLS WORK NP DT SCENARIO PYTHON
set -euo pipefail
HOUR="$1"; POLL="$2"; MASTER="$3"; DISPSRC="$4"; TOOLS="$5"; WORK="$6"; NP="$7"; DT="${8:-1.0}"; SCEN="${9:-reference}"; PY="${10:-python3}"
DDIR="$WORK/disp/h$HOUR/$POLL"; FDIR="$WORK/flow/h$HOUR"
[ -d "$FDIR/processor0" ] || { echo "ERROR: flow for hour $HOUR not found ($FDIR). Run the flow first."; exit 1; }
FL=$(cd "$FDIR" && foamListTimes -processor -latestTime 2>/dev/null | tail -1)
[ -n "$FL" ] && [ "$FL" != "0" ] || { echo "ERROR: flow h$HOUR has no converged time."; exit 1; }

rm -rf "$DDIR"; mkdir -p "$DDIR/constant" "$DDIR/geo"
cp -r "$DISPSRC/system" "$DDIR/system"
cp -r "$DISPSRC/constant/triSurface" "$DDIR/constant/"
cp -r "$DISPSRC/0" "$DDIR/0"
for f in transportProperties fvOptions; do [ -f "$DISPSRC/constant/$f" ] && cp "$DISPSRC/constant/$f" "$DDIR/constant/"; done
cp "$MASTER/geo/streets_face_segments.csv" "$DDIR/geo/"
ln -s "$(readlink -f "$MASTER/constant/polyMesh")" "$DDIR/constant/polyMesh"      # serial mesh (for -fields)
for d in "$MASTER"/processor*; do p=$(basename "$d"); mkdir -p "$DDIR/$p/0"
  ln -s "$(readlink -f "$MASTER/$p/constant")" "$DDIR/$p/constant"               # decomposed mesh + cellZones
  cp "$FDIR/$p/$FL/U"   "$DDIR/$p/0/U"                                           # frozen carrier (decomposed)
  cp "$FDIR/$p/$FL/phi" "$DDIR/$p/0/phi"
  [ -f "$FDIR/$p/$FL/nut" ] && cp "$FDIR/$p/$FL/nut" "$DDIR/$p/0/nut"
done

"$PY" "$TOOLS/set_emissions.py" --case "$DDIR" --pollutant "$POLL" --hour "$HOUR" --scenario "$SCEN" --DT "$DT"

cd "$DDIR"
foamDictionary -entry numberOfSubdomains -set "$NP" system/decomposeParDict >/dev/null
decomposePar -fields -force > log.decompfields 2>&1            # scatter only 0/T
srun scalarTransportFoam -parallel > log.scalar 2>&1
dl=$(foamListTimes -processor -latestTime 2>/dev/null | tail -1)
if [ -n "$dl" ] && [ "$dl" != "0" ]; then
  for p in processor*; do [ -f "$p/$dl/T" ] && mv "$p/$dl/T" "$p/0/T_${POLL}"; done   # keep snapshot, decomposed
fi
echo "disp h$HOUR $POLL done -> $DDIR (snapshot 0/T_${POLL}, decomposed)"
