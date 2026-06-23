#!/usr/bin/env python3
"""
POST-MESH: carve a single 'streets' wall patch out of the Terrain ground, made of
the ground faces lying under the road network. One patch, with a per-face ->
segment mapping recorded so a NON-UNIFORM fixedGradient (per-segment emission)
can be written onto it later (tools/set_emissions.py).

Run on the cluster AFTER the mesh exists (constant/polyMesh present, ASCII):
  python3 make_street_patches.py --case dispersionCase \
          --roads dispersionCase/geo/snapped_road_segments_recentred.csv \
          --half-width 5.0
then:
  createPatch -overwrite -case dispersionCase     # uses the createPatchDict written here

Outputs (under --case):
  constant/polyMesh/sets/streets        faceSet (global face labels), selection order
  system/createPatchDict                builds ONE 'streets' wall patch from that set
  geo/streets_face_segments.csv         face_label, segment_id, area  (set order)

Selection: a Terrain boundary face joins 'streets' if its centre is within
--half-width (metres, plan distance) of any road polyline; it is tagged with the
NEAREST segment id (= road id = CSV row index).

Self-test (no mesh needed):  python3 make_street_patches.py --selftest
"""
import argparse, csv, math, os, re, sys


# ----------------------------- geometry helpers -----------------------------
def pt_seg_dist2(px, py, ax, ay, bx, by):
    """squared planar distance from point P to segment AB."""
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0.0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = ((px - ax) * dx + (py - ay) * dy) / L2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def poly_area_3d(verts):
    """area of a planar polygon given as list of (x,y,z) via fan triangulation."""
    if len(verts) < 3:
        return 0.0
    ax, ay, az = verts[0]
    area2 = [0.0, 0.0, 0.0]
    for i in range(1, len(verts) - 1):
        bx, by, bz = verts[i]
        cx, cy, cz = verts[i + 1]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        area2[0] += uy * vz - uz * vy
        area2[1] += uz * vx - ux * vz
        area2[2] += ux * vy - uy * vx
    return 0.5 * math.sqrt(area2[0] ** 2 + area2[1] ** 2 + area2[2] ** 2)


def face_centre(verts):
    n = len(verts)
    return (sum(v[0] for v in verts) / n,
            sum(v[1] for v in verts) / n,
            sum(v[2] for v in verts) / n)


# ----------------------------- OpenFOAM ASCII IO ----------------------------
def _strip_header(txt):
    """drop the FoamFile {...} header block, return the rest."""
    m = re.search(r"FoamFile\s*\{.*?\}", txt, re.S)
    return txt[m.end():] if m else txt


def read_points(path):
    txt = _strip_header(open(path).read())
    m = re.search(r"(\d+)\s*\(", txt)
    body = txt[m.end():]
    pts = re.findall(r"\(\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s*\)", body)
    return [(float(a), float(b), float(c)) for a, b, c in pts]


def read_faces(path):
    txt = _strip_header(open(path).read())
    # consume the list header "<count> (" first, so only face entries remain
    m = re.search(r"(\d+)\s*\(", txt)
    body = txt[m.end():] if m else txt
    # each face entry: "k(v0 v1 ... vk-1)"  (OpenFOAM writes k immediately then '(')
    faces = []
    for fm in re.finditer(r"(\d+)\s*\(([^)]*)\)", body):
        n = int(fm.group(1))
        idx = [int(t) for t in fm.group(2).split()]
        if len(idx) == n and n >= 3:
            faces.append(idx)
    return faces


def read_boundary(path):
    txt = _strip_header(open(path).read())
    patches = {}
    for m in re.finditer(r"([A-Za-z0-9_]+)\s*\{([^}]*)\}", txt):
        name, body = m.group(1), m.group(2)
        nf = re.search(r"nFaces\s+(\d+)", body)
        sf = re.search(r"startFace\s+(\d+)", body)
        if nf and sf:
            patches[name] = (int(sf.group(1)), int(nf.group(1)))
    return patches


def write_faceset(path, name, labels):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("FoamFile\n{\n    version 2.0;\n    format ascii;\n"
                "    class faceSet;\n    location \"constant/polyMesh/sets\";\n"
                f"    object {name};\n}}\n\n")
        f.write(f"{len(labels)}\n(\n")
        for l in labels:
            f.write(f"{l}\n")
        f.write(")\n")


CREATEPATCH = """FoamFile
{{
    version 2.0; format ascii; class dictionary; object createPatchDict;
}}
// One 'streets' wall patch built from the carved ground faces (faceSet '{set}').
pointSync false;
patches
(
    {{
        name {patch};
        patchInfo {{ type wall; }}
        constructFrom set;
        set {set};
    }}
);
"""


# ----------------------------- roads ----------------------------------------
def read_roads(path):
    """list of segments; each is a list of (x,y) vertices (recentred frame)."""
    segs = []
    for line in open(path):
        nums = re.findall(r"(-?\d+\.?\d*(?:[eE][-+]?\d+)?)", line)
        if not nums:
            continue
        vals = [float(x) for x in nums]
        # LINESTRING Z -> triples (x y z); take x,y
        pts = [(vals[i], vals[i + 1]) for i in range(0, len(vals) - 2, 3)]
        if len(pts) >= 2:
            segs.append(pts)
    return segs


def nearest_segment(cx, cy, segs):
    best_i, best_d2 = -1, float("inf")
    for i, pts in enumerate(segs):
        for j in range(len(pts) - 1):
            d2 = pt_seg_dist2(cx, cy, pts[j][0], pts[j][1], pts[j+1][0], pts[j+1][1])
            if d2 < best_d2:
                best_d2, best_i = d2, i
    return best_i, math.sqrt(best_d2)


# ----------------------------- main carve -----------------------------------
def carve(case, roads_csv, terrain_patch, half_width, set_name, patch_name):
    pm = os.path.join(case, "constant", "polyMesh")
    pts = read_points(os.path.join(pm, "points"))
    faces = read_faces(os.path.join(pm, "faces"))
    bnd = read_boundary(os.path.join(pm, "boundary"))
    if terrain_patch not in bnd:
        sys.exit(f"ERROR: patch '{terrain_patch}' not in boundary {list(bnd)}")
    start, nf = bnd[terrain_patch]
    segs = read_roads(roads_csv)

    chosen = []      # (global_face_label, segment_id, area)
    for k in range(nf):
        gf = start + k
        verts = [pts[i] for i in faces[gf]]
        cx, cy, _ = face_centre(verts)
        seg, dist = nearest_segment(cx, cy, segs)
        if dist <= half_width:
            chosen.append((gf, seg, poly_area_3d(verts)))

    write_faceset(os.path.join(pm, "sets", set_name), set_name, [c[0] for c in chosen])
    with open(os.path.join(case, "system", "createPatchDict"), "w") as f:
        f.write(CREATEPATCH.format(set=set_name, patch=patch_name))
    mp = os.path.join(case, "geo", "streets_face_segments.csv")
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    with open(mp, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["face_label", "segment_id", "area_m2"])
        for gf, seg, a in chosen:
            w.writerow([gf, seg, f"{a:.6f}"])

    seg_hit = sorted({c[1] for c in chosen})
    print(f"Terrain faces scanned : {nf}")
    print(f"street faces selected : {len(chosen)}  (half-width {half_width} m)")
    print(f"segments with faces   : {len(seg_hit)} / {len(segs)}")
    print(f"total street area     : {sum(c[2] for c in chosen):.1f} m^2")
    print(f"wrote: {pm}/sets/{set_name}, system/createPatchDict, geo/streets_face_segments.csv")
    if len(seg_hit) < len(segs):
        miss = len(segs) - len(seg_hit)
        print(f"WARNING: {miss} segments got no faces -> raise --half-width or refine the mesh near roads")


# ----------------------------- self test ------------------------------------
def selftest():
    # point-segment distance
    assert abs(math.sqrt(pt_seg_dist2(0, 1, -1, 0, 1, 0)) - 1.0) < 1e-9
    assert abs(math.sqrt(pt_seg_dist2(2, 0, -1, 0, 1, 0)) - 1.0) < 1e-9  # past end
    # unit square area = 1
    sq = [(0,0,0),(1,0,0),(1,1,0),(0,1,0)]
    assert abs(poly_area_3d(sq) - 1.0) < 1e-9
    assert face_centre(sq) == (0.5, 0.5, 0.0)
    # nearest segment pick
    segs = [[(0,0),(10,0)], [(0,50),(10,50)]]
    i, d = nearest_segment(5, 2, segs); assert i == 0 and abs(d-2) < 1e-9
    i, d = nearest_segment(5, 48, segs); assert i == 1 and abs(d-2) < 1e-9
    # faceSet round-trip parse
    import tempfile
    d = tempfile.mkdtemp()
    fp = os.path.join(d, "streets"); write_faceset(fp, "streets", [3, 7, 11])
    txt = open(fp).read()
    assert "class faceSet" in txt and re.search(r"3\s*\(\s*3\s+7\s+11\s*\)", txt)
    # faces parser tolerates "n(...)"
    fcontent = ('FoamFile{}\n2\n(\n3(0 1 2)\n4(0 1 2 3)\n)\n')
    fpp = os.path.join(d, "faces"); open(fpp, "w").write(fcontent)
    fs = read_faces(fpp); assert fs == [[0,1,2],[0,1,2,3]], fs
    print("selftest: ALL PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="dispersionCase")
    ap.add_argument("--roads", default=None)
    ap.add_argument("--terrain-patch", default="Terrain")
    ap.add_argument("--half-width", type=float, default=5.0)
    ap.add_argument("--set-name", default="streets")
    ap.add_argument("--patch-name", default="streets")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest(); return
    roads = args.roads or os.path.join(args.case, "geo", "snapped_road_segments_recentred.csv")
    carve(args.case, roads, args.terrain_patch, args.half_width, args.set_name, args.patch_name)


if __name__ == "__main__":
    main()
