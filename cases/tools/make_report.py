#!/usr/bin/env python3
"""
make_report.py -- scenario air-quality report for the Guimaraes mobility study.

Reads receptor concentrations from the four scenario runs (reference, S1, S2, S3),
computes per-receptor / per-pollutant statistics over the sampled hours, compares
each scenario against the reference, and writes:
  <out>/receptor_summary.csv     per (scenario,pollutant,receptor): mean/peak/min (+ peak hour)
  <out>/scenario_comparison.csv  per (pollutant,receptor,metric): reference + each scenario + % change
  <out>/figs/*.png               grouped bar charts, %-change heatmap, diurnal profiles
  <out>/air_quality_report.pdf   multi-page PDF (findings + tables + figures)

Each --run takes  LABEL=PATH  where PATH is either
  * a receptors_long.csv / receptors.csv  (cols: hour,scenario,pollutant,receptor,site,conc_ugm3), or
  * a run directory containing disp/h<H>/<poll>/postProcessing/<receptor>/<t>/surfaceFieldValue.dat
    (this branch needs --triSurface .../constant/triSurface for receptors.json site names).

Example:
  python3 make_report.py \
      --run reference=../workflow/results_pod/receptors_long.csv \
      --run S1=../workflow_S1/results_pod_S1/receptors_long.csv \
      --run S2=../workflow_S2/results_pod_S2/receptors_long.csv \
      --run S3=../workflow_S3/results_pod_S3/receptors_long.csv \
      --triSurface ../dispersionCaseBig/constant/triSurface --out report
"""
import argparse, csv, glob, json, os, sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np

UG = 1.0e9  # kg/m^3 -> ug/m^3

SCEN_DESC = {
    "reference": "Reference - provided traffic (baseline)",
    "S1": "S1 - 20% gas vehicles -> EV  (all roads x0.8)",
    "S2": "S2 - 40% gas vehicles -> EV  (all roads x0.6)",
    "S3": "S3 - Metro Bus N101  (x0.5 / x0.7 on listed roads)",
}
# Air-quality reference values (ug/m3) for CONTEXT only (modelled NOx != ambient NO2;
# CFD values are the local traffic increment with no background added).
AQ_REF = {"NOx": [("EU NO2 annual limit (40)", 40.0), ("WHO NO2 24h (25)", 25.0)]}


def last_value(dat_path):
    v = None
    with open(dat_path) as fh:
        for ln in fh:
            s = ln.strip()
            if s and not s.startswith("#"):
                try:
                    v = float(s.split()[-1])
                except ValueError:
                    pass
    return v


def load_from_csv(path):
    recs = []
    with open(path) as fh:
        for row in csv.DictReader(fh):
            try:
                c = float(row["conc_ugm3"])
            except (ValueError, KeyError, TypeError):
                c = None
            recs.append(dict(hour=int(float(row["hour"])), pollutant=row["pollutant"],
                             receptor=row["receptor"], site=row.get("site", "") or row["receptor"],
                             conc=c))
    return recs


def load_from_rundir(run, triSurface):
    sites = {}
    if triSurface and os.path.isfile(os.path.join(triSurface, "receptors.json")):
        for m in json.load(open(os.path.join(triSurface, "receptors.json"))):
            sites[m["id"]] = m.get("site_name", "") or m["id"]
    recs = []
    pat = os.path.join(run, "disp", "h*", "*", "postProcessing", "*", "*", "surfaceFieldValue.dat")
    for dat in glob.glob(pat):
        parts = dat.split(os.sep)
        try:
            i = parts.index("disp"); j = parts.index("postProcessing")
        except ValueError:
            continue
        try:
            hour = int(parts[i + 1].lstrip("h"))
        except ValueError:
            continue
        poll = parts[i + 2]; rid = parts[j + 1]
        v = last_value(dat)
        recs.append(dict(hour=hour, pollutant=poll, receptor=rid,
                         site=sites.get(rid, rid), conc=(v * UG if v is not None else None)))
    return recs


def load_run(path, triSurface):
    if os.path.isfile(path):
        return load_from_csv(path)
    if os.path.isdir(path):
        for cand in [os.path.join(path, "receptors_long.csv")] + \
                    sorted(glob.glob(os.path.join(path, "results*", "receptors_long.csv"))):
            if os.path.isfile(cand):
                return load_from_csv(cand)
        return load_from_rundir(path, triSurface)
    raise SystemExit("ERROR: run path not found: %s" % path)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="append", required=True, metavar="LABEL=PATH",
                    help="scenario run, e.g. reference=../workflow/results_pod/receptors_long.csv")
    ap.add_argument("--triSurface", default=None, help="dir with receptors.json (for run-dir inputs)")
    ap.add_argument("--reference", default="reference", help="label used as the comparison baseline")
    ap.add_argument("--pollutants", default="CO NOx")
    ap.add_argument("--out", default="report")
    args = ap.parse_args()
    polls = args.pollutants.split()

    # ---- load ----
    scen_order, data, sites = [], {}, {}
    for spec in args.run:
        if "=" not in spec:
            raise SystemExit("ERROR: --run must be LABEL=PATH, got %r" % spec)
        label, path = spec.split("=", 1)
        recs = load_run(path, args.triSurface)
        if not recs:
            print("WARN: no receptor records found for %s (%s)" % (label, path), file=sys.stderr)
        scen_order.append(label)
        d = defaultdict(dict)            # (poll,receptor) -> {hour: conc}
        for r in recs:
            d[(r["pollutant"], r["receptor"])][r["hour"]] = r["conc"]
            sites[r["receptor"]] = r["site"]
        data[label] = d

    receptors = sorted({rk for d in data.values() for (_, rk) in d})
    ref = args.reference if args.reference in data else scen_order[0]
    os.makedirs(os.path.join(args.out, "figs"), exist_ok=True)

    # ---- aggregate stats ----
    # stat[(scen,poll,recep)] = dict(mean,peak,peak_hour,minv,n)
    stat = {}
    for scen in scen_order:
        for p in polls:
            for rk in receptors:
                series = data[scen].get((p, rk), {})
                pairs = sorted((h, v) for h, v in series.items() if v is not None)
                if pairs:
                    vals = [v for _, v in pairs]
                    ph, pk = max(pairs, key=lambda hv: hv[1])
                    stat[(scen, p, rk)] = dict(mean=sum(vals) / len(vals), peak=pk,
                                               peak_hour=ph, minv=min(vals), n=len(vals))
                else:
                    stat[(scen, p, rk)] = dict(mean=None, peak=None, peak_hour=None, minv=None, n=0)
    n_hours = max((stat[(s, p, rk)]["n"] for s in scen_order for p in polls for rk in receptors), default=0)

    # ---- CSV 1: receptor summary ----
    with open(os.path.join(args.out, "receptor_summary.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["scenario", "pollutant", "receptor", "site", "mean_ugm3", "peak_ugm3", "peak_hour", "min_ugm3", "n_hours"])
        for scen in scen_order:
            for p in polls:
                for rk in receptors:
                    s = stat[(scen, p, rk)]
                    w.writerow([scen, p, rk, sites.get(rk, rk),
                                fmt(s["mean"]), fmt(s["peak"]), s["peak_hour"], fmt(s["minv"]), s["n"]])

    # ---- CSV 2: scenario comparison vs reference ----
    others = [s for s in scen_order if s != ref]
    with open(os.path.join(args.out, "scenario_comparison.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        hdr = ["pollutant", "receptor", "site", "metric", "%s_ugm3" % ref]
        for s in others:
            hdr += ["%s_ugm3" % s, "%s_pct" % s]
        w.writerow(hdr)
        for p in polls:
            for rk in receptors:
                for metric in ("mean", "peak"):
                    rv = stat[(ref, p, rk)][metric]
                    row = [p, rk, sites.get(rk, rk), metric, fmt(rv)]
                    for s in others:
                        sv = stat[(s, p, rk)][metric]
                        row += [fmt(sv), pct(sv, rv)]
                    w.writerow(row)

    # ---- figures ----
    fig_bars = [bar_figure(args.out, p, scen_order, receptors, sites, stat) for p in polls]
    fig_heat = heatmap_figure(args.out, polls, others, receptors, sites, stat, ref) if others else None
    fig_diur = [diurnal_figure(args.out, p, scen_order, receptors, sites, data) for p in polls]

    # ---- PDF ----
    findings = build_findings(polls, scen_order, others, receptors, sites, stat, ref, n_hours)
    pdf_path = os.path.join(args.out, "air_quality_report.pdf")
    with PdfPages(pdf_path) as pdf:
        text_page(pdf, "Guimaraes Mobility Scenarios - Air-Quality Assessment",
                  findings)
        for p in polls:
            table_page(pdf, p, others, receptors, sites, stat, ref)
        for f in fig_bars + ([fig_heat] if fig_heat else []) + fig_diur:
            pdf.savefig(f); plt.close(f)
    print("Report written -> %s" % pdf_path)
    print("Tables          -> %s , %s" % (os.path.join(args.out, "receptor_summary.csv"),
                                          os.path.join(args.out, "scenario_comparison.csv")))
    print("Figures         -> %s/figs/" % args.out)


def fmt(v):
    return "%.4g" % v if isinstance(v, (int, float)) else "NA"


def pct(v, ref):
    if v is None or ref in (None, 0):
        return "NA"
    return "%+.1f%%" % (100.0 * (v - ref) / ref)


def pct_val(v, ref):
    if v is None or ref in (None, 0):
        return None
    return 100.0 * (v - ref) / ref


SCEN_COLORS = {"reference": "#444444", "S1": "#1f77b4", "S2": "#2ca02c", "S3": "#d62728"}


def shortsite(s, rk):
    s = (s or rk)
    return s if len(s) <= 26 else s[:24] + ".."


def bar_figure(out, poll, scen_order, receptors, sites, stat):
    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(receptors)); w = 0.8 / max(len(scen_order), 1)
    for i, scen in enumerate(scen_order):
        vals = [stat[(scen, poll, rk)]["mean"] or 0 for rk in receptors]
        ax.bar(x + i * w, vals, w, label=scen, color=SCEN_COLORS.get(scen))
    ax.set_xticks(x + w * (len(scen_order) - 1) / 2)
    ax.set_xticklabels([shortsite(sites.get(rk), rk) for rk in receptors], rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("mean concentration  [ug/m3]")
    ax.set_title("%s - mean receptor concentration by scenario" % poll)
    ax.legend(fontsize=8, ncol=len(scen_order))
    for ref_lbl, val in AQ_REF.get(poll, []):
        ax.axhline(val, ls="--", lw=0.8, color="grey")
        ax.text(ax.get_xlim()[1], val, " " + ref_lbl, va="center", fontsize=6, color="grey")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "figs", "bar_mean_%s.png" % poll), dpi=140)
    return fig


def heatmap_figure(out, polls, others, receptors, sites, stat, ref):
    rows = [(p, rk) for p in polls for rk in receptors]
    M = np.array([[pct_val(stat[(s, p, rk)]["mean"], stat[(ref, p, rk)]["mean"]) or np.nan
                   for s in others] for (p, rk) in rows], float)
    fig, ax = plt.subplots(figsize=(7, 0.6 * len(rows) + 1.5))
    vmax = np.nanmax(np.abs(M)) if np.isfinite(M).any() else 1
    im = ax.imshow(M, cmap="RdYlGn_r", vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(others))); ax.set_xticklabels(others)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(["%s @ %s" % (p, shortsite(sites.get(rk), rk)) for (p, rk) in rows], fontsize=7)
    for r in range(len(rows)):
        for c in range(len(others)):
            if np.isfinite(M[r, c]):
                ax.text(c, r, "%+.0f%%" % M[r, c], ha="center", va="center", fontsize=7)
    ax.set_title("Change in mean concentration vs %s" % ref)
    fig.colorbar(im, ax=ax, label="% change (green = improvement)")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "figs", "heatmap_pct.png"), dpi=140)
    return fig


DAY_START = 7  # emission/wind data hour index 0 == the 07:00-08:00 interval


def hour_clock(h):
    """Hour index -> 24h clock label for the interval start (index 0 == 07:00)."""
    return "%02d:00" % ((DAY_START + int(h)) % 24)


def diurnal_figure(out, poll, scen_order, receptors, sites, data):
    n = len(receptors); cols = 2; rows = (n + 1) // 2
    fig, axes = plt.subplots(rows, cols, figsize=(11, 3.2 * rows), squeeze=False)
    allh = sorted({h for scen in scen_order for rk in receptors
                   for h in data[scen].get((poll, rk), {})})
    for k, rk in enumerate(receptors):
        ax = axes[k // cols][k % cols]
        for scen in scen_order:
            series = data[scen].get((poll, rk), {})
            pts = sorted((h, v) for h, v in series.items() if v is not None)
            if pts:
                ax.plot([h for h, _ in pts], [v for _, v in pts], "-o", ms=3,
                        label=scen, color=SCEN_COLORS.get(scen))
        ax.set_title(shortsite(sites.get(rk), rk), fontsize=9)
        ax.set_xlabel("time of day (interval start)"); ax.set_ylabel("%s [ug/m3]" % poll, fontsize=8)
        if allh:
            ax.set_xticks(allh)
            ax.set_xticklabels([hour_clock(h) for h in allh], rotation=45, ha="right", fontsize=6.5)
        ax.grid(alpha=0.3)
    axes[0][0].legend(fontsize=7)
    for k in range(n, rows * cols):
        axes[k // cols][k % cols].axis("off")
    fig.suptitle("%s - diurnal profile at each receptor (sampled hours, 24h clock)" % poll)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(os.path.join(out, "figs", "diurnal_%s.png" % poll), dpi=140)
    return fig


def build_findings(polls, scen_order, others, receptors, sites, stat, ref, n_hours):
    L = []
    L.append("Baseline = '%s'.  Statistics over %d sampled hours, 4 sensitive receptors." % (ref, n_hours))
    L.append("Concentrations are the local traffic increment (passive scalar, ug/m3); no background added.")
    L.append("")
    L.append("Scenario-average reduction of MEAN concentration vs reference (mean over receptors):")
    for s in others:
        bits = []
        for p in polls:
            ch = [pct_val(stat[(s, p, rk)]["mean"], stat[(ref, p, rk)]["mean"]) for rk in receptors]
            ch = [c for c in ch if c is not None]
            if ch:
                bits.append("%s %+.1f%% (range %+.0f..%+.0f%%)" % (p, sum(ch) / len(ch), min(ch), max(ch)))
        L.append("  %-4s %s : %s" % (s, SCEN_DESC.get(s, ""), " | ".join(bits)))
    L.append("")
    # most polluted receptor (by reference mean, summed pollutants)
    worst = max(receptors, key=lambda rk: sum((stat[(ref, p, rk)]["mean"] or 0) for p in polls))
    L.append("Most exposed receptor (reference): %s." % (sites.get(worst, worst)))
    # which receptor benefits most from S3 (most spatially-selective scenario)
    if "S3" in others:
        best = None
        for rk in receptors:
            ch = [pct_val(stat[("S3", p, rk)]["mean"], stat[(ref, p, rk)]["mean"]) for p in polls]
            ch = [c for c in ch if c is not None]
            if ch:
                a = sum(ch) / len(ch)
                if best is None or a < best[1]:
                    best = (rk, a)
        if best:
            L.append("S3 (Metro Bus) is spatially selective: largest improvement at %s (%+.1f%%);"
                     % (sites.get(best[0], best[0]), best[1]))
            L.append("  receptors far from the N101 corridor change little -> location matters.")
    L.append("")
    L.append("Note: dispersion is linear in emission for a frozen flow, so the EV scenarios scale")
    L.append("near-uniformly (S1 ~ -20%, S2 ~ -40% at every receptor); a near-uniform result is a")
    L.append("consistency check on the workflow, while S3's heterogeneity reflects the road selection.")
    return L


def text_page(pdf, title, lines):
    # Wrap long lines and paginate so nothing runs off the page (A4 portrait).
    import textwrap
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.07, 0.955, title, fontsize=15, weight="bold", va="top")
    fig.text(0.07, 0.92, "OpenFOAM Hackathon (OFW21) - receptor air-quality comparison",
             fontsize=9, va="top", color="#555555")
    y = 0.875
    for ln in lines:
        for k, seg in enumerate(textwrap.wrap(ln, width=92) or [""]):
            fig.text(0.07, y, ("    " if k else "") + seg, fontsize=8.6,
                     family="monospace", va="top")
            y -= 0.0175
            if y < 0.06:                       # start a new page
                pdf.savefig(fig); plt.close(fig)
                fig = plt.figure(figsize=(8.27, 11.69)); y = 0.95
        y -= 0.005                             # gap between logical lines
    pdf.savefig(fig); plt.close(fig)


def table_page(pdf, poll, others, receptors, sites, stat, ref):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    cols = ["receptor", "metric", "%s" % ref] + [c for s in others for c in (s, "%s %%" % s)]
    rows = []
    for rk in receptors:
        for metric in ("mean", "peak"):
            rv = stat[(ref, poll, rk)][metric]
            row = [shortsite(sites.get(rk), rk), metric, fmt(rv)]
            for s in others:
                sv = stat[(s, poll, rk)][metric]
                row += [fmt(sv), pct(sv, rv)]
            rows.append(row)
    t = ax.table(cellText=rows, colLabels=cols, loc="center", cellLoc="center")
    t.auto_set_font_size(False); t.set_fontsize(8); t.scale(1, 1.4)
    ax.set_title("%s - receptor concentrations [ug/m3] and %% change vs %s" % (poll, ref), pad=20)
    pdf.savefig(fig); plt.close(fig)


if __name__ == "__main__":
    main()
