#!/usr/bin/env python3
"""
parse_receptors.py
==================
Read the surfaceFieldValue receptor output of ONE reconstructed scenario
(times 1..24 = hours 0..23) and append tidy rows to a master CSV.

postProcess writes all time rows into a single
    postProcessing/<receptorKey>/<startTime>/surfaceFieldValue.dat
with columns:  # Time <tab> areaAverage(T)

Row -> (pollutant, scenario, receptor_key, receptor_name, hour, clock, conc_kgm3, conc_ugm3)
  hour  = time - 1                 (time 1 == simulated hour 0)
  clock = (7 + hour) % 24          (hour 0 == 07:00-08:00)
  conc  in kg/m^3;  x 1e9 -> ug/m^3
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import re
from pathlib import Path

FIELDS = ["pollutant", "scenario", "receptor_key", "receptor_name",
          "hour", "clock", "conc_kgm3", "conc_ugm3"]


def parse_dat(path):
    """Return (name, {time: value}) from one surfaceFieldValue.dat."""
    name, rows = None, {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                m = re.search(r"Region type\s*:\s*\S+\s+(\S+)", line)
                if m:
                    name = m.group(1)
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    t = float(parts[0]); val = float(parts[-1])
                except ValueError:
                    continue
                rows[t] = val
    return name, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", type=Path, required=True, help="Case dir holding postProcessing/.")
    ap.add_argument("--pollutant", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--out-csv", type=Path, required=True)
    args = ap.parse_args()

    pp = args.case / "postProcessing"
    keys = sorted(d.name for d in pp.iterdir() if d.name.startswith("receptor")) \
        if pp.is_dir() else []
    if not keys:
        raise SystemExit(f"no postProcessing/receptor* under {pp}")

    new_rows = []
    for key in keys:
        dats = sorted(glob.glob(str(pp / key / "*" / "surfaceFieldValue.dat")))
        if not dats:
            print(f"  WARNING: no .dat for {key}")
            continue
        name, rows = None, {}
        for dat in dats:                                  # merge (usually one file)
            nm, r = parse_dat(dat)
            name = name or nm
            rows.update(r)
        for t in sorted(rows):
            hour = int(round(t)) - 1
            clock = (7 + hour) % 24
            conc = rows[t]
            new_rows.append({
                "pollutant": args.pollutant, "scenario": args.scenario,
                "receptor_key": key, "receptor_name": name or key,
                "hour": hour, "clock": f"{clock:02d}:00",
                "conc_kgm3": f"{conc:.8e}", "conc_ugm3": f"{conc * 1e9:.6f}",
            })

    exists = args.out_csv.exists()
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_csv, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        w.writerows(new_rows)
    print(f"[parse] {args.pollutant}/{args.scenario}: appended {len(new_rows)} rows "
          f"({len(keys)} receptors) -> {args.out_csv}")


if __name__ == "__main__":
    main()
