# flowCase — wind precursor (`simpleFoam`, ABL inlet, k-ε)

Steady RANS that produces the **hourly wind field** the dispersion stage advects on.
This case also holds the mesh (built here by `runallgeo.sh`) that the dispersion case
reuses. Coordinates are the **recentred frame** (see `../../README.md` §3 and
`geo/transform.json`).

## What it solves
`simpleFoam` (incompressible, steady, plain SIMPLE `consistent no`) for
`U, p, k, epsilon, nut` with the **k-ε** model (neutral-ABL coefficients,
Hargreaves & Wright). A `potentialFoam` step initialises `U`/`p`.

## Mesh
Built by `runallgeo.sh` (SLURM): `surfaceFeatureExtract → blockMesh (m4
cylinder) → snappyHexMesh -parallel → reconstructParMesh → checkMesh`. The live mesh
exposes **4 patches**: `inletOutlet` (all-round cylinder side), `top` (symmetry),
`Terrain`, `Buildings` (walls). The blockMesh `bottom` floor is carved away below the
terrain and does **not** appear in the fields.

## Boundary conditions (`0/`)
Single cylindrical boundary, handled with OpenFOAM's flux-aware **atmospheric** BCs
(the `cases/round` template): the ABL log-law profile is imposed where flow enters and
zero-gradient where it leaves, so one fixed mesh handles every hourly wind direction.
Needs `libs (atmosphericModels);` in `controlDict`.

| field | `inletOutlet` | `Terrain`, `Buildings` | `top` |
|---|---|---|---|
| `U` | `atmBoundaryLayerInletVelocity` | `noSlip` | `symmetry` |
| `p` | `freestreamPressure` | `zeroGradient` | `symmetry` |
| `k` | `atmBoundaryLayerInletK` | `kqRWallFunction` | `symmetry` |
| `epsilon` | `atmBoundaryLayerInletEpsilon` | `atmEpsilonWallFunction` (Terrain, z0) / `epsilonWallFunction` (Buildings) | `symmetry` |
| `nut` | `calculated` | `atmNutkWallFunction` (Terrain, z0=0.25 m) / `nutkWallFunction` (Buildings) | `symmetry` |

The profile is set in `0/include/ABLConditions` (`Uref`, `Zref`, `angle`, `z0`). The
hourly wind is the only per-run change:
`python3 ../tools/set_wind.py --case . --hour H` writes `Uref=|(u,v)|`,
`angle=atan2(v,u)`.

## Solver robustness — two-stage schemes
Starting fully 2nd-order on this stiff mesh diverges (k/ε overshoot → `nut` blow-up →
GAMG floating-point exception ~iter 10). So:
- `system/fvSchemes_1storder` — upwind `k`/`epsilon` (bounded), the **warm-up**.
- `system/fvSchemes_2ndorder` — `limitedLinear` (accurate), the **restart**.
- `system/fvSchemes` — currently = the 1st-order set (active default).

`job_flow.sh` runs the full recipe: **carve the `streets` patch (one-time, before
solving)** → `decomposePar → potentialFoam → simpleFoam` (1st-order) → swap to
2nd-order, bump `endTime`, restart from `latestTime` → `reconstructPar`.

## Street patch carved here (before the solve)
`job_flow.sh` first carves `streets` out of `Terrain` (idempotent — skipped if the
patch already exists): `foamFormatConvert` to ASCII if needed →
`make_street_patches.py` → `createPatch -overwrite` → `add_streets_bc.py` (clones the
`Terrain` boundary entry into `streets` for the uniform `0/{U,p,k,epsilon,nut}`).
Doing this **before** the solve means the frozen fields are written on the final
`Terrain`+`streets` mesh, so `../dispersionCase` can reuse them with matching face
counts. (Carving after the solve would shrink `Terrain` and desync the field sizes.)
This produces `geo/streets_face_segments.csv`, which the dispersion stage reuses.

## Key files
```
0/{U,p,k,epsilon,nut}      ABL boundary + initial fields (4 patches)
0/include/ABLConditions    Uref / Zref / angle / z0  (per-hour knobs)
constant/{transportProperties,turbulenceProperties}   nu, kEpsilon (ABL coeffs)
system/{controlDict,fvSolution,decomposeParDict}
system/{fvSchemes,fvSchemes_1storder,fvSchemes_2ndorder}
system/{blockMeshDict.m4,snappyHexMeshDict,surfaceFeatureExtractDict}
geo/                       recentred OBJs + transform.json (mesh inputs)
job_flow.sh                two-stage flow job (SLURM, 128 ranks)
```

## Run
```bash
sbatch runallgeo.sh      # mesh once
sbatch job_flow.sh             # potentialFoam + simpleFoam (1st->2nd order)
```
Output: a converged time directory with frozen `U`, `phi`, `nut` → consumed by
`../dispersionCase`.

> The previous **freestream + k-ω SST** setup is preserved in `../flowCaseOldBC` as a
> fallback (it stays bounded but its pressure residual plateaus ~0.15).
>
> The carve needs an **ASCII** `polyMesh`; `job_flow.sh` runs `foamFormatConvert`
> automatically if the mesh is binary.
> Regenerable: `processor*/`, time dirs, `constant/polyMesh/` (re-meshable).
