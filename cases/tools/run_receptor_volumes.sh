#!/bin/bash
# Volume-average receptor concentrations from the EXISTING decomposed snapshots (NO re-solve):
# build cellZones once, then postProcess volFieldValue on each T_<poll> snapshot at time 0.
# A readFields FO loads the snapshot field (its FoamFile 'object' header still says T, so we
# fix that first). Output -> receptors_long.csv (the format make_report.py consumes).
# Run on the cluster (OpenFOAM sourced, inside an allocation). ONE scenario per call.
#
# Prereq (once): python3 make_receptor_zones.py --disp <DISP> --out <DISP>/system [--exclude-zone vegetationZone]
# args: MESH DISP DISPROOT OUTCSV [HOURS] [POLLUTANTS] [NP] [SCENARIO]
set -euo pipefail
MESH="$1"; DISP="$2"; DISPROOT="$3"; OUTCSV="$4"
HOURS="${5:-0,1,3,5,8,9,11,14,17,23}"; POLLS="${6:-CO NOx}"; NP="${7:-384}"; SCEN="${8:-reference}"
MAP="$DISP/system/receptor_zone_map.json"
for f in "$DISP/system/topoSetDict" "$DISP/system/receptorsVolume" "$MAP"; do
  [ -f "$f" ] || { echo "ERROR: missing $f -- run make_receptor_zones.py --disp $DISP --out $DISP/system first"; exit 1; }
done

# 1) (re)build the roi cellZones in the shared decomposed mesh (action new overwrites)
cp "$DISP/system/topoSetDict" "$MESH/system/topoSetDict"
( cd "$MESH" && srun -n "$NP" topoSet -parallel -dict system/topoSetDict > log.topoSet.roi 2>&1 )
echo "[topoSet] roi cellZones (re)built in $MESH -- cell counts in $MESH/log.topoSet.roi"

echo "hour,scenario,pollutant,receptor,site,conc_ugm3" > "$OUTCSV"
IFS=',' read -ra HRS <<< "$HOURS"
for h in "${HRS[@]}"; do
  for p in $POLLS; do
    D="$DISPROOT/h$h/$p"; F="T_$p"
    [ -d "$D/processor0" ] || { echo "  skip h$h $p (no $D)"; continue; }
    # Fix the FoamFile 'object' header (still says T). readFields reads the field by NAME,
    # so the mismatch is usually only a WARNING -> FIXHDR=0 skips this entirely (fastest,
    # zero rewrites). When needed, do it in PARALLEL and only on the header block (1,/^}/)
    # instead of the old serial per-processor whole-file rewrite.
    if [ "${FIXHDR:-1}" = "1" ]; then
      printf '%s\0' "$D"/processor*/0/"$F" \
        | xargs -0 -r -P "${HDRJOBS:-32}" -I{} sed -i "1,/^}/ s/object[[:space:]]*T;/object $F;/" {}
    fi
    sed "s/__FIELD__/$F/g" "$DISP/system/receptorsVolume" > "$D/system/receptorsVolume"
    grep -q receptorsVolume "$D/system/controlDict" \
      || sed -i 's|#include "receptors"|#include "receptors"\n    #include "receptorsVolume"|' "$D/system/controlDict"
    rm -rf "$D"/postProcessing/roi*_vol
    ( cd "$D" && srun -n "$NP" postProcess -time 0 -parallel > log.roiVol."$p" 2>&1 ) || true
    ls "$D"/postProcessing/roi1_vol/*/volFieldValue.dat >/dev/null 2>&1 \
      || echo "  WARN: no roi output for h$h $p (see $D/log.roiVol.$p)"
    python3 - "$D" "$MAP" "$h" "$SCEN" "$p" >> "$OUTCSV" <<'PYIN'
import sys, os, glob, json
D, mapf, hour, scen, poll = sys.argv[1:6]
UG = 1.0e9
for e in json.load(open(mapf)):
    hits = glob.glob(os.path.join(D, "postProcessing", e["fo"], "*", "volFieldValue.dat"))
    v = None
    if hits:
        latest = sorted(hits, key=lambda q: float(os.path.basename(os.path.dirname(q))))[-1]
        for ln in open(latest):
            s = ln.strip()
            if s and not s.startswith("#"):
                parts = s.split()
                if len(parts) >= 2:
                    v = float(parts[-1])
    print("%s,%s,%s,%s,%s,%s" % (hour, scen, poll, e["id"], e["site"],
                                 ("%.8g" % (v*UG)) if v is not None else "NA"))
PYIN
    echo "  h$h $p -> appended"
  done
done
echo "wrote $OUTCSV"
