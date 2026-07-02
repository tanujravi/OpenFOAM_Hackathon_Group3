#!/usr/bin/env python3
"""
plot_receptors.py
=================
Day-evolution receptor plots from receptor_results.csv.

For each pollutant and each receptor location -> ONE figure with the 4 scenario
curves (concentration vs clock hour, 07:00 -> next-day 06:00).  Saved to
receptor_plots/<pollutant>_<receptorKey>_<name>.png.  Also a 2x2 overview per
pollutant (all four receptors).

Usage:  python3 plot_receptors.py --csv receptor_results.csv --out-dir receptor_plots
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# scenario -> (legend label, colour, z-order)   -- reference first
SCEN = {
    "full": ("Reference (full traffic)", "#111111"),
    "S1":   ("S1: -20% gas vehicles",    "#1f77b4"),
    "S2":   ("S2: -40% gas vehicles",    "#2ca02c"),
    "S3":   ("S3: Metro Bus (-50% N101)", "#d62728"),
}
SCEN_ORDER = ["full", "S1", "S2", "S3"]


def load(csv_path):
    # data[pollutant][receptor_key] = {"name":..., scenario: [(hour, ugm3), ...]}
    data = defaultdict(lambda: defaultdict(lambda: {"name": None, "scen": defaultdict(list)}))
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            d = data[row["pollutant"]][row["receptor_key"]]
            d["name"] = row["receptor_name"]
            d["scen"][row["scenario"]].append((int(row["hour"]), float(row["conc_ugm3"])))
    return data


def _clock(h):
    return f"{(7 + h) % 24:02d}"


def plot_one(ax, rec, title):
    for s in SCEN_ORDER:
        pts = sorted(rec["scen"].get(s, []))
        if not pts:
            continue
        hrs = [h for h, _ in pts]
        val = [v for _, v in pts]
        label, col = SCEN[s][0], SCEN[s][1]
        ax.plot(hrs, val, "o-", ms=3, lw=1.6, color=col, label=label,
                zorder=5 if s == "full" else 3)
    hrs_all = sorted({h for s in SCEN_ORDER for h, _ in rec["scen"].get(s, [])})
    ticks = hrs_all[::3] if len(hrs_all) > 12 else hrs_all
    ax.set_xticks(ticks)
    ax.set_xticklabels([_clock(h) for h in ticks])
    ax.set_xlabel("hour of day (local clock)")
    ax.set_ylabel(r"concentration  [$\mu$g/m$^3$]")
    ax.set_title(title)
    ax.grid(True, alpha=.3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    data = load(args.csv)
    n = 0
    for pol, recs in data.items():
        keys = sorted(recs)
        # one figure per receptor
        for key in keys:
            rec = recs[key]
            fig, ax = plt.subplots(figsize=(8, 5))
            plot_one(ax, rec, f"{pol} - {rec['name']}  (day evolution)")
            ax.legend(fontsize=9)
            fig.tight_layout()
            out = args.out_dir / f"{pol}_{key}_{rec['name']}.png"
            fig.savefig(out, dpi=140); plt.close(fig)
            n += 1
            print(f"[plot] {out}")
        # 2x2 overview
        fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
        for ax, key in zip(axes.ravel(), keys):
            plot_one(ax, recs[key], recs[key]["name"])
        for ax in axes.ravel()[len(keys):]:
            ax.axis("off")
        axes.ravel()[0].legend(fontsize=8)
        fig.suptitle(f"{pol}: receptor day-evolution across scenarios", fontsize=14)
        fig.tight_layout()
        out = args.out_dir / f"{pol}_overview.png"
        fig.savefig(out, dpi=140); plt.close(fig)
        n += 1
        print(f"[plot] {out}")
    print(f"[plot] wrote {n} figures -> {args.out_dir}")


if __name__ == "__main__":
    main()
