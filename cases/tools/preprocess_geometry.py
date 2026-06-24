#!/usr/bin/env python3
"""
Recenter Guimaraes small-domain geometry into a CFD-friendly frame.

Transform (pure translation, no rotation/scale):
    X' = X - X0     X0 = terrain X bbox centre
    Y' = Y - Y0     Y0 = terrain Y bbox centre
    Z' = Z - Z0     Z0 = terrain Z minimum  (lowest ground -> 0)

Applied identically to every geometry input so they stay coregistered.
Wind (u,v) and per-segment emission factors are translation-invariant and
are NOT touched here.

Outputs (under geo/):
    Mesh_Terrain.obj        recentred, single group 'Terrain'
    Mesh_Buildings.obj      buildings 0-5 merged (NO far-field _6), group 'Buildings'
    ROI.obj                 recentred receptors (4 components preserved)
    snapped_road_segments_recentred.csv
    transform.json          the offset + inverse, for back-mapping results to UTM

Canopy (canopy/merged.obj, 1.5 GB) is intentionally skipped: it is handled as a
porous zone later, not meshed, and will be transformed when that step is built.
"""
import os, json, glob, math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB   = os.path.join(ROOT, "terrain_and_buildings")
GEO  = os.path.join(ROOT, "geo")
os.makedirs(GEO, exist_ok=True)


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
    # transform a 'v x y z [w]' line; leave vn/vt untouched (translation only)
    p = ln.split()
    x = float(p[1]) + off[0]
    y = float(p[2]) + off[1]
    z = float(p[3]) + off[2]
    rest = " " + " ".join(p[4:]) if len(p) > 4 else ""
    return f"v {x:.6f} {y:.6f} {z:.6f}{rest}\n"


def transform_single(in_path, out_path, off, group):
    """Translate one OBJ, drop its groups, write one named group."""
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
            # skip existing g/o/s/usemtl/mtllib/comments
    return nv


def merge_objs(in_paths, out_path, off, group):
    """Concatenate several OBJs with correct index offsets into one group."""
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
                    # skip groups/comments/etc.
            v_tot += lv; vt_tot += lvt; vn_tot += lvn
    return v_tot, nf


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
        else:  # v/vt/vn  (vt may be empty: v//vn)
            vti = parts[1]
            vni = parts[2]
            vti = str(int(vti) + vt0) if vti else ""
            vni = str(int(vni) + vn0) if vni else ""
            out.append(f"{vi}/{vti}/{vni}")
    return " ".join(out) + "\n"


def bbox_of(path):
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
    terr_in = os.path.join(TB, "Mesh_Terrain.obj")
    b = terrain_bbox(terr_in)
    X0 = (b[0] + b[1]) / 2.0
    Y0 = (b[2] + b[3]) / 2.0
    Z0 = b[4]
    off = (-X0, -Y0, -Z0)
    print(f"Terrain bbox: X[{b[0]:.2f},{b[1]:.2f}] Y[{b[2]:.2f},{b[3]:.2f}] Z[{b[4]:.2f},{b[5]:.2f}]")
    print(f"Origin (X0,Y0,Z0) = ({X0:.3f}, {Y0:.3f}, {Z0:.3f})")
    print(f"Offset            = ({off[0]:.3f}, {off[1]:.3f}, {off[2]:.3f})")

    # 1) terrain
    nv = transform_single(terr_in, os.path.join(GEO, "Mesh_Terrain.obj"), off, "Terrain")
    print(f"[terrain]   {nv} verts -> geo/Mesh_Terrain.obj  bbox {tuple(round(x,1) for x in bbox_of(os.path.join(GEO,'Mesh_Terrain.obj')))}")

    # 2) buildings 0-5 merged (exclude far-field _6)
    bfiles = sorted(glob.glob(os.path.join(TB, "Mesh_Buildings_[0-5].obj")))
    vt, nf = merge_objs(bfiles, os.path.join(GEO, "Mesh_Buildings.obj"), off, "Buildings")
    print(f"[buildings] {len(bfiles)} files, {vt} verts, {nf} faces -> geo/Mesh_Buildings.obj  bbox {tuple(round(x,1) for x in bbox_of(os.path.join(GEO,'Mesh_Buildings.obj')))}")
    print(f"            (excluded: Mesh_Buildings_6 far-field)")

    # 3) ROI receptors
    roi_in = os.path.join(ROOT, "ROI", "ROI.obj")
    nv = transform_single(roi_in, os.path.join(GEO, "ROI.obj"), off, "ROI")
    print(f"[roi]       {nv} verts -> geo/ROI.obj  bbox {tuple(round(x,1) for x in bbox_of(os.path.join(GEO,'ROI.obj')))}")

    # 4) roads (snapped, has Z)
    roads_in = os.path.join(ROOT, "traffic", "snapped_road_segments.csv")
    nr = transform_roads(roads_in, os.path.join(GEO, "snapped_road_segments_recentred.csv"), off)
    print(f"[roads]     {nr} lines -> geo/snapped_road_segments_recentred.csv")

    # 5) transform record
    rec = {
        "description": "Pure translation; recentred frame for the small (6.3km) Guimaraes domain.",
        "origin_utm": {"X0": X0, "Y0": Y0, "Z0": Z0},
        "offset_applied": {"dx": off[0], "dy": off[1], "dz": off[2]},
        "to_recentred": "X' = X + dx ; Y' = Y + dy ; Z' = Z + dz",
        "to_utm_inverse": "X = X' - dx ; Y = Y' - dy ; Z = Z' - dz",
        "applied_to": ["Mesh_Terrain", "Mesh_Buildings_0..5 (merged)", "ROI", "snapped_road_segments"],
        "excluded": ["Mesh_Buildings_6 (far-field)", "canopy/merged.obj (porous, deferred)"],
        "invariant": ["wind u,v vectors", "emission factors"],
    }
    with open(os.path.join(GEO, "transform.json"), "w") as f:
        json.dump(rec, f, indent=2)
    print("[record]    geo/transform.json written")


if __name__ == "__main__":
    main()
