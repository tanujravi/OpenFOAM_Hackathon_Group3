# flowCaseBig — wind precursor on the BIG (25 km city4CFD) domain

Same workflow as `../flowCase`, on the larger **25.2 × 25.2 km** city4CFD terrain
(`bigger_terrain_results/`). Built to study how the larger domain / boundary
distance changes the receptor results. **Recentred frame** (same X/Y origin as the
small domain; Z0 = big-terrain min = 74.29 m). Vegetation is **not** meshed.

## What differs from the small case (only geometry + mesh sizing)
- `geo/` recentred from `bigger_terrain_results/city4CFD` (terrain + buildings 0–6)
  via `../tools/preprocess_geometry.py` (see `geo/transform.json`).
- `system/blockMeshDict.m4`: `H=524`, inner square `s=1800` (covers the ROI),
  cylinder `Rcity=12500` m (terrain half-extent is 12600 m; the cylinder inscribes
  the square — top ≈ 2086 m, floor −10 m).
- `system/snappyHexMeshDict`: **far-field terrain coarse** (`Terrain` surface level
  `(2 2)`), but **fine detail at the ROI** — `box1` region level **4** (streets +
  terrain near the roads), `box2` level 3, **buildings level 5** (+ feature edges,
  + distance refinement). The small case's global terrain-level-4 / terrain-distance
  rules were removed (they explode over 25 km).
- Reused unchanged: `0/` ABL BCs, `system/{fvSchemes*,fvSolution,controlDict,
  decomposeParDict}`, `runallgeo.sh`, `job_flow.sh`, and the emission CSVs + wind.

The 196 roads and the 4 receptors are the **same** as the small domain (same CRS),
so emission mapping and receptor sampling work identically;
`../dispersionCaseBig/constant/triSurface/receptors.json` is mapped to the same
four sites (Hospital, Francisco de Holanda, Martins Sarmento, Santos Simões).

## Mesh resolution (buildings + streets)

Background cell in the inner block is `2*s/Ns0 = 3600/24 = 150 m` (vert ~175 m);
snappy halves it at each refinement level:

| region | level | cell size |
|---|---|---|
| far-field terrain | 2 | ~37.5 m |
| transition (box2) | 3 | ~18.8 m |
| **streets / terrain at the ROI** (box1) | 4 | **~9.4 m** |
| **buildings** (surface + feature edges) | 5 | **~4.7 m** (vert ~5.5 m) |

- **Buildings ~4.7 m** — resolves individual building massing and (via the level-5
  feature edges) keeps corners/outlines crisp; matches the small-domain case (~4.2 m).
- **Streets ~9.4 m** — about **1 cell across** a typical 10-14 m road: enough to lift
  the emission off the street into the air (which sets the receptor concentrations),
  but not to resolve cross-street / street-canyon gradients. For 2-3 cells per road
  (~4.7 m), raise `box1` to level 5 (~8x the cells inside that box); push buildings to
  level 6 (~2.3 m) for facade-scale detail. Do a castellated-only preview first to
  check the total cell count.

## Run a single hour on the big domain
```bash
# 1. mesh once (cluster; minutes->~1 h is fine):
cd cases/flowCaseBig && sbatch runallgeo.sh
#    sanity-check the cell count BEFORE the long solve:
#    grep -iE "cells|Total" logs/snappyHex.log ; checkMesh -latestTime

# 2. set this hour's wind:
python3 ../tools/set_wind.py --case . --hour 8

# 3. flow precursor (carves the 'streets' patch, then 2-stage simpleFoam):
sbatch job_flow.sh

# 4. dispersion + receptor table — run the driver from cases/, pointed here:
cd ..
HOUR=8 SCENARIO=reference FLOW=./flowCaseBig DISP=./dispersionCaseBig sbatch run_single_hour.sh
```

> Cell count: far field is coarse but the ROI is level 4–5 over a much larger
> domain, so expect well above the small case's ~1.7 M cells. Do a castellated-only
> test first (or read `logs/snappyHex.log`) and adjust `box1`/buildings levels or
> `Rcity` if it overshoots your node budget.
> Regenerable: `geo/Mesh_*.obj` (rebuild with `preprocess_geometry.py`),
> `constant/polyMesh/`, `processor*/`, logs.
