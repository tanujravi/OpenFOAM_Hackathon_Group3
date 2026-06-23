#!/usr/bin/env python3
"""
Plot simpleFoam residuals and field bounds from postProcessing.
Usage:  python3 plot_residuals.py [case_dir]
Output: <case_dir>/residuals.png
"""

import os
import sys
import glob

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CASE = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
PP   = os.path.join(CASE, "postProcessing")
OUT  = os.path.join(CASE, "residuals.png")

CONV_THRESHOLD = 1e-4   # from fvSolution residualControl


# ── helpers ──────────────────────────────────────────────────────────────────

def find_latest_dat(subdir):
    """Return path to the .dat inside postProcessing/<subdir>/<time>/*.dat,
    preferring the time directory with the largest numeric name."""
    pattern = os.path.join(PP, subdir, "*", "*.dat")
    candidates = glob.glob(pattern)
    if not candidates:
        return None
    # sort by the numeric time-dir component
    def time_key(p):
        try:    return float(os.path.basename(os.path.dirname(p)))
        except: return 0.0
    return sorted(candidates, key=time_key)[-1]


def read_dat(path):
    """Parse a whitespace-separated OF function-object .dat file.
    Returns (header_list, 2-D numpy array) or (None, None) on error."""
    if path is None or not os.path.isfile(path):
        return None, None
    header = None
    rows   = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    # last header line wins (OF sometimes writes multiple)
                    header = line.lstrip("# ").split()
                else:
                    try:
                        rows.append([float(x) for x in line.split()])
                    except ValueError:
                        pass
        if not rows:
            return None, None
        data = np.array(rows)
        return header, data
    except Exception as e:
        print(f"  [plot] could not read {path}: {e}")
        return None, None


# ── load data ─────────────────────────────────────────────────────────────────

res_path = find_latest_dat("residuals")
mm_path  = find_latest_dat("fieldMinMax")
si_path  = find_latest_dat("solverInfo")

res_hdr, res_data = read_dat(res_path)
mm_hdr,  mm_data  = read_dat(mm_path)

if res_data is None:
    print(f"  [plot] No residuals data found under {PP}/residuals — aborting.")
    sys.exit(0)

iters = res_data[:, 0]


# ── figure layout ─────────────────────────────────────────────────────────────

n_panels = 2 if mm_data is not None else 1
fig, axes = plt.subplots(n_panels, 1, figsize=(10, 4 * n_panels),
                         sharex=True, constrained_layout=True)
if n_panels == 1:
    axes = [axes]

fig.suptitle("simpleFoam — convergence monitor", fontsize=13, fontweight="bold")


# ── panel 1: residuals ────────────────────────────────────────────────────────

ax = axes[0]

# field columns start at index 1 (index 0 = Time/Iter)
field_names = res_hdr[1:] if res_hdr else [f"col{i}" for i in range(1, res_data.shape[1])]

colors = plt.cm.tab10.colors
for i, name in enumerate(field_names):
    col = i + 1
    if col >= res_data.shape[1]:
        break
    ax.semilogy(iters, res_data[:, col], label=name,
                color=colors[i % len(colors)], linewidth=1.2)

ax.axhline(CONV_THRESHOLD, color="black", linestyle="--",
           linewidth=0.8, label=f"target {CONV_THRESHOLD:.0e}")

ax.set_ylabel("Initial residual")
ax.set_title("Field residuals")
ax.legend(ncol=4, fontsize=8, loc="upper right")
ax.grid(True, which="both", linestyle=":", alpha=0.5)
ax.set_ylim(bottom=1e-8)


# ── panel 2: velocity / pressure bounds (fieldMinMax) ─────────────────────────

if mm_data is not None:
    ax = axes[1]
    mm_iters = mm_data[:, 0]

    # Try to find columns whose headers contain 'U' or 'p'
    if mm_hdr:
        for i, col_name in enumerate(mm_hdr[1:], start=1):
            if i >= mm_data.shape[1]:
                break
            label = col_name
            ls    = "--" if "max" in col_name.lower() else "-"
            ax.plot(mm_iters, mm_data[:, i], label=label,
                    linestyle=ls, linewidth=1.0)
    else:
        for i in range(1, mm_data.shape[1]):
            ax.plot(mm_iters, mm_data[:, i], label=f"col{i}", linewidth=1.0)

    ax.set_ylabel("Value")
    ax.set_title("Field min / max bounds")
    ax.legend(ncol=4, fontsize=8, loc="upper right")
    ax.grid(True, linestyle=":", alpha=0.5)


axes[-1].set_xlabel("Iteration")


# ── save ──────────────────────────────────────────────────────────────────────

fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"  [plot] saved → {OUT}")
