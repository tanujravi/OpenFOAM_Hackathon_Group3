#!/usr/bin/env python3
"""
POST-createPatch fix-up: ensure the new 'streets' patch has a boundaryField entry
in each 0/ field. createPatch adds 'streets' to constant/polyMesh/boundary but
does NOT always propagate it into pre-existing field files, which then crash the
solver / set_emissions. Here we CLONE the reference patch's entry (default
'Terrain', since the street faces are ex-Terrain ground) into each field if a
'streets' entry is missing. Idempotent.

Usage:
  python3 add_streets_bc.py --case cases/dispersionCase            # patches 0/U 0/phi 0/nut 0/T
  python3 add_streets_bc.py --case . --fields U phi nut --ref Terrain
"""
import argparse, os, re, sys


def patch_span(txt, name):
    """(start,end) of a 'name { ... }' boundaryField entry, brace-matched."""
    m = re.search(r"(?:^|\n)([ \t]*)" + re.escape(name) + r"\b", txt)
    if not m:
        return None
    try:
        i = txt.index("{", m.end())
    except ValueError:
        return None
    depth = 0
    j = i
    while j < len(txt):
        if txt[j] == "{":
            depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0:
                j += 1
                break
        j += 1
    return m.start(1), j      # from the entry's indentation to just past its '}'


def ensure_streets(field_path, ref="Terrain", new="streets"):
    txt = open(field_path).read()
    if re.search(r"(?:^|\n)[ \t]*" + re.escape(new) + r"\s*\{", txt):
        return "already has %s" % new
    span = patch_span(txt, ref)
    if span is None:
        return "SKIP (no '%s' entry to clone)" % ref
    a, b = span
    block = txt[a:b]                       # "    Terrain\n    { ... }"
    clone = block.replace(ref, new, 1)     # rename only the patch key
    out = txt[:b] + "\n" + clone + txt[b:]
    open(field_path, "w").write(out)
    return "added %s (cloned from %s)" % (new, ref)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="cases/dispersionCase")
    ap.add_argument("--fields", nargs="+", default=["U", "phi", "nut", "T"])
    ap.add_argument("--ref", default="Terrain")
    args = ap.parse_args()
    for fld in args.fields:
        fp = os.path.join(args.case, "0", fld)
        if not os.path.isfile(fp):
            print("  0/%-4s : (absent, skipped)" % fld)
            continue
        print("  0/%-4s : %s" % (fld, ensure_streets(fp, args.ref)))


if __name__ == "__main__":
    main()
