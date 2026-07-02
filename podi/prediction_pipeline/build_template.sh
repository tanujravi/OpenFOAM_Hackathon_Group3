#!/bin/bash
# =====================================================================
# build_template.sh
# ---------------------------------------------------------------------
# Build a lightweight numpyToFoam/postProcess TEMPLATE case from the
# reference disp case, WITHOUT copying the bulky field data:
#
#   * processor*/constant  -> HARD-LINKED from the reference (same FS,
#                             read-only during our runs -> no GB copy)
#   * processor*/0/T       -> copied  (BC + dimension template for numpyToFoam)
#   * system/, constant/{triSurface,transportProperties,fvOptions,polyMesh-link}
#                          -> copied
#   * everything else (solved time dirs, nut/phi/U/T_CO, postProcessing) DROPPED
#
# Then it tweaks the case for our reuse:
#   * controlDict  writeFormat -> binary          (fast/small T writes)
#   * receptors    writeInterval -> 1             (a receptor row at every time)
#   * writes system/numpyToFoamDict               (fields (T), times 1..24)
#
# Usage:  bash build_template.sh            # uses defaults below
#         REF=... TPL=... bash build_template.sh
# =====================================================================
set -euo pipefail

REF=${REF:-/projects/F202500001HPCVLABEPICURE/ofoam.019/referenceCase-big/cases/workflow/runs_pod/disp/h0/CO}
TPL=${TPL:-/projects/F202500001HPCVLABEPICURE/tanuj/PODI/receptor_pipeline/template_case}
NHOURS=${NHOURS:-24}

[ -d "$REF/processor0/constant/polyMesh" ] || { echo "ERROR: no decomposed mesh in $REF"; exit 1; }
NP=$(ls -d "$REF"/processor* | wc -l)
echo "[build_template] REF=$REF  ($NP processors)"
echo "[build_template] TPL=$TPL"

rm -rf "$TPL"
mkdir -p "$TPL"

# ---- case-root system / constant / 0 (all small) -------------------- #
cp -r "$REF/system"   "$TPL/system"
cp -a "$REF/constant" "$TPL/constant"     # -a keeps the polyMesh symlink as a link
cp -r "$REF/0"        "$TPL/0"            # serial 0/T template (harmless, ~1 MB)

# ---- per-processor: symlink mesh (read-only) ----------------------- #
# Cross-owner hard links are blocked (protected_hardlinks), so symlink the
# reference constant/ dir per processor -- the mesh is only ever read.
#
# We deliberately do NOT seed processor*/0/T: the reference 0/T carries an
# inletOutlet BC that needs the flux field phi, and numpyToFoam's
# correctBoundaryConditions() would then fail ("failed lookup of phi").
# With no 0/T, numpyToFoam auto-creates T with phi-free 'calculated' BCs.
# The receptors area-average INTERIOR ROI cells, so the boundary type does
# not affect the sampled concentration.
echo "[build_template] symlinking $NP processor meshes ..."
for d in "$REF"/processor*; do
    p=$(basename "$d")
    mkdir -p "$TPL/$p"
    ln -s "$d/constant" "$TPL/$p/constant"       # symlink mesh (no data copy)
done

# ---- tweak case for reuse ------------------------------------------- #
# faster/smaller field writes
sed -i 's/^\([[:space:]]*writeFormat[[:space:]]*\)ascii;/\1binary;/' "$TPL/system/controlDict"
# emit a receptor value at every reconstructed time (default was every 100)
sed -i 's/writeInterval[[:space:]]*100;/writeInterval   1;/g' "$TPL/system/receptors"

# ---- numpyToFoamDict: reconstruct T at times 1..NHOURS -------------- #
cat > "$TPL/system/numpyToFoamDict" <<EOF
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      numpyToFoamDict;
}
// Reconstruct the pollutant field T for the 24 hours of one scenario.
// data/T/T_proc_<p>.npy has shape (nCells_p, $NHOURS) -> written to times 1..$NHOURS.
dataDir       data;
fields        (T);
time
{
    startTime     1;
    endTime       $NHOURS;
    deltaT        1;
}
EOF

echo "[build_template] done."
echo "  writeFormat : $(grep -m1 writeFormat "$TPL/system/controlDict")"
echo "  numpyToFoamDict times: 1..$NHOURS"
du -sh "$TPL" 2>/dev/null || true
