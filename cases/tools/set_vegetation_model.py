#!/usr/bin/env python3
"""
Switch the vegetation model for the big-domain cases, BEFORE meshing.

  porous : canopy = volumetric Darcy-Forchheimer momentum sink + T uptake in a
           'vegetationZone' cellZone (topoSet). No Vegetation patch, no veg surface
           in snappy. (Robust on the elevated-canopy / coarse far-field mesh.)
  wall   : canopy = a snapped 'Vegetation' noSlip wall with roughness z0 in the atm
           wall functions (the Rotterdam case example / guideline method). Veg surface added to
           snappy; no fvOptions/topoSet.

The two modes give DIFFERENT meshes (patch vs no-patch), so pick the mode, then
(re)mesh that flavour on x86. Idempotent: re-running resets then applies cleanly.

  python3 set_vegetation_model.py --flow ../flowCaseBig --disp ../dispersionCaseBig --model porous
  python3 set_vegetation_model.py --flow ../flowCaseBig --disp ../dispersionCaseBig --model wall --z0 0.8
"""
import argparse, os, re, sys

# ----- wall-mode Vegetation patch BCs (one land-cover type: vegetation) -----
WALL_BC = {
    "U":       "    Vegetation { type noSlip; }\n",
    "p":       "    Vegetation { type zeroGradient; }\n",
    "k":       "    Vegetation { type kqRWallFunction; value uniform $kInlet; }\n",
    "epsilon": ("    Vegetation\n    {\n        type atmEpsilonWallFunction;\n"
                "        #include \"include/ABLConditions\"\n        z0 $z0vegetation;\n"
                "        value uniform $epsilonInlet;\n    }\n"),
    "nut":     ("    Vegetation\n    {\n        type atmNutkWallFunction;\n"
                "        z0 $z0vegetation;\n        value uniform 0;\n    }\n"),
}
T_WALL_BC = "    Vegetation { type fixedValue; value uniform 0; }\n"   # initial-trial sink

VEG_BEGIN, VEG_END = "// VEG-BEGIN\n", "// VEG-END\n"
SNAPPY_GEOM = ('// VEG-BEGIN\n'
    '    Mesh_Vegetation { type triSurfaceMesh; file "Mesh_Vegetation.obj";'
    ' regions { Vegetation { name Vegetation; } } }\n// VEG-END\n')
SNAPPY_REFS = ('// VEG-BEGIN\n'
    '        Mesh_Vegetation { level (0 0); regions { Vegetation'
    ' { level (5 5); patchInfo { type wall; } } } }\n// VEG-END\n')

FVOPT_FLOW = '''/*------ fvOptions: vegetation canopy POROUS momentum sink (vegetationZone) ------*/
FoamFile { version 2.0; format ascii; class dictionary; object fvOptions; }
vegetationCanopy
{
    type            explicitPorositySource;
    explicitPorositySourceCoeffs
    {
        type          DarcyForchheimer;
        selectionMode cellZone;
        cellZone      vegetationZone;
        d   (0 0 0);
        f   (%(f)s %(f)s %(fz)s);   // = 2*Cd*LAD [1/m]; TUNE to leaf-area density
        coordinateSystem { origin (0 0 0); e1 (1 0 0); e2 (0 1 0); }
    }
}
'''
FVOPT_DISP = '''/*------ fvOptions: vegetation pollutant uptake (vegetationZone) ------*/
FoamFile { version 2.0; format ascii; class dictionary; object fvOptions; }
// INITIAL TRIAL: pin T=0 in the canopy cells (perfect volumetric sink).
vegetationUptake
{
    type            fixedValueConstraint;
    selectionMode   cellZone;
    cellZone        vegetationZone;
    fieldValues     { T 0; }
}
// LATER deposition (-lambda*T): swap for scalarSemiImplicitSource, injectionRateSuSp { T (0 -1e-3); }
'''
TOPOSET = '''/*------ topoSetDict: build 'vegetationZone' (porous canopy) ------*/
FoamFile { version 2.0; format ascii; class dictionary; object topoSetDict; }
actions
(
    {
        name vegetationCells; type cellSet; action new; source surfaceToCell;
        sourceInfo
        {
            file "constant/triSurface/Mesh_Vegetation.obj"; useSurfaceOrientation false;
            outsidePoints ((0 0 1500)); includeCut true; includeInside false;
            includeOutside false; nearDistance %(near)s; curvature -100;
        }
    }
    { name vegetationZone; type cellZoneSet; action new; source setToCellZone; sourceInfo { set vegetationCells; } }
);
'''


def strip_veg_patch(field_path):
    s = open(field_path, encoding="utf-8").read()
    s = re.sub(r'(?ms)^[ \t]*Vegetation\b\s*\{.*?\}[ \t]*\n', '', s)
    open(field_path, "w", encoding="utf-8").write(s)


def add_veg_patch(field_path, entry):
    s = open(field_path, encoding="utf-8").read()
    if re.search(r'(?m)^[ \t]*Vegetation\b\s*\{', s):
        return
    # insert just before the boundaryField closing brace (last '}' of the file's BF block)
    m = list(re.finditer(r'\n\}', s))
    if not m:
        sys.exit("no closing brace in %s" % field_path)
    i = m[-1].start() + 1
    open(field_path, "w", encoding="utf-8").write(s[:i] + entry + s[i:])


def strip_snappy_veg(snappy):
    s = open(snappy, encoding="utf-8").read()
    s = re.sub(re.escape(VEG_BEGIN) + r'.*?' + re.escape(VEG_END), '', s, flags=re.S)
    open(snappy, "w", encoding="utf-8").write(s)


def add_snappy_veg(snappy):
    s = open(snappy, encoding="utf-8").read()
    if "VEG-BEGIN" in s:
        return
    s = re.sub(r'(?m)^(geometry\s*\n\{[ \t]*\n)', r'\1' + SNAPPY_GEOM, s, count=1)
    s = re.sub(r'(?m)^([ \t]*refinementSurfaces\s*\n[ \t]*\{[ \t]*\n)', r'\1' + SNAPPY_REFS, s, count=1)
    open(snappy, "w", encoding="utf-8").write(s)


def ensure_z0veg(abl, z0):
    s = open(abl, encoding="utf-8").read()
    if re.search(r'(?m)^\s*z0vegetation\b', s):
        s = re.sub(r'(?m)^(\s*z0vegetation\s+).*?;', r'\1uniform %s;' % z0, s)
    else:
        s = re.sub(r'(?m)^(\s*z0\s+uniform.*?;.*\n)', r'\1z0vegetation         uniform %s;   // canopy roughness\n' % z0, s, count=1)
    open(abl, "w", encoding="utf-8").write(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flow", required=True)
    ap.add_argument("--disp", required=True)
    ap.add_argument("--model", choices=["porous", "wall"], required=True)
    ap.add_argument("--z0", default="0.8", help="wall mode: canopy roughness [m] (forest~0.8, grass~0.03)")
    ap.add_argument("--f", default="0.4", help="porous mode: Forchheimer f horizontal = 2*Cd*LAD")
    ap.add_argument("--fz", default="0.04", help="porous mode: Forchheimer f vertical")
    ap.add_argument("--near", default="10", help="porous mode: topoSet canopy band [m]")
    a = ap.parse_args()
    F, D = a.flow, a.disp
    snappy = os.path.join(F, "system", "snappyHexMeshDict")

    # ---- RESET (idempotent): clear any prior vegetation config from both modes ----
    for fld in WALL_BC:
        strip_veg_patch(os.path.join(F, "0", fld))
    strip_veg_patch(os.path.join(D, "0", "T"))
    if os.path.isfile(snappy):
        strip_snappy_veg(snappy)
    for p in (os.path.join(F, "constant", "fvOptions"),
              os.path.join(D, "constant", "fvOptions"),
              os.path.join(F, "system", "topoSetDict")):
        if os.path.isfile(p):
            os.remove(p)

    # ---- APPLY ----
    if a.model == "porous":
        open(os.path.join(F, "constant", "fvOptions"), "w").write(FVOPT_FLOW % {"f": a.f, "fz": a.fz})
        open(os.path.join(D, "constant", "fvOptions"), "w").write(FVOPT_DISP)
        open(os.path.join(F, "system", "topoSetDict"), "w").write(TOPOSET % {"near": a.near})
        print("model=porous: fvOptions (f=%s) + topoSetDict (near=%s) written; no Vegetation patch; veg NOT in snappy." % (a.f, a.near))
    else:
        for fld, entry in WALL_BC.items():
            add_veg_patch(os.path.join(F, "0", fld), entry)
        add_veg_patch(os.path.join(D, "0", "T"), T_WALL_BC)
        ensure_z0veg(os.path.join(F, "0", "include", "ABLConditions"), a.z0)
        if os.path.isfile(snappy):
            add_snappy_veg(snappy)
        print("model=wall: Vegetation noSlip patch + z0vegetation=%s added; veg surface in snappy; no fvOptions/topoSet." % a.z0)
    for c in (F, D):
        open(os.path.join(c, ".veg_model"), "w").write(a.model + "\n")
    print("recorded .veg_model=%s in both cases." % a.model)
    print("Re-mesh this flavour on x86, then decompose. (Modes give different meshes.)")


if __name__ == "__main__":
    main()
