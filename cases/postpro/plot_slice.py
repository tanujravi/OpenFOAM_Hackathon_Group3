#!/usr/bin/env python3
"""
plot_slice.py -- draw a ground-level concentration map from a .npz dumped by
`pv_ground_slice.py --extract --dump slice.npz`.

Runs in a NORMAL Python that has matplotlib (i.e. OUTSIDE ParaView/pvbatch),
so it sidesteps the pvbatch-embedded-Python / EasyBuild-matplotlib ABI clash:
  module load matplotlib            # any env whose python imports matplotlib
  python3 plot_slice.py slice.npz [out.png]

The .npz carries everything needed (grid, extent, log/linear flag, colormap,
receptor points), so this script needs only numpy + matplotlib.
"""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, Normalize

if len(sys.argv) < 2:
    sys.exit("usage: python3 plot_slice.py slice.npz [out.png]")
npz = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else npz[:-4] + "_ground.png" if npz.endswith(".npz") else npz + "_ground.png"

d = np.load(npz, allow_pickle=True)
grid = d["grid"]; b = d["extent"]
unit = str(d["unit"]); label = str(d["label"]); fld = str(d["field"])
z = float(d["z"]); no_log = bool(int(d["no_log"])); cmap_name = str(d["cmap"])
dy_dx = float(d["dy_dx"]); rxy = d["recept_xy"]; rnm = d["recept_names"]

finite = grid[np.isfinite(grid)]
if finite.size == 0:
    sys.exit("slice is empty (check --z / --time in the dump step)")
vmax = float(np.nanmax(finite))
vpos = finite[finite > 0]
use_log = (not no_log) and vmax > 0 and vpos.size > 0
vmin = float(vpos.min()) if use_log else float(np.nanmin(finite))
norm = LogNorm(vmin=max(vmin, vmax * 1e-4), vmax=vmax) if use_log else Normalize(vmin=vmin, vmax=vmax)

fig, ax = plt.subplots(figsize=(9, max(4.0, 9 * dy_dx)))
cmap = plt.get_cmap(cmap_name).copy(); cmap.set_bad(alpha=0.0)   # buildings / no-data transparent
im = ax.imshow(grid, extent=[b[0], b[1], b[2], b[3]], origin="lower",
               cmap=cmap, norm=norm, interpolation="nearest")
ax.set_aspect("equal"); ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
cb = fig.colorbar(im, ax=ax, shrink=0.75); cb.set_label("%s [%s]" % (fld.replace("T_", ""), unit))

for (x, y), nm in zip(np.atleast_2d(rxy), rnm):
    ax.plot(x, y, "o", ms=9, mfc="none", mec="cyan", mew=1.8, zorder=5)
    ax.annotate(str(nm), (x, y), xytext=(6, 6), textcoords="offset points",
                fontsize=7, color="cyan", fontweight="bold", zorder=6)

ax.set_title("%s near-ground concentration (~%.1f m above terrain) - %s" % (fld.replace("T_", ""), z, label))
fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)
print("wrote %s (range %.3g..%.3g %s)" % (out, vmin, vmax, unit))
