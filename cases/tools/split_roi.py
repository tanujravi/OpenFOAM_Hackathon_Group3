#!/usr/bin/env python3
"""
Split the recentred ROI surface into its 4 connected components (the four
receptors) and write each as its own triSurface for the dispersion case to
sample. Report centroids in recentred AND UTM coords (via transform.json).

Outputs to dispersionCase/constant/triSurface/:
  receptor1.obj .. receptor4.obj   (group 'receptorN')
  receptors.json                   centroids + UTM + counts
Ordered by descending size for stable IDs.
"""
import json, os, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load_obj(path):
    V, F = [], []
    for ln in open(path):
        if ln[:2] == "v ":
            V.append(tuple(float(x) for x in ln.split()[1:4]))
        elif ln[:2] == "f ":
            F.append([int(t.split("/")[0]) - 1 for t in ln.split()[1:]])
    return V, F


def components(nV, F):
    parent = list(range(nV))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    def uni(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    for f in F:
        for k in range(1, len(f)):
            uni(f[0], f[k])
    groups = {}
    for f in F:
        groups.setdefault(find(f[0]), []).append(f)
    return groups


def write_obj(path, name, vidx, V, F_sub, remap):
    with open(path, "w") as g:
        g.write("# receptor %s (recentred frame)\ng %s\no %s\n" % (name, name, name))
        for vi in vidx:
            x, y, z = V[vi]
            g.write("v %.6f %.6f %.6f\n" % (x, y, z))
        for f in F_sub:
            g.write("f %s\n" % " ".join(str(remap[i] + 1) for i in f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geo", default=os.path.join(ROOT, "flowCase", "geo"),
                    help="case geo/ dir with ROI.obj + transform.json")
    ap.add_argument("--out", default=os.path.join(ROOT, "dispersionCase", "constant", "triSurface"),
                    help="triSurface output dir")
    args = ap.parse_args()
    GEO = args.geo
    ROI = os.path.join(GEO, "ROI.obj")
    TRANSFORM = os.path.join(GEO, "transform.json")
    OUTDIR = args.out
    os.makedirs(OUTDIR, exist_ok=True)
    V, F = load_obj(ROI)
    groups = components(len(V), F)
    off = json.load(open(TRANSFORM))["offset_applied"]
    dx, dy, dz = off["dx"], off["dy"], off["dz"]

    comps = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    meta = []
    for n, (root, faces) in enumerate(comps, start=1):
        vidx = sorted({i for f in faces for i in f})
        remap = {vi: j for j, vi in enumerate(vidx)}
        name = "receptor%d" % n
        write_obj(os.path.join(OUTDIR, name + ".obj"), name, vidx, V, faces, remap)
        cx = sum(V[i][0] for i in vidx) / len(vidx)
        cy = sum(V[i][1] for i in vidx) / len(vidx)
        cz = sum(V[i][2] for i in vidx) / len(vidx)
        meta.append({"id": name, "n_faces": len(faces), "n_verts": len(vidx),
                     "centroid_recentred": [round(cx, 2), round(cy, 2), round(cz, 2)],
                     "centroid_utm": [round(cx - dx, 2), round(cy - dy, 2), round(cz - dz, 2)],
                     "site_name": "TBD (confirm on map)"})
        print("%s: %d faces  recentred(%.1f %.1f %.1f)  UTM(%.1f %.1f %.1f)"
              % (name, len(faces), cx, cy, cz, cx - dx, cy - dy, cz - dz))
    json.dump(meta, open(os.path.join(OUTDIR, "receptors.json"), "w"), indent=2)
    print("wrote %d receptor surfaces + receptors.json" % len(meta))


if __name__ == "__main__":
    main()
