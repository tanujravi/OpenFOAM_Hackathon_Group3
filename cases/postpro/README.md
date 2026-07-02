# Post-processing — ParaView figures (dispersion)

Headless, reproducible figures of the CO/NOx dispersion fields for the report and
the 15-min talk. Built for **ParaView 6.0.1** (`pvbatch`).

## 0. Fix the field header first
`T_CO`/`T_NOx` are renamed copies of the solver field `T`, so their `FoamFile`
`object` entry usually still says `T`. ParaView lists a field by filename but reads
`object` — make them match, in the time dir that holds the fields:
```bash
sed -i 's/object[[:space:]]\+T;/object T_CO;/'  T_CO
sed -i 's/object[[:space:]]\+T;/object T_NOx;/' T_NOx
```

## 1. Run
```bash
# one case (must have constant/polyMesh + a time dir with T_CO/T_NOx):
bash run_pv_figures.sh ../dispersionCase reference
# explicit:
pvbatch pv_dispersion_figures.py --case ../dispersionCase --label reference \
    --fields T_CO T_NOx --triSurface ../dispersionCase/constant/triSurface --out figs/reference
```
Loop scenarios (each a solved case dir):
```bash
for s in reference S1 S2 S3; do bash run_pv_figures.sh cases/$s "$s"; done
```

## 2. Outputs (per field; T kg/m^3 -> x1e9 = ug/m^3)
- `<label>_<field>_volume.png`  — **whole-air volume rendering** of the internal mesh
  (the pollution throughout the city air). Default on; `--orbit N` adds N fly-around frames.
- `<label>_<field>_iso.png`   — 3-D plume isosurfaces, log-coloured, over the domain.
- `<label>_<field>_<receptor>.png` — each ROI surface coloured by its concentration.
- `<label>_<field>_slice_z*.png` — horizontal ground slice (only with `--slice-z`).

The volume view resamples the cell field onto a uniform grid (`--vol-dims 220 220 120`)
and GPU volume-renders it with a transparent(clean)->opaque(dense) opacity ramp
(`--vol-opacity 0.5`). Bump `--vol-dims` for sharper plumes (slower). Disable with
`--no-volume`. Make a rotating fly-around then stitch with ffmpeg:
```bash
pvbatch pv_dispersion_figures.py --case ../dispersionCase --label reference --orbit 72 --out figs/ref
ffmpeg -framerate 24 -i figs/ref/reference_T_CO_volume_%03d.png -pix_fmt yuv420p co_flythrough.mp4
```

## 2b. Real-time, interactive (ParaView GUI)
For live exploration instead of batch images:
1. `paraFoam` (or open `case.foam`); reader: **Reconstructed Case**, tick `internalMesh`
   + `T_CO`/`T_NOx`, **Apply**.
2. **Filters -> Calculator** (Cell/Point Data): `CO_ugm3 = "T_CO"*1e9`, **Apply**.
3. (large mesh, for speed) **Filters -> Resample To Image**, dims ~220x220x120, **Apply**.
4. Set **Representation = Volume**, **Coloring = CO_ugm3**.
5. In the colour-map editor: **Use log scale**, rescale to data range, and drag the
   **opacity** curve so low values are transparent and high values opaque.
6. Rotate/zoom live; **View -> Animation** + Orbit for a recorded fly-through.

## 3. Useful flags
`--n-iso 4` isosurface count · `--slice-z <z>` add a ground slice (recentred frame,
ground≈0 at the ROI) · `--preset "Cool to Warm"` colour map · `--time <t>` pick a
time (default latest) · `--res 1920 1080`.

## Notes
Optional steps (slice, receptor resample, log colour) are wrapped so the script
keeps going and prints `WARN:` if a ParaView-6.0.1 property name differs — paste the
WARN back to pin the exact name. ParaView is for the spatial story; the per-receptor
numbers are in `results/.../receptor_table.csv`.

## Mesh inspection (pv_mesh_inspect.py)

Check a big mesh's refinement without reconstructing it. Reads the **decomposed**
case (`processor*/`) directly; run it in parallel over the decomposition:
```bash
mpirun -np <Nprocs> pvbatch pv_mesh_inspect.py --case ../flowCaseBig --out meshfigs
pvbatch pv_mesh_inspect.py --case ../flowCaseBig --no-slice --out meshfigs   # surfaces only (light)
```
Outputs: `mesh_surfaces.png` (Buildings+streets+Terrain as Surface-With-Edges,
coloured by `cellLevel` -> see street/building resolution) and
`mesh_slice_<axis>.png` (a slice showing the box1/box2/far-field refinement
transitions). Flags: `--reconstructed` (read serial mesh instead), `--patches`,
`--slice-axis x|y|z` + `--slice-origin X Y Z`, `--no-slice`, `--res`.
`cellLevel` comes from snappy; if it's missing the surfaces render solid grey.

## Ground-level concentration field (pv_ground_slice.py)

Top-down map of the CFD concentration field — the "clear visualisation of pollutant
concentration fields" the challenge asks for. Renders a horizontal slice at breathing height
(`--z`), coloured by `T_CO`/`T_NOx`, receptors overlaid → `<label>_<field>_ground.png`.

**The POD snapshots live at TIME 0** (`run_disp_decomp.sh` stashes the converged field into
`processor*/0/T_<poll>`), so use `--time 0` (the default). Each POD disp dir holds ONE pollutant,
and `--case` points at the RUN dir, not the template.

Three ways to run (each disp dir; fix the FoamFile `object` header first — it still says `T`):
```bash
# (A) GL-free, no reconstruct (recommended: immune to headless-OpenGL crashes)
export LC_ALL=C.UTF-8 LANG=C.UTF-8            # pvbatch needs a UTF-8 locale or it aborts
for p in "$D"/processor*; do sed -i 's/object[[:space:]]\+T;/object T_NOx;/' "$p"/0/T_NOx; done
srun pvbatch pv_ground_slice.py --case "$D" --decomposed --extract --time 0 \
    --label reference_h11 --fields T_NOx --z 2.0 --triSurface ../dispersionCaseBig/constant/triSurface --out figs
# (B) ParaView rendering (needs a working GL context): add --force-offscreen-rendering
# (C) reconstruct + serial:  redistributePar -reconstruct -time 0 -parallel  then plain pvbatch
```
Notes: `--extract` resamples the slice to a grid and draws with matplotlib (no ParaView
rendering → no OpenGL); `--decomposed` reads `processor*/` directly; `SkipZeroTime=0` is set so
the reader sees time 0; `scalarTransportFoam` leaves a tiny negative undershoot so the render path
sets a positive range before enabling the log colour scale. Cluster ParaView here is
**5.11.2-foss-2023a** (Python 3.11) — do not mix a Python-3.13 numpy/matplotlib module onto
`PYTHONPATH` (ABI clash); for `--extract`, `PYTHONPATH=` or a matplotlib module built for the
same toolchain.
