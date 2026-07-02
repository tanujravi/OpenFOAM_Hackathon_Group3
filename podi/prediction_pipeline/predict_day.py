#!/usr/bin/env python3
"""
predict_day.py
==============
Predict the pollutant field for ALL 24 hours of one scenario using a pickled
PODI model, and write the result as a numpyToFoam-ready per-processor stack:

    <out-dir>/<field>/<field>_proc_<p>.npy      shape (nCells_p, 24), float32, F-order

Column h (0..23) is simulated hour h -> wind column h of config.yaml
(hour 0 == 07:00-08:00; clock = (7 + h) % 24).  The scenario's emission
controls (G,L) are constant across the day.

The reconstruction is exactly predict_from_model() in podi_validate.py:
    coeffs = [1, standardise(shape_features(u,v,G,L))] @ W
    field  = predict_scale(u,v,G,L) * (mean + modes @ coeffs)
done per hour, sliced per processor so no (nCells x 24) full array is held.

Usage:
    python3 predict_day.py --model models/model_CO.pkl --config config.yaml \
        --G 1.0 --L 1.0 --out-dir /path/to/case/data --field T
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import yaml

# reuse the exact fitted feature/scale maps from the trainer
PODI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PODI_DIR))
from podi_validate import shape_features, predict_scale  # noqa: E402


def build_query(cfg, G, L, pcols):
    """One row per hour: [u,v,G,L] in the model's parameter order."""
    u = np.asarray(cfg["wind"]["u"], dtype=np.float64)
    v = np.asarray(cfg["wind"]["v"], dtype=np.float64)
    if len(u) != 24 or len(v) != 24:
        sys.exit(f"expected 24 wind columns, got u={len(u)} v={len(v)}")
    cols = {"u": u, "v": v, "G": np.full(24, float(G)), "L": np.full(24, float(L))}
    missing = [c for c in pcols if c not in cols]
    if missing:
        sys.exit(f"model needs parameters {pcols}; cannot build {missing}")
    return np.column_stack([cols[c] for c in pcols])            # (24, len(pcols))


def main():
    ap = argparse.ArgumentParser(description="Predict a full 24-hour field stack for one scenario.")
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--G", type=float, required=True)
    ap.add_argument("--L", type=float, required=True)
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="Field parent dir (numpyToFoam dataDir); files go under <out-dir>/<field>/.")
    ap.add_argument("--field", default="T", help="OpenFOAM field name to write (default T).")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    with open(args.model, "rb") as f:
        M = pickle.load(f)
    pcols = M["param_names"]

    Xq = build_query(cfg, args.G, args.L, pcols)                # (24, p)
    Fq = shape_features(Xq, pcols)
    Xb = np.hstack([np.ones((Xq.shape[0], 1)), (Fq - M["mu"]) / M["sd"]])
    coeffs = Xb @ M["W"]                                         # (24, r)
    scale = predict_scale(Xq, M["beta"], pcols)                 # (24,)

    mean = M["mean"]                                            # (nCells,) f32
    modes = M["modes"]                                          # (nCells, r) f32
    counts, procs = M["counts"], M["procs"]

    fdir = args.out_dir / args.field
    fdir.mkdir(parents=True, exist_ok=True)
    coeffsT = coeffs.T.astype(np.float32)                       # (r, 24)
    scale32 = scale.astype(np.float32)                          # (24,)

    start = 0
    for p, cnt in zip(procs, counts):
        m_p = modes[start:start + cnt]                         # (cnt, r)
        mean_p = mean[start:start + cnt]                       # (cnt,)
        # shape per hour, then scale: (cnt,24) = (mean + modes@coeffs) * scale
        block = (mean_p[:, None] + m_p @ coeffsT) * scale32[None, :]
        np.save(fdir / f"{args.field}_proc_{p}.npy",
                np.asfortranarray(block.astype(np.float32)))
        start += cnt

    print(f"[predict_day] {args.model.name}  G={args.G} L={args.L}  "
          f"-> {fdir}  ({len(procs)} procs x 24 h, {start} cells)")
    # magnitude sanity: mean predicted |field| per hour (volume-agnostic)
    print("[predict_day] per-hour scale (||field||_vol): " +
          " ".join(f"{s:.3e}" for s in scale))


if __name__ == "__main__":
    main()
