#!/usr/bin/env python3
"""
Write the per-segment emission as a NON-UNIFORM fixedGradient onto the single
'streets' patch in <case>/0/T, for one pollutant / hour / scenario.

Order: createPatch (run first) carves 'streets' and adds it to every field,
inheriting Terrain's zeroGradient. This tool then REWRITES the streets block in
0/T to a per-segment fixedGradient.

Depends on:
  * geo/streets_face_segments.csv   (make_street_patches.py: face order, seg, area)
  * map_emissions.py                (per-segment scaled emission, this scenario)

Flux model: face f of segment s -> gradient_f = flux_s / DT,
  flux_s = (E_s * unit_scale) / A_s   [kg/(m^2 s)]
  E_s scaled CSV value, A_s total carved street area of s, unit_scale g/h->kg/s.
With T in kg/m^3 the field is an absolute concentration; DT*grad*area = kg/s.
"""
import argparse, csv, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import map_emissions as me


def load_face_map(path):
    faces = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            faces.append((int(row["segment_id"]), float(row["area_m2"])))
    return faces


def per_segment_values(pollutant, hour, scenario):
    header, data = me.load_factors(pollutant)
    col = me.hour_column(header, hour)
    scale = me.scenario_scale(scenario, len(data))
    return [data[i][col] * scale[i] for i in range(len(data))], header[col]


def write_nonuniform_gradient(t_path, grads):
    txt = open(t_path).read()
    lst = "nonuniform List<scalar> \n%d\n(\n%s\n)" % (
        len(grads), "\n".join("%.10g" % g for g in grads))
    body = ("\n        type            fixedGradient;\n"
            "        gradient        %s;\n    " % lst)
    if re.search(r"(^|\n)\s*streets\s*\{", txt):
        # replace the existing streets{...} body (zeroGradient from createPatch
        # or a previous fixedGradient)
        new, n = re.subn(r"(streets\s*\{).*?(\})",
                         lambda m: m.group(1) + body + m.group(2),
                         txt, count=1, flags=re.S)
    else:
        # createPatch did not propagate the patch into the field -> insert it
        entry = "    streets\n    {%s}\n" % body
        new, n = re.subn(r"(boundaryField\s*\{[ \t]*\n)",
                         lambda m: m.group(1) + entry, txt, count=1)
    if n != 1:
        sys.exit("ERROR: could not write streets gradient in %s "
                 "(no streets block and no boundaryField{ found)" % t_path)
    open(t_path, "w").write(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="dispersionCase")
    ap.add_argument("--pollutant", choices=["CO", "NOx"], required=True)
    ap.add_argument("--hour", required=True)
    ap.add_argument("--scenario", default="reference")
    ap.add_argument("--DT", type=float, default=1.0)
    ap.add_argument("--unit-scale", type=float, default=1.0 / 3.6e6)  # g/h -> kg/s
    ap.add_argument("--face-map", default=None)
    ap.add_argument("--field", default=None, help="explicit T file to edit (default <case>/0/T; transient uses a restart time dir)")
    args = ap.parse_args()

    fmap = args.face_map or os.path.join(args.case, "geo", "streets_face_segments.csv")
    if not os.path.isfile(fmap):
        sys.exit("ERROR: %s missing -- run make_street_patches.py first (needs the mesh)." % fmap)
    faces = load_face_map(fmap)
    vals, hour_label = per_segment_values(args.pollutant, args.hour, args.scenario)

    area_seg = {}
    for seg, a in faces:
        area_seg[seg] = area_seg.get(seg, 0.0) + a

    grads = []
    for seg, a in faces:
        A = area_seg[seg]
        flux = (vals[seg] * args.unit_scale) / A if A > 0 else 0.0
        grads.append(flux / args.DT)

    t_path = args.field or os.path.join(args.case, "0", "T")
    write_nonuniform_gradient(t_path, grads)
    print("pollutant=%s hour='%s' scenario=%s DT=%g unit_scale=%.6g"
          % (args.pollutant, hour_label, args.scenario, args.DT, args.unit_scale))
    print("wrote nonuniform gradient: %d faces over %d segments -> %s"
          % (len(grads), len(area_seg), t_path))
    print("gradient range: %.3e .. %.3e kg/m^4 (DT*grad*area = kg/s)"
          % (min(grads), max(grads)))


if __name__ == "__main__":
    main()
