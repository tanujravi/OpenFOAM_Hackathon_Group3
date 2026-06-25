#!/usr/bin/env python3
"""Parse ONE dispersion run's receptor surfaceFieldValue outputs into a tidy
receptors.csv: hour,scenario,pollutant,receptor,site,conc_ugm3  (kg/m^3 x1e9)."""
import argparse, csv, glob, json, os

UG = 1.0e9


def last_value(p):
    v = None
    for ln in open(p):
        s = ln.strip()
        if s and not s.startswith("#"):
            v = float(s.split()[-1])
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--disp", required=True)
    ap.add_argument("--triSurface", required=True)
    ap.add_argument("--hour", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--pollutant", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    meta = json.load(open(os.path.join(a.triSurface, "receptors.json")))
    ids = [m["id"] for m in meta]
    site = {m["id"]: m.get("site_name", "") for m in meta}

    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hour", "scenario", "pollutant", "receptor", "site", "conc_ugm3"])
        for rid in ids:
            hits = glob.glob(os.path.join(a.disp, "postProcessing", rid, "*", "surfaceFieldValue.dat"))
            val = last_value(sorted(hits)[-1]) if hits else None
            w.writerow([a.hour, a.scenario, a.pollutant, rid, site.get(rid, ""),
                        ("%.8g" % (val * UG)) if val is not None else "NA"])
    print("wrote", a.out)


if __name__ == "__main__":
    main()
