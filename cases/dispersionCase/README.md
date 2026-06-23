# dispersionCase — pollutant transport (`scalarTransportFoam`)

Transports a passive pollutant scalar `T` on the **frozen** wind field from
`../initialCase`, with traffic emissions applied as a surface source on a `streets`
patch carved from the ground. One pollutant per run (CO and NOx are solved
separately). Recentred frame (see `../README.md` §3).

## What it solves
`scalarTransportFoam` for a single scalar `T` (dimensions **kg/m³** → ×1e9 = µg/m³)
using the copied `U`, `phi`, `nut` and a constant diffusivity `DT` (~1 m²/s).
Steady, first-order-upwind, residual-controlled.

## The flow → dispersion handoff
Before solving, the driver copies into this case:
- `constant/polyMesh` (from the converged flow case), and
- `0/U`, `0/phi`, `0/nut` (the frozen latest-time fields).

## Street source (post-mesh, no remesh)
The roads are not in the mesh, so the source patch is carved afterwards:
1. `python3 ../tools/make_street_patches.py --case . --half-width 6.0`
   → selects `Terrain` ground faces under the roads, writes a faceSet,
   `system/createPatchDict`, and `geo/streets_face_segments.csv` (face→segment+area).
2. `createPatch -overwrite` → splits them into a single **`streets`** wall patch
   (added to every field, inheriting `Terrain`'s `zeroGradient`).

## Emission setting (per scenario / hour / pollutant)
`python3 ../tools/set_emissions.py --case . --pollutant NOx --hour 0 --scenario reference`
rewrites the `streets` block in `0/T` to a **non-uniform `fixedGradient`**:
`gradient_f = (E_s · unit_scale)/A_s / DT`, with the CSV rate in **g/h**
(`unit_scale = 1/3.6e6` → kg/s). Scenario scaling (reference/S1/S2/S3) comes from
`../tools/map_emissions.py`.

## Receptors
`system/receptors` defines 4 `surfaceFieldValue` function objects (areaAverage of
`T` over each `constant/triSurface/receptorN.obj`), included by `controlDict`
`functions{}`. They write `postProcessing/receptorN/.../surfaceFieldValue.dat`;
`../tools/receptor_table.py` turns these into a µg/m³ table.

## Key files
```
0/T                              scalar field (4 patches; streets added by createPatch)
constant/transportProperties     DT
constant/triSurface/receptor*.obj  the 4 receptor surfaces (+ receptors.json)
system/{controlDict,fvSchemes,fvSolution,decomposeParDict,receptors}
system/createPatchDict            written by make_street_patches.py
geo/                              recentred roads + transform.json
Allrun                            standalone (serial) flow→dispersion chain
```

## Run
Easiest via the top-level driver (parallel, both pollutants, + table):
```bash
HOUR=0 SCENARIO=reference bash ../run_single_hour.sh
```
or this case's serial `Allrun` after `../initialCase` has converged.

> ASCII `polyMesh` required by the carver — if the copied mesh is binary, run
> `foamFormatConvert` first. Regenerable: `processor*/`, `postProcessing/`,
> time dirs, `constant/polyMesh/sets/`.
