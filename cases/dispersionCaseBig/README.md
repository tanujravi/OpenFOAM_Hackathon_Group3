# dispersionCaseBig - pollutant transport on the BIG (25 km) domain

Big-domain twin of `../dispersionCase`. Transports the passive pollutant `T`
(CO, NOx solved separately) on the **frozen flow from `../flowCaseBig`**, and
samples the four receptors. Recentred frame of the 25 km city4CFD domain
(same X/Y origin as the small domain; Z0 = 74.29 m - see `../flowCaseBig/geo/transform.json`).

This is a **separate** case from the small-domain `../dispersionCase`; the initial
small-domain READMEs are unchanged.

## What it reuses (identical to the small domain)
- `0/T`, `system/{controlDict,fvSchemes,fvSolution,decomposeParDict,receptors}`,
  `constant/transportProperties` - copied from `../dispersionCase`.
- The tools (`set_emissions.py`, `collect_receptors.py`, `receptor_table.py`) and
  the emission CSVs + wind data - the big domain has the **same 196 roads**.

## What is big-domain specific
- `constant/triSurface/receptor{1..4}.obj` + `receptors.json` were split from the
  **big** ROI (`../flowCaseBig/geo/ROI.obj`) via
  `python3 ../tools/split_roi.py --geo ../flowCaseBig/geo --out constant/triSurface`.
  They map to the same four sites (Hospital, Francisco de Holanda, Martins Sarmento,
  Santos Simões), so results are directly comparable to the small domain.
- The carved `streets` mesh + frozen `U/phi/nut` come from `../flowCaseBig`
  (which carves `streets` into its own mesh before the flow solve).
- `0/T` has a **`bottom`** entry (`zeroGradient`): unlike the small domain, the big
  mesh keeps the floor patch (the cylinder reaches past the terrain at a few far
  edges), so every field - including `T` - needs a `bottom` BC. No flux through it.
- **Vegetation canopy - two dispersion-sink implementations** (`constant/fvOptions`, applied in
  the `vegetationZone` cellZone inherited from the flow mesh; a cellZone, **not** a `Vegetation`
  patch). Either can be selected per run:
  1. *Total (perfect) sink* - `scalarFixedValueConstraint` pins `T=0` in the canopy cells
     (complete uptake; a simple, strongly-bounding estimate).
  2. *Finite dry deposition* - `scalarSemiImplicitSource` applies a first-order sink -λT
     (λ≈1e-3 s⁻¹), so canopy cells retain realistic, non-zero concentrations.

## Big-mesh handoff (avoid serial reconstruct)
For the 40 M-cell mesh, reconstructing/​re-decomposing the whole mesh is slow and
OOM-prone. Keep flow + dispersion on the **same decomposition** so the dispersion
reuses the flow's already-decomposed frozen `U/phi/nut` directly, and let the
receptor `surfaceFieldValue` function objects produce the numbers **in parallel**- 
so the volume `T` never has to be reconstructed (only reconstruct it, via
`redistributePar -reconstruct`, if you want the full field for ParaView).

## Run (single hour, big domain)
Prereq: `../flowCaseBig` is meshed (`runallgeo.sh`) and solved for the hour
(`job_flow.sh`). Then, from `cases/`, point the shared driver at the big cases:
```bash
HOUR=8 SCENARIO=reference FLOW=./flowCaseBig DISP=./dispersionCaseBig sbatch run_single_hour.sh
```
Outputs: `results/h<HOUR>_<SCENARIO>/` (`T_CO`, `T_NOx` [kg/m³] and
`receptor_table.csv` [µg/m³]). See `../flowCaseBig/README.md` for the full sequence
and the mesh-resolution table.

> Regenerable: `constant/polyMesh/` (copied from flowCaseBig at run time),
> `processor*/`, `postProcessing/`, time dirs.

## Updates (2026-07)

- **Canopy dispersion sink - two implementations** (`constant/fvOptions`, `vegetationZone`),
  either selectable per run:
  1. **Total sink** - `scalarFixedValueConstraint` with `T=0` (complete uptake; the bounding case).
  2. **Finite dry deposition** - `scalarSemiImplicitSource`, `volumeMode specific`,
     `injectionRateSuSp { T (0 -1e-3); }` (λ≈1e-3 s⁻¹): a first-order sink -λT so vegetated
     cells hold realistic (not annihilated) concentrations. Tune λ ≈ deposition-velocity × leaf-area-density.
  Whichever is not in use is kept commented. Runs were produced with each.
- **Volume receptor sampling.** In addition to the surface `areaAverage` in `system/receptors`, a
  `volFieldValue volAverage` over a box of breathing air above each receptor is available
  (`../tools/make_receptor_zones.py` builds `roiNZone` + the FO). It is the **primary reported
  metric**; the surface areaAverage is a robustness cross-check. Two collectors in `../tools/`:
  `run_receptor_volumes.sh` (post-process finished `T_<poll>` snapshots at time 0, with a
  `readFields` FO) and `collect_receptor_volumes.sh` (gather values written during the solve; wired
  into `../workflow/Snakefile.podrun`).
- **fvOptions type name (ESI v2512):** the constraint form must be `scalarFixedValueConstraint`
  (typed), not the bare `fixedValueConstraint`, or the solver reports "Unknown fvOption type".
