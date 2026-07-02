#!/usr/bin/env python3
"""
Headless mesh-inspection figures (ParaView 6.0.1 pvbatch) for a big OpenFOAM case.

Reads the DECOMPOSED case (processor*/) so you never have to reconstruct a 40M-cell
mesh onto one node. Run in parallel over the decomposition for speed/memory:

    mpirun -np <Nprocs> pvbatch pv_mesh_inspect.py --case ../flowCaseBig --out meshfigs
    # serial is fine for surfaces-only on a modest mesh:
    pvbatch pv_mesh_inspect.py --case ../flowCaseBig --no-slice --out meshfigs

Outputs (PNGs in --out):
  mesh_surfaces.png    Buildings+streets+Terrain as Surface-With-Edges, coloured by
                       cellLevel (refinement level) -> see street/building resolution
  mesh_slice_<axis>.png  a slice through the domain, Surface-With-Edges + cellLevel
                       -> see the box1/box2/far-field refinement transitions

Notes
- cellLevel/pointLevel are written by snappyHexMesh; if absent the script colours by
  a solid colour and warns.
- Reader / representation property names vary between ParaView builds, so optional
  steps are wrapped (safe()/setp()) -> the script keeps going and prints WARN.
"""
import argparse, os, sys

try:
    from paraview.simple import *           # noqa: F401,F403
except Exception as exc:                    # pragma: no cover
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
        print("WARN: skipped %s (%s)" % (what, e))
        return None


def ensure_foam(case):
    if os.path.isfile(case) and case.endswith((".foam", ".OpenFOAM")):
        return case
    d = case if os.path.isdir(case) else os.path.dirname(case) or "."
    stub = os.path.join(d, "case.foam")
    if not os.path.exists(stub):
        open(stub, "w").close()
    return stub


def make_reader(name, foam, regions, case_type, want_level):
    r = OpenFOAMReader(registrationName=name, FileName=foam)
    setp(r, "CaseType", case_type)
    setp(r, "MeshRegions", regions)
    if want_level:
        setp(r, "CellArrays", ["cellLevel"])
    r.UpdatePipeline()
    return r


def colour_by_level(disp, view, reader):
    """Colour by cellLevel if present; else a flat grey. Returns the array name or None."""
    has = "cellLevel" in list(reader.CellData.keys())
    if has:
        ColorBy(disp, ("CELLS", "cellLevel"))
        lut = GetColorTransferFunction("cellLevel")
        arr = reader.CellData.GetArray("cellLevel")
        rng = arr.GetRange() if arr else (0, 6)
        safe(lambda: lut.RescaleTransferFunction(rng[0], rng[1]), "rescale cellLevel")
        safe(lambda: lut.ApplyPreset("Viridis (matplotlib)", True), "preset")
        safe(lambda: setattr(lut, "InterpretValuesAsCategories", 0), "category flag")
        safe(lambda: setattr(GetScalarBar(lut, view), "Title", "cellLevel"), "scalar bar")
        return "cellLevel"
    print("WARN: 'cellLevel' not found -> colouring solid grey (run after snappy to get it)")
    safe(lambda: ColorBy(disp, None), "solid colour")
    safe(lambda: setattr(disp, "DiffuseColor", [0.8, 0.8, 0.8]), "grey")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, help=".foam file or case directory")
    ap.add_argument("--out", default="meshfigs")
    ap.add_argument("--decomposed", dest="decomposed", action="store_true", default=True,
                    help="read processor*/ (default; no reconstruct needed)")
    ap.add_argument("--reconstructed", dest="decomposed", action="store_false",
                    help="read the serial reconstructed mesh instead")
    ap.add_argument("--patches", nargs="+", default=["Terrain", "Buildings", "streets"])
    ap.add_argument("--no-slice", action="store_true", help="skip the (heavy) volume slice")
    ap.add_argument("--slice-axis", choices=["x", "y", "z"], default="y")
    ap.add_argument("--slice-origin", nargs=3, type=float, default=[0.0, 0.0, 60.0])
    ap.add_argument("--res", nargs=2, type=int, default=[1800, 1100])
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    case_type = "Decomposed Case" if a.decomposed else "Reconstructed Case"

    foam = ensure_foam(a.case)
    view = GetActiveViewOrCreate("RenderView")
    view.ViewSize = a.res
    view.Background = [1, 1, 1]
    safe(lambda: setattr(view, "OrientationAxesVisibility", 1), "orientation axes")

    # ---------------- surfaces (light): patches only ----------------
    surf = make_reader("surf", foam, list(a.patches), case_type, want_level=True)
    ds = Show(surf, view)
    safe(lambda: setattr(ds, "Representation", "Surface With Edges"), "surface with edges")
    safe(lambda: setattr(ds, "EdgeColor", [0.15, 0.15, 0.15]), "edge colour")
    colour_by_level(ds, view, surf)
    ResetCamera(view)
    SaveScreenshot(os.path.join(a.out, "mesh_surfaces.png"), view, ImageResolution=a.res)
    print("wrote mesh_surfaces.png (patches: %s)" % ", ".join(a.patches))
    Hide(surf, view)

    # ---------------- slice (heavy): internal volume ----------------
    if not a.no_slice:
        def _slice():
            vol = make_reader("vol", foam, ["internalMesh"], case_type, want_level=True)
            sl = Slice(registrationName="slice", Input=vol)
            sl.SliceType = "Plane"
            sl.SliceType.Origin = a.slice_origin
            sl.SliceType.Normal = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}[a.slice_axis]
            sl.UpdatePipeline()
            d2 = Show(sl, view)
            safe(lambda: setattr(d2, "Representation", "Surface With Edges"), "slice edges")
            safe(lambda: setattr(d2, "EdgeColor", [0.15, 0.15, 0.15]), "slice edge colour")
            colour_by_level(d2, view, vol)
            ResetCamera(view)
            SaveScreenshot(os.path.join(a.out, "mesh_slice_%s.png" % a.slice_axis),
                           view, ImageResolution=a.res)
            print("wrote mesh_slice_%s.png (origin %s)" % (a.slice_axis, a.slice_origin))
            Hide(sl, view)
        safe(_slice, "volume slice")

    print("DONE -> %s" % a.out)


if __name__ == "__main__":
    main()
