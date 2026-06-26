#!/usr/bin/env python3
"""
Clean a triangulated surface OBJ for snappyHexMesh: weld coincident vertices, drop
duplicate faces (exact + flipped) and degenerate (zero-area) triangles. Fixes the
'illegal triangles' that surfaceCheck reports after merging several building OBJs
(shared walls / overlapping files), which otherwise make snappy create
negative-volume / huge-aspect-ratio cells.

Writes a clean OBJ with a single named group (so snappyHexMeshDict's
regions { <group> { name <group>; } } still resolves).

  python3 clean_surface.py --in geo/Mesh_Buildings.obj --out geo/Mesh_Buildings.obj --group Buildings
"""
import argparse, os, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--group", default="Buildings")
    a = ap.parse_args()
    try:
        import numpy as np, trimesh
    except Exception as e:
        sys.exit("ERROR: needs numpy+trimesh (pip install --break-system-packages trimesh): %s" % e)

    # force='mesh' concatenates all OBJ objects into one Trimesh; process=True does an
    # initial merge_vertices + duplicate/degenerate removal.
    m = trimesh.load(a.inp, force="mesh", process=True, maintain_order=False)
    nf0, nv0 = len(m.faces), len(m.vertices)

    safe = lambda fn, *x: (fn(*x) if True else None)
    try: m.merge_vertices()
    except Exception as e: print("WARN merge_vertices:", e)
    # drop duplicate faces (winding-insensitive) -- API differs across versions
    try:
        m.update_faces(m.unique_faces())
    except Exception:
        if hasattr(m, "remove_duplicate_faces"):
            try: m.remove_duplicate_faces()
            except Exception as e: print("WARN dup faces:", e)
    # drop degenerate (zero-area) faces
    try:
        m.update_faces(m.nondegenerate_faces())
    except Exception:
        if hasattr(m, "remove_degenerate_faces"):
            try: m.remove_degenerate_faces()
            except Exception as e: print("WARN degenerate:", e)
    try: m.remove_unreferenced_vertices()
    except Exception: pass

    V, F = m.vertices, m.faces
    with open(a.out, "w") as f:
        f.write("# cleaned from %s (weld + dedup + de-degenerate)\n" % os.path.basename(a.inp))
        f.write("g %s\no %s\n" % (a.group, a.group))
        for v in V:
            f.write("v %.6f %.6f %.6f\n" % (v[0], v[1], v[2]))
        for t in F:
            f.write("f %d %d %d\n" % (t[0] + 1, t[1] + 1, t[2] + 1))
    print("faces %d -> %d   verts %d -> %d   (removed %d faces)"
          % (nf0, len(F), nv0, len(V), nf0 - len(F)))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
