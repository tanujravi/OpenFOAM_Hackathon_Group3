#!/usr/bin/env python3
"""
Aggregate the 24-hour quasi-steady sweep into daily receptor air-quality tables.

Reads the per-(hour, scenario, pollutant) receptor files produced by the workflow
(run_disp.sh), each a CSV with header:
    hour,scenario,pollutant,receptor,site,conc_ugm3
and writes three tables under --out:

  hourly_long.csv            tidy long form (one row per hour/scn/pol/receptor)
  receptor_daily_summary.csv per scenario/pollutant/receptor: daily mean, peak,
                             peak-hour, n_hours
  scenario_comparison.csv    per pollutant/receptor/metric(mean|peak): the
                             reference value, each scenario's value, and % change
                             vs reference  (the headline deliverable)

Usage:
  python3 aggregate_day.py --work runs --out results
  python3 aggregate_day.py --inputs a/receptors.csv b/receptors.csv ... --out results
"""
import argparse, csv, glob, os, sys
from collections import defaultdict


def read_rows(paths):
    rows = []
    for p in paths:
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                if not r.get("receptor"):
                    continue
                try:
                    r["hour"] = int(r["hour"])
                    r["conc_ugm3"] = float(r["conc_ugm3"])
                except (ValueError, TypeError):
                    continue
                rows.append(r)
    return rows


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=None, help="sweep work dir (globs disp/h*/*/*/receptors.csv)")
    ap.add_argument("--inputs", nargs="*", default=None, help="explicit receptors.csv files")
    ap.add_argument("--out", required=True, help="output dir for the tables")
    ap.add_argument("--reference", default="reference", help="baseline scenario name")
    args = ap.parse_args()

    if args.inputs:
        paths = list(args.inputs)
    elif args.work:
        paths = sorted(glob.glob(os.path.join(args.work, "disp", "h*", "*", "*", "receptors.csv")))
    else:
        sys.exit("ERROR: pass --work or --inputs")
    if not paths:
        sys.exit("ERROR: no receptors.csv files found")
    os.makedirs(args.out, exist_ok=True)

    rows = read_rows(paths)
    if not rows:
        sys.exit("ERROR: no valid data rows parsed")

    # ---- hourly_long.csv -------------------------------------------------
    long_hdr = ["hour", "scenario", "pollutant", "receptor", "site", "conc_ugm3"]
    long_rows = sorted(
        ([r["hour"], r["scenario"], r["pollutant"], r["receptor"], r.get("site", ""),
          "%.6g" % r["conc_ugm3"]] for r in rows),
        key=lambda x: (x[2], x[3], x[1], x[0]))
    write_csv(os.path.join(args.out, "hourly_long.csv"), long_hdr, long_rows)

    # ---- receptor_daily_summary.csv -------------------------------------
    # group by (scenario, pollutant, receptor)
    series = defaultdict(list)             # key -> list[(hour, conc)]
    site_of = {}
    for r in rows:
        key = (r["scenario"], r["pollutant"], r["receptor"])
        series[key].append((r["hour"], r["conc_ugm3"]))
        site_of[r["receptor"]] = r.get("site", "")

    summary = {}                           # key -> dict(mean, peak, peak_hour, n)
    sum_hdr = ["scenario", "pollutant", "receptor", "site",
               "mean_ugm3", "peak_ugm3", "peak_hour", "n_hours"]
    sum_rows = []
    for key in sorted(series):
        vals = series[key]
        concs = [c for _, c in vals]
        mean = sum(concs) / len(concs)
        peak_hour, peak = max(vals, key=lambda hc: hc[1])
        summary[key] = dict(mean=mean, peak=peak, peak_hour=peak_hour, n=len(vals))
        scn, pol, rec = key
        sum_rows.append([scn, pol, rec, site_of.get(rec, ""),
                         "%.6g" % mean, "%.6g" % peak, peak_hour, len(vals)])
    write_csv(os.path.join(args.out, "receptor_daily_summary.csv"), sum_hdr, sum_rows)

    # ---- scenario_comparison.csv ----------------------------------------
    scenarios = sorted({k[0] for k in series})
    others = [s for s in scenarios if s != args.reference]
    pol_set = sorted({k[1] for k in series})
    rec_set = sorted({k[2] for k in series})

    cmp_hdr = ["pollutant", "receptor", "site", "metric", args.reference]
    for s in others:
        cmp_hdr += [s, "%s_pct" % s]
    cmp_rows = []
    for pol in pol_set:
        for rec in rec_set:
            for metric in ("mean", "peak"):
                refkey = (args.reference, pol, rec)
                if refkey not in summary:
                    continue
                refv = summary[refkey][metric]
                row = [pol, rec, site_of.get(rec, ""), metric, "%.6g" % refv]
                for s in others:
                    k = (s, pol, rec)
                    if k in summary:
                        v = summary[k][metric]
                        pct = (100.0 * (v - refv) / refv) if refv else float("nan")
                        row += ["%.6g" % v, "%+.1f%%" % pct]
                    else:
                        row += ["NA", "NA"]
                cmp_rows.append(row)
    write_csv(os.path.join(args.out, "scenario_comparison.csv"), cmp_hdr, cmp_rows)

    print("aggregated %d rows from %d files -> %s" % (len(rows), len(paths), args.out))
    print("  hourly_long.csv  receptor_daily_summary.csv  scenario_comparison.csv")


if __name__ == "__main__":
    main()
