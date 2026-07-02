# initialCase - wind precursor (`simpleFoam`)

Steady RANS (k-ω SST) that produces the **hourly wind field** the dispersion stage
advects on. This case also holds the mesh (built here by `runallgeo.sh`) that the
dispersion case reuses. Coordinates are the **recentred frame** (see
`../README.md` §3 and `geo/transform.json`).

## What it solves
`simpleFoam` (incompressible, steady, SIMPLEC) for `U, p, k, omega, nut` on the
`snappyHexMesh` mesh of terrain + ROI buildings.

## Mesh
Built in place by `../runallgeo.sh` (SLURM, 96 ranks):
`surfaceFeatureExtract → blockMesh (m4 cylinder) → snappyHexMesh -parallel →
reconstructParMesh → checkMesh`. The live mesh exposes **4 patches**:
`inletOutlet` (all-round cylinder side), `top` (symmetry), `Terrain`, `Buildings`
(walls). The blockMesh `bottom` floor is carved away below the terrain and does
**not** appear in the fields.

## Boundary conditions (`0/`)
Single cylindrical boundary handling any hourly wind direction via the freestream
family:

| field | `inletOutlet` | `Terrain`,`Buildings` | `top` |
|---|---|---|---|
| `U` | `freestreamVelocity` (hourly `(u,v,0)`) | `noSlip` | `symmetry` |
| `p` | `freestream` | `zeroGradient` | `symmetry` |
| `k` | `inletOutlet` | `kqRWallFunction` | `symmetry` |
| `omega` | `inletOutlet` | `omegaWallFunction` | `symmetry` |
| `nut` | `calculated` | `nutkWallFunction` | `symmetry` |

The hourly wind is the only per-run change - set it with
`python3 ../tools/set_wind.py --case . --hour H` (writes `0/U`).

## Key files
```
0/{U,p,k,omega,nut}        boundary + initial fields (4 patches)
constant/{transportProperties,turbulenceProperties}   nu, kOmegaSST
system/{controlDict,fvSchemes,fvSolution,decomposeParDict}
system/{blockMeshDict.m4,snappyHexMeshDict,surfaceFeatureExtractDict}
geo/                       recentred OBJs + transform.json (mesh inputs)
```
`fvSolution` uses `nNonOrthogonalCorrectors 2` (mesh max non-ortho ~72°).

## Run
```bash
# mesh once:
sbatch ../runallgeo.sh
# then flow (or let ../run_single_hour.sh do it):
python3 ../tools/set_wind.py --case . --hour 0
decomposePar -force && mpirun -np 96 simpleFoam -parallel && reconstructPar -latestTime
```
Output: a converged time directory with frozen `U`, `phi`, `nut` → consumed by
`../dispersionCase`.

> Regenerable: `processor*/`, time dirs, `constant/polyMesh/` (re-meshable).
