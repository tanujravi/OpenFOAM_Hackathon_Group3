#!/usr/bin/env python3
"""
Recenter Guimaraes geometry into a CFD-friendly frame (pure translation):
    X' = X - X0   X0 = terrain X bbox centre
    Y' = Y - Y0   Y0 = terrain Y bbox centre
    Z' = Z - Z0   Z0 = terrain Z minimum  (lowest ground -> 0)

Applied identically to every geometry input so they stay coregistered. Wind (u,v)
and per-segment emission factors are translation-invariant and are NOT touched.

Defaults reproduce the SMALL (6.3 km) domain exactly (terrain_and_buildings/ +
ROI/ + traffic/ -> cases/flowCase/geo). Override the paths to recenter the big
city4CFD domain into its own case, e.g.:

  python3 preprocess_geometry.py \
    --terrain   ../../bigger_terrain_results/city4CFD/Mesh_Terrain.obj \
    --buildings ../../bigger_terrain_results/city4CFD/Mesh_Buildings_0.obj ... _6.obj \
    --roi       ../../bigger_terrain_results/ROI/ROI.obj \
    --roads     ../../bigger_terrain_results/roads/snapped_road_segments.csv \
    --out       ../flowCaseBig/geo --label "big 25km city4CFD domain"

Outputs (under --out): Mesh_Terrain.obj, Mesh_Buildings.obj (merged),
ROI.obj, snapped_road_segments_recentred.csv, transform.json.
Canopy / vegetation is intentionally NOT meshed (porous-zone candidate).
"""
import os, json, glob, math, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def terrain_bbox(path):
    mnx = mny = mnz = math.inf
    mxx = mxy = mxz = -math.inf
    with open(path) as f:
        for ln in f:
            if ln[:2] == "v ":
                x, y, z = map(float, ln.split()[1:4])
                mnx = min(mnx, x); mxx = max(mxx, x)
                mny = min(mny, y); mxy = max(mxy, y)
                mnz = min(mnz, z); mxz = max(mxz, z)
    return mnx, mxx, mny, mxy, mnz, mxz


def shift_v(ln, off):
    p = ln.split()
    x = float(p[1]) + off[0]
    y = float(p[2]) + off[1]
    z = float(p[3]) + off[2]
    rest = " " + " ".join(p[4:]) if len(p) > 4 else ""
    return f"v {x:.6f} {y:.6f} {z:.6f}{rest}\n"


def transform_single(in_path, out_path, off, group):
    nv = 0
    with open(in_path) as fi, open(out_path, "w") as fo:
        fo.write(f"# recentred from {os.path.basename(in_path)}\n")
        fo.write(f"g {group}\no {group}\n")
        for ln in fi:
            t = ln[:2]
            if t == "v ":
                fo.write(shift_v(ln, off)); nv += 1
            elif ln[:3] in ("vn ", "vt "):
                fo.write(ln)
            elif ln[:2] == "f " or ln[:2] == "l ":
                fo.write(ln)
    return nv


def _offset_face(ln, v0, vt0, vn0):
    out = ["f"]
    for tok in ln.split()[1:]:
        parts = tok.split("/")
        vi = int(parts[0]) + v0
        if len(parts) == 1:
            out.append(str(vi))
        elif len(parts) == 2:
            vti = parts[1]
            vti = str(int(vti) + vt0) if vti else ""
            out.append(f"{vi}/{vti}")
        else:
            vti = parts[1]; vni = parts[2]
            vti = str(int(vti) + vt0) if vti else ""
            vni = str(int(vni) + vn0) if vni else ""
            out.append(f"{vi}/{vti}/{vni}")
    return " ".join(out) + "\n"


def merge_objs(in_paths, out_path, off, group):
    v_tot = vt_tot = vn_tot = 0
    nf = 0
    with open(out_path, "w") as fo:
        fo.write(f"# merged + recentred: {', '.join(os.path.basename(p) for p in in_paths)}\n")
        fo.write(f"g {group}\no {group}\n")
        for p in in_paths:
            v0, vt0, vn0 = v_tot, vt_tot, vn_tot
            lv = lvt = lvn = 0
            with open(p) as fi:
                for ln in fi:
                    t2 = ln[:2]; t3 = ln[:3]
                    if t2 == "v ":
                        fo.write(shift_v(ln, off)); lv += 1
                    elif t3 == "vt ":
                        fo.write(ln); lvt += 1
                    elif t3 == "vn ":
                        fo.write(ln); lvn += 1
                    elif t2 == "f ":
                        fo.write(_offset_face(ln, v0, vt0, vn0)); nf += 1
            v_tot += lv; vt_tot += lvt; vn_tot += lvn
    return v_tot, nf


def bbox_of(path):
    return terrain_bbox(path)


def transform_roads(in_csv, out_csv, off):
    import re
    n = 0
    with open(in_csv) as fi, open(out_csv, "w") as fo:
        for ln in fi:
            def repl(m):
                x, y, z = float(m.group(1)), float(m.group(2)), float(m.group(3))
                return f"{x+off[0]:.6f} {y+off[1]:.6f} {z+off[2]:.6f}"
            new = re.sub(r"(-?\d+\.?\d*)\s+(-?\d+\.?\d*)\s+(-?\d+\.?\d*)", repl, ln)
            fo.write(new); n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--terrain", default=os.path.join(ROOT, "terrain_and_buildings", "Mesh_Terrain.obj"))
    ap.add_argument("--buildings", nargs="+", default=None,
                    help="building OBJs to merge (default: terrain_and_buildings/Mesh_Buildings_[0-5].obj)")
    ap.add_argument("--roi", default=os.path.join(ROOT, "ROI", "ROI.obj"))
    ap.add_argument("--roads", default=os.path.join(ROOT, "traffic", "snapped_road_segments.csv"))
    ap.add_argument("--out", default=os.path.join(ROOT, "cases", "flowCase", "geo"))
    ap.add_argument("--label", default="small (6.3km) Guimaraes domain")
    args = ap.parse_args()

    GEO = args.out
    os.makedirs(GEO, exist_ok=True)
    bfiles = sorted(args.buildings) if args.buildings else \
        sorted(glob.glob(os.path.join(ROOT, "terrain_and_buildings", "Mesh_Buildings_[0-5].obj")))

    b = terrain_bbox(args.terrain)
    X0 = (b[0] + b[1]) / 2.0
    Y0 = (b[2] + b[3]) / 2.0
    Z0 = b[4]
    off = (-X0, -Y0, -Z0)
    print(f"Terrain bbox: X[{b[0]:.2f},{b[1]:.2f}] Y[{b[2]:.2f},{b[3]:.2f}] Z[{b[4]:.2f},{b[5]:.2f}]")
    print(f"Origin (X0,Y0,Z0) = ({X0:.3f}, {Y0:.3f}, {Z0:.3f})  offset = ({off[0]:.3f}, {off[1]:.3f}, {off[2]:.3f})")

    nv = transform_single(args.terrain, os.path.join(GEO, "Mesh_Terrain.obj"), off, "Terrain")
    print(f"[terrain]   {nv} verts -> {GEO}/Mesh_Terrain.obj  bbox {tuple(round(x,1) for x in bbox_of(os.path.join(GEO,'Mesh_Terrain.obj')))}")

    vt, nf = merge_objs(bfiles, os.path.join(GEO, "Mesh_Buildings.obj"), off, "Buildings")
    print(f"[buildings] {len(bfiles)} files, {vt} verts, {nf} faces -> {GEO}/Mesh_Buildings.obj")

    nv = transform_single(args.roi, os.path.join(GEO, "ROI.obj"), off, "ROI")
    print(f"[roi]       {nv} verts -> {GEO}/ROI.obj  bbox {tuple(round(x,1) for x in bbox_of(os.path.join(GEO,'ROI.obj')))}")

    nr = transform_roads(args.roads, os.path.join(GEO, "snapped_road_segments_recentred.csv"), off)
    print(f"[roads]     {nr} lines -> {GEO}/snapped_road_segments_recentred.csv")

    rec = {
        "description": "Pure translation; recentred frame for the %s." % args.label,
        "origin_utm": {"X0": X0, "Y0": Y0, "Z0": Z0},
        "offset_applied": {"dx": off[0], "dy": off[1], "dz": off[2]},
        "to_recentred": "X' = X + dx ; Y' = Y + dy ; Z' = Z + dz",
        "to_utm_inverse": "X = X' - dx ; Y = Y' - dy ; Z = Z' - dz",
        "inputs": {"terrain": args.terrain, "buildings": bfiles, "roi": args.roi, "roads": args.roads},
        "invariant": ["wind u,v vectors", "emission factors"],
    }
    with open(os.path.join(GEO, "transform.json"), "w") as f:
        json.dump(rec, f, indent=2)
    print(f"[record]    {GEO}/transform.json written")


if __name__ == "__main__":
    main()
