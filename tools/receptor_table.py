#!/usr/bin/env python3
"""
Build the receptor air-quality table from a single-hour run's postProcessing.

Reads, for each pollutant, each receptor's areaAverage(T):
  <results>/pp_<POLL>/<receptorN>/<startTime>/surfaceFieldValue.dat
converts kg/m^3 -> ug/m^3 (x1e9), and writes/prints a table keyed by receptor
(with site name + UTM centroid from receptors.json).

When given --reference <dir> (another results dir, e.g. the reference scenario),
it also adds absolute and % change vs that reference per receptor/pollutant.

Usage:
  python3 receptor_table.py --results results/h0_reference
  python3 receptor_table.py --results results/h0_S2 --reference results/h0_reference
"""
import argparse, glob, json, os, sys

UG = 1.0e9   # kg/m^3 -> ug/m^3


def last_value(dat_path):
    val = None
    for ln in open(dat_path):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        val = float(s.split()[-1])   # last column = areaAverage(T)
    return val


def read_run(results_dir, pollutants, recept_ids):
    """{receptor: {pollutant: ug/m^3}}"""
    out = {r: {} for r in recept_ids}
    for poll in pollutants:
        for r in recept_ids:
            hits = glob.glob(os.path.join(results_dir, "pp_%s" % poll, r, "*", "surfaceFieldValue.dat"))
            if not hits:
                out[r][poll] = None
                continue
            v = last_value(sorted(hits)[-1])
            out[r][poll] = v * UG if v is not None else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--pollutants", default="CO NOx")
    ap.add_argument("--triSurface", default="dispersionCase/constant/triSurface")
    ap.add_argument("--reference", default=None)
    args = ap.parse_args()
    polls = args.pollutants.split()

    meta = json.load(open(os.path.join(args.triSurface, "receptors.json")))
    ids = [m["id"] for m in meta]
    info = {m["id"]: m for m in meta}

    run = read_run(args.results, polls, ids)
    ref = read_run(args.reference, polls, ids) if args.reference else None

    # ---- print + CSV ----
    hdr = ["receptor", "site", "UTM_x", "UTM_y"]
    for p in polls:
        hdr.append("%s_ug_m3" % p)
        if ref:
            hdr += ["%s_ref" % p, "%s_pct" % p]
    rows = []
    for r in ids:
        x, y = info[r]["centroid_utm"][0], info[r]["centroid_utm"][1]
        row = [r, info[r].get("site_name", ""), "%.1f" % x, "%.1f" % y]
        for p in polls:
            v = run[r][p]
            row.append("%.4g" % v if v is not None else "NA")
            if ref:
                rv = ref[r][p]
                row.append("%.4g" % rv if rv is not None else "NA")
                if v is not None and rv not in (None, 0):
                    row.append("%+.1f%%" % (100.0 * (v - rv) / rv))
                else:
                    row.append("NA")
        rows.append(row)

    w = [max(len(hdr[i]), max(len(r[i]) for r in rows)) for i in range(len(hdr))]
    line = lambda c: "  ".join(str(c[i]).ljust(w[i]) for i in range(len(c)))
    print(line(hdr)); print("  ".join("-" * w[i] for i in range(len(hdr))))
    for r in rows:
        print(line(r))

    out_csv = os.path.join(args.results, "receptor_table.csv")
    with open(out_csv, "w") as f:
        f.write(",".join(hdr) + "\n")
        for r in rows:
            f.write(",".join(r) + "\n")
    print("\nwrote", out_csv)


if __name__ == "__main__":
    main()
