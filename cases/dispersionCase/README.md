# dispersionCase - pollutant transport (`scalarTransportFoam`)

Transports a passive pollutant scalar `T` on the **frozen** wind field from
`../flowCase`. The `streets` source patch is already carved into that flow mesh
(before the flow solve), so this case **reuses** the split mesh + fields and never
carves. One pollutant per run (CO and NOx solved separately). Recentred frame (see
`../../README.md` §3).

## What it solves
`scalarTransportFoam` for a single scalar `T` (dimensions **kg/m³** → ×1e9 = µg/m³)
using the copied `U`, `phi`, `nut` and a constant diffusivity `DT` (~1 m²/s).
Steady, first-order-upwind, residual-controlled. `controlDict` loads
`libs (atmosphericModels)` because the copied `nut` carries `atmNutkWallFunction`.

## Flow → dispersion handoff (no carve here)
`../run_single_hour.sh` copies in from `../flowCase`:
- `constant/polyMesh` - the **already-split** `Terrain` + `streets` mesh,
- `0/U`, `0/phi`, `0/nut` - frozen fields, written on that split mesh (sizes match),
- `geo/streets_face_segments.csv` - the face → segment + area map from the flow carve.

> The `streets` patch is carved in `../flowCase` **before** the flow solve (see
> `../../README.md` §6.1). Carving here instead would shrink `Terrain` after the
> fields were written and crash on a boundary-list size mismatch.

## Emission setting (per scenario / hour / pollutant)
`python3 ../tools/set_emissions.py --case . --pollutant NOx --hour 0 --scenario reference`
writes the `streets` block in `0/T` as a **non-uniform `fixedGradient`** (inserting
it if absent): `gradient_f = (E_s · unit_scale)/A_s / DT`, CSV rate in **g/h**
(`unit_scale = 1/3.6e6` → kg/s). Scenario scaling (reference/S1/S2/S3) is applied via
`../tools/map_emissions.py` (imported by `set_emissions`).

## Receptors
`system/receptors` defines 4 `surfaceFieldValue` function objects (areaAverage of
`T` over each `constant/triSurface/receptorN.obj`), included by `controlDict`
`functions{}`. They write `postProcessing/receptorN/.../surfaceFieldValue.dat`;
`../tools/receptor_table.py` turns these into a µg/m³ table.

## Key files
```
0/T                                scalar field; 'streets' added/updated by set_emissions
constant/transportProperties       DT
constant/triSurface/receptor*.obj  the 4 receptor surfaces (+ receptors.json)
system/{controlDict,fvSchemes,fvSolution,decomposeParDict,receptors}
geo/streets_face_segments.csv      copied from flowCase (face -> segment + area)
```

## Run
Via the top-level dispersion driver (parallel, both pollutants, + table), after the
flow has been carved+solved in `../flowCase` (`job_flow.sh`):
```bash
HOUR=0 SCENARIO=reference bash ../run_single_hour.sh
```

> Regenerable: `processor*/`, `postProcessing/`, time dirs, `constant/polyMesh/`.
