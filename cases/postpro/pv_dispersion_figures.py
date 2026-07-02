#!/usr/bin/env python3
"""
Headless ParaView figures for the Guimaraes dispersion results.

RUN WITH ParaView 6.0.1's pvbatch (NOT plain python3):
    pvbatch pv_dispersion_figures.py --case ../dispersionCase \
        --label reference --fields T_CO T_NOx \
        --triSurface ../dispersionCase/constant/triSurface --out figs/reference

Produces, per field (T is kg/m^3 -> x1e9 = ug/m^3):
  <label>_<field>_iso.png        3-D plume isosurfaces (log-coloured) over the domain
  <label>_<field>_slice_z*.png   horizontal ground slice  (only with --slice-z)
  <label>_<field>_<receptor>.png each ROI surface coloured by what it "sees"

Notes
- The OpenFOAM reader / ResampleWithDataset property names vary across ParaView
  releases; every non-essential step is wrapped in safe()/try so the script keeps
  going and prints a WARN instead of crashing. If something is skipped, paste the
  WARN line back and the exact ParaView-6.0.1 property name can be pinned.
- Reads cell data, converts to point data for contouring.
"""
import argparse, glob, os, sys

try:
    from paraview.simple import *           # noqa: F401,F403
except Exception as exc:                    # pragma: no cover
    sys.exit("ERROR: run with ParaView's pvbatch -- 'paraview.simple' not importable (%s)" % exc)


def setp(proxy, name, value):
    """Set a proxy property only if it exists (versions rename them)."""
    if hasattr(proxy, name):
        try:
            setattr(proxy, name, value)
            return True
        except Exception as e:
            print("WARN: could not set %s=%r (%s)" % (name, value, e))
    return False


def safe(fn, what):
    try:
        return fn()
    except Exception as e:
        print("WARN: skipped %s (%s)" % (what, e))
        return None


def ensure_foam(case):
    """Accept a .foam/.OpenFOAM file or a case dir; return a .foam stub path."""
    if os.path.isfile(case) and case.endswith((".foam", ".OpenFOAM")):
        return case
    d = case if os.path.isdir(case) else os.path.dirname(case) or "."
    stub = os.path.join(d, "case.foam")
    if not os.path.exists(stub):
        open(stub, "w").close()
    return stub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, help=".foam file or case directory")
    ap.add_argument("--label", default="run", help="prefix for output PNG names (e.g. scenario)")
    ap.add_argument("--fields", nargs="+", default=["T_CO", "T_NOx"])
    ap.add_argument("--scale", type=float, default=1.0e9, help="kg/m^3 -> ug/m^3")
    ap.add_argument("--unit", default="ug/m3")
    ap.add_argument("--time", default="latest")
    ap.add_argument("--triSurface", default=None, help="dir with receptor*.obj")
    ap.add_argument("--out", default="figs")
    ap.add_argument("--res", nargs=2, type=int, default=[1600, 1000])
    ap.add_argument("--n-iso", type=int, default=4, help="number of log-spaced isosurfaces")
    ap.add_argument("--slice-z", type=float, default=None, help="z of an optional ground slice")
    ap.add_argument("--no-volume", action="store_true", help="skip the whole-air volume rendering")
    ap.add_argument("--vol-dims", nargs=3, type=int, default=[220, 220, 120],
                    help="ResampleToImage grid for volume rendering")
    ap.add_argument("--vol-opacity", type=float, default=0.5, help="max opacity of the densest air")
    ap.add_argument("--orbit", type=int, default=0, help="save N frames orbiting the volume (fly-around)")
    ap.add_argument("--preset", default="Viridis (matplotlib)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    foam = ensure_foam(a.case)
    reader = OpenFOAMReader(registrationName="dispcase", FileName=foam)
    setp(reader, "CaseType", "Reconstructed Case")
    setp(reader, "CellArrays", a.fields)
    setp(reader, "MeshRegions", ["internalMesh", "Terrain", "Buildings", "streets"])
    setp(reader, "Createcelltopointfiltereddata", 1)
    reader.UpdatePipeline()

    # TimestepValues may be a list, a vtk/numpy array, or a single float; coerce
    # every entry to a plain python float so UpdatePipeline(double) accepts it.
    try:
        times = [float(x) for x in reader.TimestepValues]
    except TypeError:
        _tv = reader.TimestepValues
        times = [float(_tv)] if _tv is not None else []
    t = (float(times[-1]) if a.time == "latest" else float(a.time)) if times else 0.0
    print("using time = %s (available: %s)" % (t, times))

    c2p = CellDatatoPointData(registrationName="c2p", Input=reader)
    c2p.UpdatePipeline(t)

    view = GetActiveViewOrCreate("RenderView")
    view.ViewSize = a.res
    view.Background = [1, 1, 1]
    safe(lambda: setattr(view, "OrientationAxesVisibility", 0), "hide orientation axes")

    avail = list(c2p.PointData.keys())
    print("point fields available: %s" % avail)

    for fld in a.fields:
        if fld not in avail:
            print("WARN: field '%s' not found -> skipping (check the FoamFile 'object' header)" % fld)
            continue
        ug = fld.replace("T_", "") + "_" + a.unit.replace("/", "")

        calc = Calculator(registrationName="calc_" + fld, Input=c2p)
        setp(calc, "AttributeType", "Point Data")
        calc.ResultArrayName = ug
        calc.Function = '"%s"*%g' % (fld, a.scale)
        calc.UpdatePipeline(t)

        arr = calc.PointData.GetArray(ug)
        rng = arr.GetRange() if arr else (0.0, 1.0)
        vmax = rng[1] if rng[1] > 0 else 1.0
        vmin = max(vmax * 1e-3, rng[0] if rng[0] > 0 else vmax * 1e-3)

        # ---------------- 3-D isosurfaces ----------------
        levels = sorted(vmax * (10.0 ** (-k)) for k in range(a.n_iso))
        cont = Contour(registrationName="iso_" + fld, Input=calc)
        cont.ContourBy = ["POINTS", ug]
        cont.Isosurfaces = levels
        cont.UpdatePipeline(t)

        Hide(reader, view); Hide(c2p, view); Hide(calc, view)
        disp = Show(cont, view)
        ColorBy(disp, ("POINTS", ug))
        lut = GetColorTransferFunction(ug)
        safe(lambda: lut.ApplyPreset(a.preset, True), "apply preset")
        safe(lambda: setp(lut, "UseLogScale", 1), "log colour scale")
        safe(lambda: lut.RescaleTransferFunction(vmin, vmax), "rescale colour range")
        safe(lambda: setattr(disp, "Opacity", 0.6), "set opacity")
        safe(lambda: setattr(GetScalarBar(lut, view), "Title", "%s [%s]" % (fld, a.unit)),
             "scalar bar title")
        ResetCamera(view)
        SaveScreenshot(os.path.join(a.out, "%s_%s_iso.png" % (a.label, fld)), view,
                       ImageResolution=a.res)
        Hide(cont, view)
        print("  wrote %s_%s_iso.png (range %.3g..%.3g %s, iso=%s)"
              % (a.label, fld, vmin, vmax, a.unit, ["%.2g" % x for x in levels]))

        # ---------------- whole-air VOLUME rendering ----------------
        if not a.no_volume:
            def _volume():
                ri = ResampleToImage(registrationName="ri_" + fld, Input=calc)
                setp(ri, "UseInputBounds", 1)
                setp(ri, "SamplingDimensions", a.vol_dims)
                ri.UpdatePipeline(t)
                Hide(cont, view)
                dv = Show(ri, view)
                try:
                    dv.SetRepresentationType("Volume")
                except Exception:
                    dv.Representation = "Volume"
                ColorBy(dv, ("POINTS", ug))
                lut2 = GetColorTransferFunction(ug)
                safe(lambda: lut2.ApplyPreset(a.preset, True), "volume preset")
                safe(lambda: setp(lut2, "UseLogScale", 1), "volume log scale")
                safe(lambda: lut2.RescaleTransferFunction(vmin, vmax), "volume rescale")
                # opacity ramp: clean air transparent, dense pollution opaque
                pwf = GetOpacityTransferFunction(ug)
                safe(lambda: setattr(pwf, "Points",
                     [vmin, 0.0, 0.5, 0.0, vmax, float(a.vol_opacity), 0.5, 0.0]),
                     "opacity ramp")
                safe(lambda: setattr(GetScalarBar(lut2, view), "Title", "%s [%s]" % (fld, a.unit)),
                     "volume scalar bar")
                ResetCamera(view)
                SaveScreenshot(os.path.join(a.out, "%s_%s_volume.png" % (a.label, fld)),
                               view, ImageResolution=a.res)
                if a.orbit > 0:
                    cam = GetActiveCamera()
                    for i in range(a.orbit):
                        cam.Azimuth(360.0 / a.orbit); Render()
                        SaveScreenshot(os.path.join(a.out, "%s_%s_volume_%03d.png" % (a.label, fld, i)),
                                       view, ImageResolution=a.res)
                Hide(ri, view)
                print("  wrote %s_%s_volume.png%s" % (a.label, fld,
                      ("  + %d orbit frames" % a.orbit) if a.orbit > 0 else ""))
            safe(_volume, "volume rendering")

        # ---------------- optional ground slice ----------------
        if a.slice_z is not None:
            def _slice():
                sl = Slice(registrationName="sl_" + fld, Input=calc)
                sl.SliceType = "Plane"
                sl.SliceType.Origin = [0.0, 0.0, a.slice_z]
                sl.SliceType.Normal = [0.0, 0.0, 1.0]
                sl.UpdatePipeline(t)
                ds = Show(sl, view); ColorBy(ds, ("POINTS", ug))
                GetColorTransferFunction(ug).RescaleTransferFunction(vmin, vmax)
                ResetCamera(view)
                SaveScreenshot(os.path.join(a.out, "%s_%s_slice_z%g.png" % (a.label, fld, a.slice_z)),
                               view, ImageResolution=a.res)
                Hide(sl, view)
            safe(_slice, "ground slice")

        # ---------------- receptor exposure ----------------
        if a.triSurface:
            for obj in sorted(glob.glob(os.path.join(a.triSurface, "receptor*.obj"))):
                rname = os.path.splitext(os.path.basename(obj))[0]
                def _recep(obj=obj, rname=rname):
                    rec = OpenDataFile(obj)
                    try:
                        rs = ResampleWithDataset(registrationName="rs_" + rname,
                                                 SourceDataArrays=calc, DestinationMesh=rec)
                    except TypeError:
                        rs = ResampleWithDataset(registrationName="rs_" + rname)
                        setp(rs, "SourceDataArrays", calc); setp(rs, "DestinationMesh", rec)
                        setp(rs, "Input", rec); setp(rs, "Source", calc)
                    rs.UpdatePipeline(t)
                    dr = Show(rs, view); ColorBy(dr, ("POINTS", ug))
                    GetColorTransferFunction(ug).RescaleTransferFunction(vmin, vmax)
                    ResetCamera(view)
                    SaveScreenshot(os.path.join(a.out, "%s_%s_%s.png" % (a.label, fld, rname)),
                                   view, ImageResolution=a.res)
                    Hide(rs, view)
                safe(_recep, "receptor %s" % rname)

    print("DONE -> %s" % a.out)


if __name__ == "__main__":
    main()
