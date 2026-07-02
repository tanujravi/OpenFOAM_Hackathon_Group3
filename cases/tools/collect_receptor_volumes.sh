#!/bin/bash
# Collect the volume-average receptor values computed DURING the dispersion solve
# (receptorsVolume volFieldValue FOs on the live T) into receptors_long.csv -- the format
# make_report.py consumes. No postProcess/topoSet: the solve already wrote the output.
# ONE scenario per call.
# args: DISP DISPROOT OUTCSV [HOURS] [POLLUTANTS] [SCENARIO]
set -euo pipefail
DISP="$1"; DISPROOT="$2"; OUTCSV="$3"
HOURS="${4:-0,1,3,5,8,9,11,14,17,23}"; POLLS="${5:-CO NOx}"; SCEN="${6:-reference}"
MAP="$DISP/system/receptor_zone_map.json"
[ -f "$MAP" ] || { echo "ERROR: $MAP missing -- run make_receptor_zones.py first"; exit 1; }
echo "hour,scenario,pollutant,receptor,site,conc_ugm3" > "$OUTCSV"
IFS=',' read -ra HRS <<< "$HOURS"
for h in "${HRS[@]}"; do
  for p in $POLLS; do
    D="$DISPROOT/h$h/$p"
    [ -d "$D/postProcessing" ] || { echo "  skip h$h $p (no postProcessing in $D)"; continue; }
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
