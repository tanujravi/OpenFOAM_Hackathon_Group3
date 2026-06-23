#!/usr/bin/env python3
"""
ALTERNATIVE inlet treatment (better pressure convergence than all-round freestream).

POST-MESH: split the single cylindrical 'inletOutlet' patch into an upwind
'inlet' arc and a downwind 'outlet' arc, by the hour's wind direction. The
domain is centred on the origin, so for a side face at horizontal position
(cx,cy) the outward normal is ~radial; the wind w=(u,v) ENTERS where the face is
on the windward side, i.e. r.w < 0  -> inlet ; r.w >= 0 -> outlet.

Writes (under --case):
  constant/polyMesh/sets/inletFaces, .../outletFaces   faceSets
  system/createPatchDict_inletoutlet                    splits inletOutlet -> inlet + outlet
Then:  createPatch -overwrite -dict system/createPatchDict_inletoutlet
and copy the 0.split/ fields over 0/ (inlet=fixed wind, outlet=fixed p=0).

For THIS dataset the wind stays NW all day, so one split (any hour) serves all
hours; re-run per hour if the direction ever changes sign.

Self-test:  python3 split_inlet_outlet.py --selftest
"""
import argparse, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_street_patches as msp     # reuse polyMesh ASCII parsers
import set_wind as sw                 # reuse the wind-CSV loader


CREATEPATCH = """FoamFile
{{
    version 2.0; format ascii; class dictionary; object createPatchDict;
}}
// Split the all-round 'inletOutlet' ring into windward 'inlet' + leeward 'outlet'.
pointSync false;
patches
(
    {{ name inlet;  patchInfo {{ type patch; }} constructFrom set; set inletFaces;  }}
    {{ name outlet; patchInfo {{ type patch; }} constructFrom set; set outletFaces; }}
);
"""


def split(case, u, v, ring_patch):
    pm = os.path.join(case, "constant", "polyMesh")
    pts = msp.read_points(os.path.join(pm, "points"))
    faces = msp.read_faces(os.path.join(pm, "faces"))
    bnd = msp.read_boundary(os.path.join(pm, "boundary"))
    if ring_patch not in bnd:
        sys.exit("ERROR: patch '%s' not in boundary %s" % (ring_patch, list(bnd)))
    start, nf = bnd[ring_patch]
    inlet, outlet = [], []
    for k in range(nf):
        gf = start + k
        vs = [pts[i] for i in faces[gf]]
        cx = sum(p[0] for p in vs) / len(vs)
        cy = sum(p[1] for p in vs) / len(vs)
        s = cx * u + cy * v          # r . w  ; <0 windward (inlet)
        (inlet if s < 0 else outlet).append(gf)
    msp.write_faceset(os.path.join(pm, "sets", "inletFaces"), "inletFaces", inlet)
    msp.write_faceset(os.path.join(pm, "sets", "outletFaces"), "outletFaces", outlet)
    with open(os.path.join(case, "system", "createPatchDict_inletoutlet"), "w") as f:
        f.write(CREATEPATCH)
    print("wind (u,v) = (%.3f, %.3f)" % (u, v))
    print("inlet faces  : %d" % len(inlet))
    print("outlet faces : %d" % len(outlet))
    print("wrote sets/{inletFaces,outletFaces} + system/createPatchDict_inletoutlet")
    print("next: createPatch -overwrite -dict system/createPatchDict_inletoutlet -case %s" % case)
    if not inlet or not outlet:
        print("WARNING: one side is empty -- check the wind vector / patch name")


def selftest():
    # 4 faces around origin at +x,-x,+y,-y; wind +x => inlet on -x face (r.w<0)
    # emulate by checking the sign rule directly
    cases = [((10, 0), 1, 0, "outlet"), ((-10, 0), 1, 0, "inlet"),
             ((0, 10), 0, 1, "outlet"), ((0, -10), 0, 1, "inlet"),
             ((10, 0), -1, 0, "inlet")]
    for (cx, cy), u, v, want in cases:
        s = cx * u + cy * v
        got = "inlet" if s < 0 else "outlet"
        assert got == want, (cx, cy, u, v, got, want)
    print("selftest: ALL PASS (windward face -> inlet)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="cases/flowCase")
    ap.add_argument("--hour", default="0")
    ap.add_argument("--wind-csv", default=None)
    ap.add_argument("--ring-patch", default="inletOutlet")
    ap.add_argument("--u", type=float, default=None)
    ap.add_argument("--v", type=float, default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest(); return
    if args.u is not None and args.v is not None:
        u, v = args.u, args.v
    else:
        csv = args.wind_csv or os.path.join(
            os.path.dirname(os.path.abspath(args.case)), "..", "wind_data", "wind_velocity_time.csv")
        labels, us, vs = sw.load_wind(csv)
        i = sw.resolve_index(args.hour, labels)
        u, v = us[i], vs[i]
    split(args.case, u, v, args.ring_patch)


if __name__ == "__main__":
    main()
