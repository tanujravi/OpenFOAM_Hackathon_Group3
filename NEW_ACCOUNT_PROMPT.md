# Bootstrap prompt for a new Cowork session / account

Copy everything in the fenced block below and paste it as your **first message** in the new Cowork
session (after selecting this `referenceCase` folder). It orients the fresh Claude — which has none
of the previous conversation's memory — to the full project state.

---

```
This is the OpenFOAM Hackathon (OFW21) Guimarães air-quality project. I'm continuing it in a new
Cowork session, so you have no memory of the earlier work — everything is persisted in this folder.

Before doing anything, read these in full (they are the authoritative state, in this order):
1. CLAUDE.md               — standing rules + "Resuming" section + environment knobs
2. PROJECT_MEMORY.md       — running log of everything built and every gotcha hit
3. README.md               — the pipeline end to end (see §11 for reporting/receptors)
4. cases/tools/README.md   — the analysis/reporting toolchain
5. cases/workflow/README_podrun.md — the Snakemake POD workflow (receptor tables + report)
Then give me a 5-bullet summary of where the project stands and what's left, and wait.

Context you can rely on: the pipeline is COMPLETE and has run end-to-end on the Deucalion HPC
cluster. Done: mesh (snappyHexMesh, big 25 km city4CFD domain with a porous + finite-deposition
canopy), per-hour k-ε ABL flow (frozen), scalarTransportFoam dispersion for CO and NOx, all four
scenarios (reference/S1/S2/S3), a 24 h→10 representative-hour POD sweep (Snakemake, cluster-generic
executor), receptor concentrations by TWO metrics (surface areaAverage and — primary — a volume
volAverage in a breathing-air box above each receptor), spatial maps, a ParaView ground-level
concentration field, and an auto-generated technical report (make_report → make_maps →
make_techreport). Key result: S1 ≈ −20%, S2 ≈ −40% uniformly (linear check); the Metro Bus (S3) is
spatially selective — ≈ −40% at the Public Hospital, ≈ −5% at Santos Simões.

How the work is split: the CFD runs on the HPC cluster over SSH/tmux (I run them; the repo is
git-synced there). You edit this local repo — no MCP connectors are needed. Compiled results live
in the results_pod folder (receptors_long*.csv + the report).

Environment knobs that may differ for me/this allocation (check, don't assume):
- cases/workflow/run_podrun.sh: ACCOUNT (SLURM allocation), ARMPART (ARM partition)
- cases/workflow/config_pod.yaml: python_bin (absolute aarch64 numpy python), nprocs
- Cluster modules: OpenFOAM/v2512-foss-2025a; an aarch64 snakemake +
  snakemake-executor-plugin-cluster-generic; ParaView 5.11.2-foss-2023a; reportlab.

Deliverables are a concise technical report (PDF) + the OpenFOAM cases/tools; assessment weights:
workflow 30%, scenario implementation 25%, receptor assessment 20%, presentation 15%, post-pro 10%.

Please keep updating PROJECT_MEMORY.md and the READMEs as you work, and don't re-run finished cluster
jobs unless I ask. Start by reading the files above.
```

---

## Checklist before you switch accounts

1. **Files travel with the folder** — all context is in the repo (`CLAUDE.md`, `PROJECT_MEMORY.md`,
   the READMEs, `cases/tools/`, `cases/workflow/`, `cases/postpro/`). Nothing lives only in the chat.
2. **Same machine:** in the new account's Cowork, just add/select the `referenceCase` folder (and
   `results_pod/` if you want the compiled results visible). Done.
3. **Different machine:** `git clone` (or copy) the repo, but do NOT copy the regenerable heavy dirs:
   `runs_pod*/`, `processor*/`, `postProcessing/`, `snapshots/`, `results*/`, `.snakemake/`,
   `constant/polyMesh/`, `*.npz`/`*.pkl`. They rebuild on the cluster.
4. **The cluster stays the same** — the Claude account only changes who edits the local repo; your
   Deucalion runs, tmux sessions, and git remote are unaffected.
5. Paste the block above as the first message; the new session self-orients from the repo files.
