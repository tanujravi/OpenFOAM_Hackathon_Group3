# flowCaseBig - wind precursor on the BIG (25 km city4CFD) domain

Same pipeline as `../flowCase`, on the larger **25.2 × 25.2 km** city4CFD terrain
(`bigger_terrain_results/`), to study how domain size / boundary distance changes the
receptor results. **Recentred frame** (same X/Y origin as the small domain; Z0 =
big-terrain min = 74.29 m). Vegetation can be modelled two ways (a porous canopy zone or a roughness wall - see below).

The 196 roads and 4 receptors are the **same** as the small domain (same CRS), so
emission mapping and receptor sampling are identical; `../dispersionCaseBig`'s
`receptors.json` maps to the same four sites (Hospital, Francisco de Holanda,
Martins Sarmento, Santos Simões).

## What differs from the small case
- `geo/` recentred from `bigger_terrain_results/city4CFD` (terrain + buildings 0–6)
  by `../tools/preprocess_geometry.py` (see `geo/transform.json`).
- **Building surface is auto-cleaned.** Merging buildings 0–6 left **1247 duplicate /
  degenerate triangles** (`surfaceCheck`), which made snappy produce negative-volume
  cells. `preprocess_geometry.py` now dedups/de-degenerates the merged OBJ (via
  `../tools/clean_surface.py` logic); terrain was already clean.
- `system/blockMeshDict.m4`: `H=524`, inner square `s=1800` (covers the ROI),
  cylinder `Rcity=12500` m, **floor `z0=-150`** (see "bottom patch" below), top ≈ 1946 m.
- `system/snappyHexMeshDict`: **far-field terrain coarse**, **fine at the ROI** - see
  the table below. `locationInMesh (123.4 57.3 600)` (off the symmetry planes / grid
  lines, in the air).
- Reused: `0/` ABL BCs (+ a new `bottom` entry), the emission CSVs + wind, and the
  tools.

## Vegetation - two switchable models (porous | wall)
Pick the model **before meshing** with `../tools/set_vegetation_model.py --flow . --disp ../dispersionCaseBig --model porous|wall` (idempotent). The two modes give
**different meshes**, so re-mesh the chosen flavour on x86.
- `wall` = the Rotterdam case example / guideline method: a snapped `Vegetation` noSlip wall with
  roughness `z0` (`--z0`, forest~0.8). Adds the veg surface to snappy; flow-only.
- `porous` = canopy as a cellZone momentum sink + T uptake (below).

### porous canopy zone
Vegetation is **not** snapped as a wall - its surface drapes ~8 m above terrain across
the whole 25 km, so wall-snapping it in the coarse far field makes bad cells. It is a
**porous momentum sink** instead:
- `system/topoSetDict` builds a `vegetationZone` cellZone from `Mesh_Vegetation.obj`
  (`surfaceToCell`, ~8 m canopy band); `runallgeo.sh` runs `topoSet -parallel` after
  meshing so the zone lives in the decomposed mesh.
- `constant/fvOptions`: `explicitPorositySource` (Darcy-Forchheimer) canopy drag in that
  zone. **Tune** Forchheimer `f` (~2·Cd·LAD) and topoSet `nearDistance` (tree height).
- `../tools/preprocess_geometry.py --vegetation` recenters + cleans `Mesh_Vegetation.obj`.

The dispersion case reuses this decomposed mesh, so the zone carries over and applies the
canopy pollutant uptake there (see `../dispersionCaseBig/README.md`).

## Mesh resolution (buildings + streets)
Background inner-block cell = `2*s/Ns0 = 3600/24 = 150 m` (vert ~175 m); snappy halves
it per refinement level:

| region | level | cell size |
|---|---|---|
| far-field terrain | 2 | ~37.5 m |
| transition (box2) | 4 | ~9.4 m |
| **streets / ROI terrain** (box1) | 5 | **~4.7 m** (2–3 cells per road) |
| **buildings** (surface + feature edges) | 6 | **~2.3 m** (facade scale) |

Far terrain is deliberately coarse (it only shapes the approach flow); the detail is
concentrated in the ROI box + on the buildings. Expect **~30–45 M cells** (well above
the small case's ~1.7 M). To trade detail for cells: `box1` 5→4 (streets ~9.4 m) or
buildings 6→5 (~4.7 m). Always do a **castellated-only preview** (`snap false`) to read
the cell count before the full snap + solve.

## The `bottom` patch is KEPT here (not carved away)
On the small domain the flat floor patch `bottom` is carved away by snappy. On the big
domain the cylinder (r=12500) reaches just past the terrain's real coverage at a few
far edges, so `bottom` is a **genuine** lower boundary there and survives even with
`z0=-150`. It is therefore given a BC rather than fought:
`U` slip · `p`,`k`,`epsilon`,`omega` zeroGradient · `nut` calculated 0 · `T` (dispersion)
zeroGradient. It's a flat floor ~10 km from the receptors, so `slip` keeps it inert (no
spurious ground boundary layer).

## Meshing on the ARM nodes (memory-tight: ~30 GB / 48 cores)
`runallgeo.sh` is tuned for these nodes:
- `--mem=0` (grab all node RAM - without it SLURM caps at `DefMemPerCPU × ntasks`),
  and **few ranks/node** (`--ntasks-per-node=12`): each rank holds the full
  building+terrain search trees, so packing 48/node OOMs. Budget ~8–10 M cells per node;
  a ~40 M mesh wants ~6–8 nodes. `scotch` decomposition balances cells/rank.
- **No serial mesh reconstruct.** snappy runs `-overwrite` (final mesh → decomposed
  `constant/polyMesh`) and `srun redistributePar -reconstruct -constant -parallel`
  gathers it in parallel (the serial `reconstructParMesh` OOMs on 40 M).

## Flow solve (`job_flow.sh`, runs on x86)
- **4 nodes × 96 ranks** (`--mem=0`): `simpleFoam` is memory-bandwidth-bound, so spread
  the ranks - 128 on one node saturates bandwidth (~8 s/iter); 4×96 → ~1–1.5 s/iter.
- `fvSolution`: `residualControl 1e-5`, `nNonOrthogonalCorrectors 1` (re-check max
  non-orthogonality after the clean re-mesh; bump to 2 if it's still high).
- Flow fields reconstructed in parallel: `srun redistributePar -reconstruct -latestTime -parallel`.
- Two-stage schemes (1st-order warm-up → 2nd-order restart) as in the small case.

## Run a single hour
```bash
# 0. geometry: preprocess_geometry.py already recentres + cleans the buildings.
#    (or clean an existing OBJ:  python3 ../tools/clean_surface.py --in geo/Mesh_Buildings.obj \
#       --out geo/Mesh_Buildings.obj --group Buildings ; surfaceCheck geo/Mesh_Buildings.obj)

# 1. mesh once (ARM; --mem=0, ~12 ranks/node). Preview the count first if unsure:
#    foamDictionary -entry snap -set false system/snappyHexMeshDict ; sbatch runallgeo.sh ...
sbatch runallgeo.sh
#    CONFIRM the mesh is clean before solving:
srun checkMesh -parallel 2>/dev/null | grep -iE 'negative|orientation|aspect|non-ortho'

# 2. set this hour's wind:
python3 ../tools/set_wind.py --case . --hour 8

# 3. flow precursor (carve streets + 2-stage simpleFoam; 4 nodes x 96):
sbatch job_flow.sh

# 4. dispersion + receptor table (driver from cases/, pointed at the big cases):
cd ..
HOUR=8 SCENARIO=reference FLOW=./flowCaseBig DISP=./dispersionCaseBig sbatch run_single_hour.sh
```

> Visualise the mesh without reconstructing: `../postpro/pv_mesh_inspect.py` (reads the
> decomposed case, colours surfaces/slices by `cellLevel`).
> Regenerable: `geo/Mesh_*.obj` (rebuild via `preprocess_geometry.py`),
> `constant/polyMesh/`, `processor*/`, logs.
