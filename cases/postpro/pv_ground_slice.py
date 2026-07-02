#!/usr/bin/env python3
"""
pv_ground_slice.py -- top-down GROUND-LEVEL concentration-field map (ParaView pvbatch).

Renders a horizontal slice of the dispersion field at breathing height, seen from
straight above (a "pollution map" of the CFD solution), for each pollutant. This is
the concentration-field visualisation the challenge asks for, complementing the
receptor numbers. Run on the cluster with ParaView's pvbatch, on a RECONSTRUCTED case.

IMPORTANT -- where the converged field lives:
  * The POD/decomposed run (workflow/scripts/run_disp_decomp.sh) STASHES the converged
    field back into TIME 0 as  processor*/0/T_<POLL>  (T_CO, T_NOx) -- NOT in the latest
    time directory. So for those snapshots pass  --time 0  (this is the default here).
  * A normally-solved dispersion (run_disp.sh / run_single_hour.sh) instead leaves the
    converged field in the LATEST time dir as T (renamed T_CO/T_NOx) -> use --time latest.

HEADLESS NODES: pvbatch on a compute node with no display SIGSEGVs when it tries to
open an OpenGL context. Launch with  `pvbatch --force-offscreen-rendering ...`  (or, if
that still crashes, `xvfb-run -a pvbatch ...`). Tested against ParaView 5.11 / 6.0.

LOCALE: if pvbatch prints "Fatal vtkpython error: unable to decode the command line
argument", the node locale is not UTF-8 -- export it before running (in the sbatch
script, above srun):  export LC_ALL=C.UTF-8 ; export LANG=C.UTF-8  (or an available
UTF-8 locale from `locale -a`).

The FoamFile 'object' entry inside T_CO / T_NOx still says T (they are renamed copies
of the solver field), and ParaView reads a field by its 'object' name -- so fix the
header to match the filename first.

TWO ways to run:

(A) DECOMPOSED, no reconstruct (recommended -- ARM-safe, reads processor*/0/ directly).
    Launch with PARALLEL pvbatch and pass --decomposed. Fix the header on every processor:
      D=runs_pod/disp/h11/NOx
      for p in "$D"/processor*; do sed -i 's/object[[:space:]]\\+T;/object T_NOx;/' "$p"/0/T_NOx; done
      srun pvbatch pv_ground_slice.py --case "$D" --decomposed --time 0 \\
          --label reference_h11 --fields T_NOx --z 2.0 \\
          --triSurface ../dispersionCaseBig/constant/triSurface --out figs
    (or  mpirun -np <N> pvbatch --mpi pv_ground_slice.py --decomposed ... ; N need not equal
     the decomposition -- ParaView distributes the processor subdomains across the ranks.)

(B) RECONSTRUCTED (serial pvbatch). Reconstruct the snapshot time first, then fix 0/T_*:
      srun redistributePar -reconstruct -time 0 -parallel -case "$D"
      sed -i 's/object[[:space:]]\\+T;/object T_NOx;/' "$D"/0/T_NOx
      pvbatch pv_ground_slice.py --case "$D" --time 0 --fields T_NOx ... --out figs

(C) GL-FREE (--extract, recommended if rendering segfaults). No RenderView is created;
    pvbatch resamples the slice to a grid and matplotlib draws the map -> immune to the
    headless-OpenGL crash. Works serial (reconstructed) or with --decomposed in parallel
    (Fetch gathers to rank 0). Receptors are overlaid from receptors.json (recentred frame):
      for p in "$D"/processor*; do sed -i 's/object[[:space:]]\\+T;/object T_NOx;/' "$p"/0/T_NOx; done
      srun pvbatch pv_ground_slice.py --case "$D" --decomposed --extract --time 0 \\
          --label reference_h11 --fields T_NOx --z 2.0 \\
          --triSurface ../dispersionCaseBig/constant/triSurface --out figs

Note: POD snapshots live at TIME 0 (T_<POLL> stashed in 0/ by run_disp_decomp.sh) and each
disp dir holds ONE pollutant; a normally-solved dispersion (run_disp.sh) has the field in
the LATEST time dir -> use --time latest. --case points at the RUN dir, not the template.
Output: <out>/<label>_<field>_ground.png  (one per field).
"""
import argparse, os, sys, glob

try:
    from paraview.simple import *            # noqa: F401,F403
except Exception as exc:                     # pragma: no cover
    sys.exit("ERROR: run with ParaView's pvbatch -- 'paraview.simple' not importable (%s)" % exc)


def setp(proxy, name, value):
    if hasattr(proxy, name):
        try:
            setattr(proxy, name, value); return True
        except Exception as e:
            print("WARN: could not set %s=%r (%s)" % (name, value, e))
    return False


def safe(fn, what):
    try:
        return fn()
    except Exception as e:
        print("WARN: skipped %s (%s)" % (what, e)); return None


def ensure_foam(case):
    if os.path.isfile(case) and case.endswith((".foam", ".OpenFOAM")):
        return case
    d = case if os.path.isdir(case) else os.path.dirname(case) or "."
    stub = os.path.join(d, "case.foam")
    if not os.path.exists(stub):
        open(stub, "w").close()
    return stub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, help=".foam file or reconstructed case dir")
    ap.add_argument("--label", default="run")
    ap.add_argument("--fields", nargs="+", default=["T_CO", "T_NOx"])
    ap.add_argument("--scale", type=float, default=1.0e9, help="kg/m^3 -> ug/m^3")
    ap.add_argument("--unit", default="ug/m3")
    ap.add_argument("--time", default="0",
                    help="time to read: '0' for POD snapshots (T_<poll> stashed in 0/), "
                         "'latest' for a normally-solved dispersion")
    ap.add_argument("--z", type=float, default=2.0, help="slice height in the recentred frame (m above ground~0 at ROI)")
    ap.add_argument("--triSurface", default=None, help="dir with receptor*.obj to overlay")
    ap.add_argument("--out", default="figs")
    ap.add_argument("--res", nargs=2, type=int, default=[1600, 1200])
    ap.add_argument("--preset", default="Viridis (matplotlib)", help="ParaView colour preset (render mode)")
    ap.add_argument("--cmap", default="inferno", help="matplotlib colormap (--extract mode)")
    ap.add_argument("--no-log", action="store_true", help="use a linear colour scale")
    ap.add_argument("--decomposed", action="store_true",
                    help="read processor*/ directly (NO reconstruct); launch with parallel "
                         "pvbatch, e.g. `srun pvbatch ...` or `mpirun -np N pvbatch --mpi ...`")
    ap.add_argument("--extract", action="store_true",
                    help="GL-free: resample the slice to a grid and draw the map with "
                         "matplotlib (NO ParaView rendering -> no OpenGL, no segfault on "
                         "headless nodes). Works serial or --decomposed parallel.")
    ap.add_argument("--grid", type=int, default=600, help="--extract raster: cells along the longer side")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    foam = ensure_foam(a.case)
    reader = OpenFOAMReader(registrationName="dispcase", FileName=foam)
    setp(reader, "CaseType", "Decomposed Case" if a.decomposed else "Reconstructed Case")
    setp(reader, "SkipZeroTime", 0)         # POD snapshots (T_<poll>) live in 0/ -> do NOT skip time 0
    setp(reader, "CellArrays", a.fields)
    setp(reader, "MeshRegions", ["internalMesh"])
    setp(reader, "Createcelltopointfiltereddata", 1)
    reader.UpdatePipeline()
    try:
        times = [float(x) for x in reader.TimestepValues]
    except TypeError:
        _tv = reader.TimestepValues; times = [float(_tv)] if _tv is not None else []
    t = (float(times[-1]) if a.time == "latest" else float(a.time)) if times else 0.0
    print("using time = %s (available: %s)" % (t, times))

    c2p = CellDatatoPointData(registrationName="c2p", Input=reader); c2p.UpdatePipeline(t)
    view = None
    if not a.extract:                       # creating a RenderView touches OpenGL -> skip it in extract mode
        view = GetActiveViewOrCreate("RenderView")
        view.ViewSize = a.res; view.Background = [1, 1, 1]
        safe(lambda: setattr(view, "OrientationAxesVisibility", 0), "hide orientation axes")
    avail = list(c2p.PointData.keys())
    print("point fields available: %s" % avail)

    # receptor overlay sources for the RENDER path (extract mode overlays from receptors.json instead)
    receptors = []
    if a.triSurface and not a.extract:
        for obj in sorted(glob.glob(os.path.join(a.triSurface, "receptor*.obj"))):
            r = safe(lambda o=obj: OpenDataFile(o), "load %s" % os.path.basename(obj))
            if r is not None:
                receptors.append(r)

    for fld in a.fields:
        if fld not in avail:
            print("WARN: field '%s' not found -> skipping (check the FoamFile 'object' header)" % fld)
            continue
        ug = fld.replace("T_", "") + "_" + a.unit.replace("/", "")
        calc = Calculator(registrationName="calc_" + fld, Input=c2p)
        setp(calc, "AttributeType", "Point Data")
        calc.ResultArrayName = ug; calc.Function = '"%s"*%g' % (fld, a.scale)
        calc.UpdatePipeline(t)

        if a.extract:
            extract_plot(calc, ug, fld, a, t)
            continue

        sl = Slice(registrationName="ground_" + fld, Input=calc)
        sl.SliceType = "Plane"
        sl.SliceType.Origin = [0.0, 0.0, a.z]
        sl.SliceType.Normal = [0.0, 0.0, 1.0]
        sl.UpdatePipeline(t)

        arr = sl.PointData.GetArray(ug)
        rng = arr.GetRange() if arr else (0.0, 1.0)
        vmax = rng[1] if rng[1] > 0 else 1.0
        vmin = max(vmax * 1e-3, rng[0] if rng[0] > 0 else vmax * 1e-3)

        Hide(reader, view); Hide(c2p, view); Hide(calc, view)
        ds = Show(sl, view); ColorBy(ds, ("POINTS", ug))
        lut = GetColorTransferFunction(ug)
        safe(lambda: lut.ApplyPreset(a.preset, True), "apply preset")
        # set a POSITIVE range BEFORE enabling log (scalarTransportFoam leaves a tiny
        # negative undershoot; a log LUT clamps to [1,10] if the range includes <=0).
        safe(lambda: lut.RescaleTransferFunction(vmin, vmax), "rescale colour range")
        if not a.no_log:
            safe(lambda: setp(lut, "UseLogScale", 1), "log colour scale")
            safe(lambda: lut.RescaleTransferFunction(vmin, vmax), "rescale (log)")
        sb = safe(lambda: GetScalarBar(lut, view), "scalar bar")
        if sb is not None:
            safe(lambda: setattr(sb, "Title", "%s [%s]" % (fld.replace("T_", ""), a.unit)), "scalar bar title")
            safe(lambda: setattr(sb, "ComponentTitle", ""), "scalar bar subtitle")

        # receptors as black outlines on top
        for r in receptors:
            dr = safe(lambda rr=r: Show(rr, view), "show receptor")
            if dr is not None:
                safe(lambda d=dr: setattr(d, "Representation", "Surface"), "receptor repr")
                safe(lambda d=dr: setattr(d, "DiffuseColor", [0, 0, 0]), "receptor colour")
                safe(lambda d=dr: setattr(d, "Opacity", 0.9), "receptor opacity")

        # top-down (map) camera with parallel projection
        b = sl.GetDataInformation().GetBounds()
        cx, cy = 0.5 * (b[0] + b[1]), 0.5 * (b[2] + b[3])
        half = 0.5 * max(b[1] - b[0], b[3] - b[2]) * 1.05
        cam = GetActiveCamera()
        cam.SetFocalPoint(cx, cy, a.z); cam.SetPosition(cx, cy, a.z + 1.0e4); cam.SetViewUp(0, 1, 0)
        setp(view, "CameraParallelProjection", 1)
        safe(lambda: setattr(view, "CameraParallelScale", half), "parallel scale")
        Render(view)
        out = os.path.join(a.out, "%s_%s_ground.png" % (a.label, fld))
        SaveScreenshot(out, view, ImageResolution=a.res)
        print("  wrote %s (z=%.1f, range %.3g..%.3g %s)" % (out, a.z, vmin, vmax, a.unit))
        Hide(sl, view)
        for r in receptors:
            safe(lambda rr=r: Hide(rr, view), "hide receptor")


def extract_plot(calc, ug, fld, a, t):
    """GL-free: resample the field onto a z-plane grid, Fetch to numpy, draw with matplotlib.
    No ParaView RenderView is created, so this never touches OpenGL. In parallel (--decomposed)
    Fetch gathers to rank 0; other ranks get an empty image and return."""
    import os as _os, json
    import numpy as np
    try:
        from paraview import servermanager as sm
    except Exception:
        import paraview.servermanager as sm
    try:
        from vtkmodules.util.numpy_support import vtk_to_numpy
    except Exception:
        from vtk.util.numpy_support import vtk_to_numpy

    b = calc.GetDataInformation().GetBounds()          # xmin,xmax,ymin,ymax,zmin,zmax (global)
    dx, dy = (b[1] - b[0]), (b[3] - b[2])
    nx = max(2, int(a.grid))
    ny = max(2, int(round(a.grid * (dy / dx)))) if dx > 0 else max(2, int(a.grid))
    ri = ResampleToImage(registrationName="ri_" + fld, Input=calc)
    setp(ri, "UseInputBounds", 0)
    ri.SamplingBounds = [b[0], b[1], b[2], b[3], a.z, a.z]
    ri.SamplingDimensions = [nx, ny, 1]
    ri.UpdatePipeline(t)

    img = sm.Fetch(ri)
    if img is not None and img.IsA("vtkMultiBlockDataSet"):
        img = img.GetBlock(0)
    if img is None or img.GetNumberOfPoints() == 0:
        return                                          # non-root MPI rank (data is on rank 0)
    pd = img.GetPointData()
    if pd.GetArray(ug) is None:
        print("WARN: %s not on the resampled slice (check --z / --time)" % ug); return
    vals = vtk_to_numpy(pd.GetArray(ug)).astype(float)
    msk = pd.GetArray("vtkValidPointMask")
    if msk is not None:
        vals[vtk_to_numpy(msk) == 0] = np.nan
    dims = img.GetDimensions()                          # (nx, ny, 1)
    grid = vals.reshape(dims[1], dims[0])               # rows = y, cols = x

    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm, Normalize
    finite = grid[np.isfinite(grid)]
    if finite.size == 0:
        print("WARN: slice empty for %s (check --z / --time)" % fld); return
    vmax = float(np.nanmax(finite))
    vpos = finite[finite > 0]
    use_log = (not a.no_log) and vmax > 0 and vpos.size > 0
    vmin = float(vpos.min()) if use_log else float(np.nanmin(finite))
    norm = LogNorm(vmin=max(vmin, vmax * 1e-4), vmax=vmax) if use_log else Normalize(vmin=vmin, vmax=vmax)

    fig, ax = plt.subplots(figsize=(9, max(4.0, 9 * (dy / dx) if dx > 0 else 9)))
    cmap = plt.get_cmap(a.cmap).copy(); cmap.set_bad(alpha=0.0)   # buildings/no-data transparent
    im = ax.imshow(grid, extent=[b[0], b[1], b[2], b[3]], origin="lower",
                   cmap=cmap, norm=norm, interpolation="nearest")
    ax.set_aspect("equal"); ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
    cb = fig.colorbar(im, ax=ax, shrink=0.75); cb.set_label("%s [%s]" % (fld.replace("T_", ""), a.unit))

    rj = _os.path.join(a.triSurface or "", "receptors.json")
    if _os.path.isfile(rj):
        for m in json.load(open(rj)):
            c = m.get("centroid_recentred") or m.get("centroid")
            if c:
                ax.plot(c[0], c[1], "o", ms=9, mfc="none", mec="cyan", mew=1.8, zorder=5)
                ax.annotate(str(m.get("site_name", ""))[:18], (c[0], c[1]), xytext=(6, 6),
                            textcoords="offset points", fontsize=7, color="cyan",
                            fontweight="bold", zorder=6)
    ax.set_title("%s ground-level concentration (z=%.1f m) - %s" % (fld.replace("T_", ""), a.z, a.label))
    out = _os.path.join(a.out, "%s_%s_ground.png" % (a.label, fld))
    fig.tight_layout(); fig.savefig(out, dpi=150); plt.close(fig)
    print("  wrote %s (extract; range %.3g..%.3g %s, grid %dx%d)" % (out, vmin, vmax, a.unit, nx, ny))


if __name__ == "__main__":
    main()
