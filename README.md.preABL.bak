<<<<<<< HEAD
# Guimarães Air-Quality / Mobility-Scenario CFD Workflow

OpenFOAM workflow for the OFW21 hackathon: quantify how four sustainable-mobility
scenarios change **CO and NOx** concentrations at four sensitive receptors
(Martins Sarmento HS, Francisco de Holanda HS, Santos Simões HS, Public Hospital)
relative to a reference case, on the real 3-D terrain of Guimarães.

This README documents the pipeline end to end: the recentred geometry frame, the
meshing strategy, the two-solver (flow → dispersion) split, the post-mesh street
patch creation, the emission mapping, receptor sampling, and the orchestration.


**Ricardo Andrade note:** The canopy/merged.obj file was not uploaded because it is very large (1.5 GB)
---

## 1. Big picture

```
                provided data (read-only)
   terrain + buildings + canopy + roads + emissions + wind
                          │
            tools/preprocess_geometry.py   (recenter to origin, merge buildings)
                          │
                       geo/  (recentred OBJs + transform.json)
                          │
        ┌─────────────────┴───────────────────┐
        │  STAGE 0  MESH  (runallgeo.sh)       │  snappyHexMesh on the terrain
        │  blockMesh → snappy → checkMesh      │  + ROI buildings (one mesh, reused)
        └─────────────────┬───────────────────┘
                          │  constant/polyMesh
        ┌─────────────────┴───────────────────┐
        │  STAGE 1  WIND  (initialCase)        │  simpleFoam, k-ω SST, steady RANS
        │  per-hour (u,v) freestream inlet     │  → frozen U, phi, nut
        └─────────────────┬───────────────────┘
                          │  frozen flow fields
        ┌─────────────────┴───────────────────┐
        │  STAGE 2  DISPERSION (dispersionCase)│  scalarTransportFoam on frozen flow
        │  carve streets → set emission → solve│  one passive scalar per pollutant
        └─────────────────┬───────────────────┘
                          │  T (kg/m³)
        ┌─────────────────┴───────────────────┐
        │  STAGE 3  RECEPTORS + TABLE          │  areaAverage(T) at the 4 ROI sites
        └──────────────────────────────────────┘  results/.../receptor_table.csv (µg/m³)
```

Driver `run_single_hour.sh` chains Stages 1–3 for one hour / one scenario.
The same mesh, BCs, solver settings and temporal strategy are reused across all
four scenarios — **only the emission scaling changes** — so comparisons are fair.

---

## 2. Provided data (read-only inputs)

| Path | Contents |
|---|---|
| `terrain_and_buildings/Mesh_Terrain.obj` | 6.3 × 6.3 km terrain, real relief (Z 143–613 m) |
| `terrain_and_buildings/Mesh_Buildings_0..5.obj` | ROI buildings |
| `terrain_and_buildings/Mesh_Buildings_6.obj` | far-field buildings (excluded from the small-domain build) |
| `canopy/merged.obj` | vegetation surface (1.5 GB; porous-zone candidate, **not** a wall) |
| `bigger_terrain_results/city4CFD/` | alternative 25 × 25 km domain (for the domain-influence study) |
| `traffic/emission_factor_per_segment_{CO,NOx}.csv` | 196 segments × 24 hourly columns, **units g/h** |
| `traffic/snapped_road_segments.csv` | 196 road LINESTRING Z, snapped to terrain |
| `wind_data/wind_velocity_time.csv` | hourly (u, v) reference wind, 24 bins 07:00→07:00 |
| `road_ids_reduction.txt` | Scenario-3 road IDs: a 50%-list (19) and a 30%-list (28) |
| `ROI/ROI.obj` | the four receptor surfaces (4 connected components) |

Coordinates are a projected CRS in metres; all layers share the frame and overlay
directly. Row order in the emission CSVs == segment order == road ID == 0-based row
index (validated: IDs ≤ 192 < 196, the two S3 tiers don't overlap).

---

## 3. Recentred coordinate frame
**Ricardo Andrade note:** Check if this translation makes sense

The provided geometry sits at large UTM-like offsets (X ≈ −13 000, Y ≈ 197 000).
The mesh templates assume a city centred on the origin with the ground near Z = 0,
so a single **pure translation** is applied to every geometry layer:

```
X' = X − X0   (X0 = terrain X bbox-centre = −13152.617)
Y' = Y − Y0   (Y0 = terrain Y bbox-centre =  197434.738)
Z' = Z − Z0   (Z0 = terrain min elevation =     142.676)
```

Result: terrain spans ±3150 m in X/Y and Z 0–470 m; the ROI sits at the origin.
The transform is recorded in `geo/transform.json` (with its inverse) so receptor
results and source locations map straight back to real UTM coordinates.

Translation-invariant and therefore **not** transformed: the wind `(u, v)` vectors
and the per-segment emission factors. No rotation is applied (the inlet handles
arbitrary wind direction — see §5).

`tools/preprocess_geometry.py` performs the recenter, merges `Mesh_Buildings_0..5`
into one `Mesh_Buildings.obj` (far-field `_6` excluded), recentres `ROI.obj` and the
road coordinates, and writes everything to `geo/`.

---

## 4. Stage 0 — Meshing strategy (`runallgeo.sh`)

A single `snappyHexMesh` mesh is built **once** and reused for every hour and
scenario (fairness + cost). Driven on the cluster by `runallgeo.sh` (SLURM, 96
ranks): `surfaceFeatureExtract → blockMesh → decomposePar → snappyHexMesh -parallel
→ reconstructParMesh → checkMesh`.

**Background domain — `system/blockMeshDict.m4`.** A COST732-style **cylinder**
generated by `m4`: outer vertices on a circle (radius set to **3000 m**, terrain-
limited — the source-city's `15·H + 2·s` rule would overrun our fixed 6.3 km
footprint), arc edges, and one all-round side patch named `inletOutlet`. Floor at
Z = −10 (below the lowest terrain), top at ~1870 m (clears the 470 m of terrain
relief plus a deep ABL). Patches: `inletOutlet` (cylinder side), `bottom` (flat
floor), `top` (`symmetry`).

> The `m4` `calc` macro defines `pi` inline (`4*atan2(1,1)`) so it needs **no Perl
> `Math::Trig`** module — this was a cluster failure (`Can't locate Math/Trig.pm`).

**Surfaces — `system/snappyHexMeshDict`.** `Mesh_Buildings` and `Mesh_Terrain` are
snapped as `wall` patches (`Buildings`, `Terrain`); refinement boxes are sized to
the ~3.2 × 2.3 km ROI; `locationInMesh (0 0 800)` sits in the air above all terrain.
Terrain at refinement level 4, buildings at 5 (cell-count balance). Canopy and
"water" are **not** meshed (no water provided; canopy is a porous-zone step).

**Key mesh facts after the first run** (~1.71 M cells, mostly hexahedra):
- The `bottom` patch is **fully carved away** (its faces lie below the terrain), so
  the live mesh exposes only **4 patches**: `inletOutlet`, `top`, `Buildings`,
  `Terrain`. The `0/` fields therefore do **not** reference `bottom`.
- checkMesh passes apart from a moderate skewness flag (max ~5) and ~70° max
  non-orthogonality — normal for snapped urban terrain. The flow `fvSolution` uses
  `nNonOrthogonalCorrectors 2` to handle it.

---

## 5. Stage 1 — Wind precursor (`initialCase`, `simpleFoam`)

Steady RANS (`simpleFoam`, k-ω SST) produces the hourly wind field that the
dispersion stage advects on.


**Ricardo Andrade Note:** We should check if this velocity boundary condition makes sense in this case.

**All-round freestream inlet (varying wind direction).** The domain boundary is a
single cylindrical `inletOutlet` patch, and the reference wind blows from a
different direction each hour. So instead of a fixed inlet face we use the
**freestream** family, which decides inflow vs. outflow per face from the flux:

| field | `inletOutlet` patch | walls (`Terrain`,`Buildings`) | `top` |
|---|---|---|---|
| `U` | `freestreamVelocity` (freestreamValue = hourly `(u,v,0)`) | `noSlip` | `symmetry` |
| `p` | `freestream` | `zeroGradient` | `symmetry` |
| `k` | `inletOutlet` | `kqRWallFunction` | `symmetry` |
| `omega` | `inletOutlet` | `omegaWallFunction` | `symmetry` |
| `nut` | `calculated` | `nutkWallFunction` (smooth) | `symmetry` |

One fixed mesh then handles every hourly wind direction with no remeshing. (Note:
for this dataset `u>0, v<0` all day — wind stays NW, only the speed varies ~0.45–2.5
m/s — but the freestream setup stays valid for any direction / the larger domain.)

`tools/set_wind.py --hour H` writes the hour's `(u,v,0)` into the `freestreamValue`
marker and `internalField` of `0/U` (the single per-hour knob).

---

## 6. Stage 2 — Dispersion (`dispersionCase`, `scalarTransportFoam`)

The converged wind (`U`, `phi`, `nut`) is **frozen** and copied in; a passive scalar
`T` is then transported by `scalarTransportFoam` with constant turbulent
diffusivity `DT` (≈1 m²/s, a crude Sc_t stand-in). `T` carries dimensions **kg/m³**,
so the solved field is an absolute concentration (×1e9 → µg/m³).

**Two pollutants = two runs.** `scalarTransportFoam` solves one scalar per run, so
CO and NOx are solved **separately** on the same frozen wind (kept distinct, never
summed). The driver loops `CO` then `NOx`, saving `T_CO` and `T_NOx`.
*(A single-run alternative — two `scalarTransport` function objects, each with an
`fvOptions` `scalarSemiImplicitSource` — is noted in §10 as the production option.)*

**Ricardo Andrade Note:** The chosen approach here is a single patch "streets" whith a non-uniform fixed gradient
with the emission values for each street inside the patch (face). Right now, the pollutants are separate 
This still needs to be tested in the cluster.


## 6.1 Street patch creation (post-mesh, no remesh)

The roads are **not** in the mesh (only terrain + buildings are). To apply the
emission as a surface source without remeshing, the road footprint is carved out of
the `Terrain` ground **after** meshing:

1. `tools/make_street_patches.py` reads `constant/polyMesh`, finds the `Terrain`
   boundary faces whose centres lie within `--half-width` (default 6 m) of any road
   polyline, tags each with its nearest segment, and writes:
   - `constant/polyMesh/sets/streets` (a faceSet),
   - `system/createPatchDict` (one `streets` wall patch from that set),
   - `geo/streets_face_segments.csv` (face → segment id + face area, in patch order).
2. `createPatch -overwrite` splits those faces off `Terrain` into a new **`streets`**
   patch and adds the patch (inheriting `Terrain`'s `zeroGradient`) to every field.

> Check the carver line `segments with faces: N/196`. If N < 196, raise
> `--half-width` or refine the mesh near roads.

### 6.2 Emission mapping (the scenario logic)
**Ricardo Andrade Note**: Should ignore for now the different scenario part and just focus on reference. 

`tools/map_emissions.py` applies the mobility-scenario scaling to the per-segment
hourly factors (this is the "correct scenario implementation" deliverable):

| Scenario | Definition | Scaling |
|---|---|---|
| reference | provided data | ×1.0 |
| S1 | 20% of gas vehicles → EV | ×0.8 all segments |
| S2 | 40% → EV | ×0.6 all segments |
| S3 | Metro Bus (N101) | ×0.5 on the 50%-list, ×0.7 on the 30%-list, ×1.0 elsewhere |

`tools/set_emissions.py` then converts the scaled per-segment rate to a wall flux and
writes it as a **non-uniform `fixedGradient`** on the `streets` patch in `0/T`:

```
each face f of segment s:  gradient_f = flux_s / DT,
                           flux_s     = (E_s · unit_scale) / A_s
```
with `E_s` the scaled CSV value, `A_s` the segment's total carved street-face area,
and `unit_scale = 1/(1000·3600)` converting **g/h → kg/s**. The wall balance
`DT · gradient · area = segment emission rate [kg/s]` then holds, and `T` is an
absolute concentration. (Sanity check: a ~30 g/h segment over ~1000 m² gives
~8e-9 kg/(m²·s), squarely in the documented busy-street range.)

---

## 7. Stage 3 — Receptors & results table

**Ricardo Andrade Note:** This is just a Function object on the patches. The ROI should probably be something like for each street an area average of the polution of the air above it

The four receptors are the four connected components of `ROI.obj`, split by
`tools/split_roi.py` into `dispersionCase/constant/triSurface/receptor{1..4}.obj`
(+ `receptors.json` with each centroid in recentred and UTM coords).

`system/receptors` defines four `surfaceFieldValue` function objects, each an
**`areaAverage` of `T`** over one receptor surface; they run inside
`scalarTransportFoam` (via `controlDict` `functions{}`) and write
`postProcessing/receptorN/.../surfaceFieldValue.dat`.

`tools/receptor_table.py` reads those, converts to **µg/m³**, and writes
`results/<run>/receptor_table.csv`. With `--reference <dir>` it adds absolute and
**% change vs the reference scenario** per receptor/pollutant.

> Receptor `site_name` is currently `TBD` — match the UTM centroids in
> `receptors.json` to the four named sites on a map (a one-time manual step).

---

## 8. Orchestration — `run_single_hour.sh` 
**Ricardo Andrade Note: IGNORE THIS FOR NOW**

One command for a full single-hour, single-scenario run on an already-meshed case:

```bash
# defaults: HOUR=0 SCENARIO=reference POLLUTANTS="CO NOx" HALFWIDTH=6.0 NPROCS=96
sbatch run_single_hour.sh
HOUR=8 SCENARIO=S2 bash run_single_hour.sh        # any hour / scenario
SKIP_FLOW=1 SCENARIO=S1 bash run_single_hour.sh   # reuse an existing wind solve
```

Stages: set wind → `simpleFoam` (parallel) → copy frozen fields + carve `streets` →
per pollutant `set_emissions` + `scalarTransportFoam` (parallel) → receptor table.
Outputs land in `results/h<HOUR>_<SCENARIO>/` (`T_CO`, `T_NOx` in kg/m³;
`receptor_table.csv` in µg/m³; per-pollutant `pp_*` postProcessing).

---

## 9. Directory layout

```
referenceCase/
  README.md                 this file
  CLAUDE.md, PROJECT_HANDOFF.md   standing rules + full handoff
  <provided data>           terrain_and_buildings/ canopy/ traffic/ wind_data/ ROI/ ...
  runallgeo.sh              STAGE 0 meshing (SLURM)
  run_single_hour.sh        STAGE 1–3 driver (SLURM)
  initialCase/              FLOW case: 0/ system/ constant/ geo/  (mesh built here)
  dispersionCase/           DISPERSION case: 0/T system/ constant/triSurface/ geo/
  tools/
    preprocess_geometry.py  recenter + merge geometry -> geo/
    set_wind.py             hourly (u,v) -> 0/U
    make_street_patches.py  carve the streets patch (post-mesh)
    map_emissions.py        per-segment scenario scaling
    set_emissions.py        per-segment non-uniform fixedGradient on streets
    split_roi.py            ROI -> 4 receptor surfaces
    receptor_table.py       receptor µg/m³ table (+ % vs reference)
  results/                  per-run receptor tables + fields (regenerable)
  backups/                  timestamped copies of edited dicts
```

Regenerable (safe to delete): `processor*/`, `postProcessing/`, `results/`,
`constant/polyMesh/sets/`, time directories.

---

## 10. Environment, gotchas & next steps

**Environment.** OpenFOAM ESI **v2512** (`module load OpenFOAM/v2512-foss-2025a`);
Python 3 with `numpy` (tools are otherwise stdlib-only). Mesh + solves run in
parallel on 96 ranks via SLURM.

**Gotchas already handled / to watch:**
- `blockMeshDict.m4` needs no Perl `Math::Trig` (inline `pi`).
- The `bottom` blockMesh patch disappears after snapping → `0/` fields list only the
  4 real patches.
- `make_street_patches.py` needs an **ASCII** `polyMesh`. If `reconstructParMesh`
  wrote binary, convert once with `foamFormatConvert` (controlDict `writeFormat
  ascii`) before carving.
- `createPatch`/field handling for `streets` on the real mesh is the one step not yet
  validated on the cluster; if `scalarTransportFoam` complains about `streets` on
  `U`/`phi`/`nut`, a one-line `zeroGradient` entry fixes it.

**Open items / next steps:**
- Confirm the four receptor `site_name`s against a map.
- Decide DT (constant vs nut/Sc_t), and tune mesh refinement vs cell count.
- Two-pollutant single-run path 
- Canopy as a porous/momentum-sink zone.
- Domain-influence comparison on the 25 km `city4CFD` domain.
- Daily aggregation (mean + peak) across the 24 hourly states, per receptor.
```
=======
# OpenFOAM_Hackathon_Group3
>>>>>>> origin/main
