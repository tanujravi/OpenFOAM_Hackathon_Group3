#!/usr/bin/env python3
"""
podi_big.py
===========
Memory-efficient LINEAR PODI for very large meshes (tens of millions of cells),
using the METHOD OF SNAPSHOTS so the (nCells x nModes) spatial basis is never
materialised.

Why this scales
---------------
With nCells >> nCases, decomposing the tall (nCells x nCases) matrix is wasteful.
Instead we build the small weighted Gram matrix

        S_ij = sum_c  vol_c * x_i[c] * x_j[c]          (nCases x nCases)

eigen-decompose it, and get the modal coefficients from that.  A POD
reconstruction lives in the span of the snapshots, so any predicted field is

        field = X @ alpha                              (alpha is length nCases)

a weighted combination of the raw snapshots.  No nCells x nModes basis is stored.

Two execution modes
-------------------
  in-memory (default): hold the snapshots once -> peak ~ nCells*nCases*dtype.
  --streaming         : accumulate the Gram and reconstruct one processor at a
                        time -> peak ~ cells_per_proc * nCases (mesh-size free).

Run once per pollutant, e.g.:
    python3 podi_big.py --cases-dir staging/CO --parameters parameters.csv --field T_CO
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np


# --------------------------------------------------------------------------- #
# Per-processor file access
# --------------------------------------------------------------------------- #

def proc_ids(cases_dir: Path, case: str, field: str) -> list[int]:
    d = cases_dir / case / "exported_data" / field
    ids = []
    for p in d.glob(f"{field}_proc_*.npy"):
        m = re.search(r"_proc_(\d+)\.npy$", p.name)
        if m:
            ids.append(int(m.group(1)))
    if not ids:
        raise FileNotFoundError(f"No {field}_proc_*.npy under {d}")
    return sorted(ids)


def proc_path(cases_dir: Path, case: str, field: str, p: int) -> Path:
    return cases_dir / case / "exported_data" / field / f"{field}_proc_{p}.npy"


def vol_path(cases_dir: Path, case: str, p: int) -> Path:
    return cases_dir / case / "exported_data" / "cellVolumes" / f"cellVolumes_proc_{p}.npy"


def proc_counts(cases_dir: Path, case: str, field: str, procs: list[int]) -> list[int]:
    return [np.load(proc_path(cases_dir, case, field, p)).shape[0] for p in procs]


# --------------------------------------------------------------------------- #
# Parameters (case,u,v,G,L[,train])  -- same format as podi_linear.py
# --------------------------------------------------------------------------- #

def load_parameters(csv_path: Path):
    raw = np.genfromtxt(csv_path, delimiter=",", names=True, dtype=None, encoding="utf-8")
    cols = list(raw.dtype.names)
    cases = [str(v) for v in raw["case"]]
    pcols = [c for c in cols if c not in ("case", "train")]
    X = np.column_stack([np.asarray(raw[c], dtype=np.float64) for c in pcols])
    train = (np.asarray(raw["train"], dtype=int) == 1) if "train" in cols \
        else np.ones(len(cases), dtype=bool)
    return cases, X, pcols, train


# --------------------------------------------------------------------------- #
# Raw weighted Gram matrix  S = X^T diag(vol) X    (nCases x nCases)
# --------------------------------------------------------------------------- #

def gram_inmemory(cases_dir, cases, field, time_index, dtype):
    """Load all snapshots once; return X (m,n) raw, vol (m,), S (n,n), counts, procs."""
    procs = proc_ids(cases_dir, cases[0], field)
    counts = proc_counts(cases_dir, cases[0], field, procs)
    m, n = sum(counts), len(cases)
    X = np.empty((m, n), dtype=dtype)
    for j, c in enumerate(cases):
        start = 0
        for p, cnt in zip(procs, counts):
            arr = np.load(proc_path(cases_dir, c, field, p))[:, time_index]
            X[start:start + cnt, j] = arr
            start += cnt
    vol = np.concatenate([np.load(vol_path(cases_dir, cases[0], p)).reshape(-1) for p in procs]).astype(np.float64)
    # S without an (m,n) temporary: one m-vector at a time
    S = np.empty((n, n))
    for j in range(n):
        wj = vol * X[:, j]
        S[:, j] = X.T @ wj
    return X, vol, S, counts, procs


def gram_streaming(cases_dir, cases, field, time_index, dtype):
    """Accumulate S per processor without holding the full field. Returns S, counts, procs."""
    procs = proc_ids(cases_dir, cases[0], field)
    counts = proc_counts(cases_dir, cases[0], field, procs)
    n = len(cases)
    S = np.zeros((n, n))
    for p, cnt in zip(procs, counts):
        block = np.empty((cnt, n), dtype=dtype)
        for j, c in enumerate(cases):
            block[:, j] = np.load(proc_path(cases_dir, c, field, p))[:, time_index]
        vp = np.load(vol_path(cases_dir, cases[0], p)).reshape(-1).astype(np.float64)
        S += block.T @ (vp[:, None] * block)
    return S, counts, procs


# --------------------------------------------------------------------------- #
# POD from the Gram matrix, for an arbitrary subset of snapshots
# --------------------------------------------------------------------------- #

def centered_eig(S: np.ndarray, T: list[int]):
    """Double-centre S[T,T] (subtract the subset mean), eigen-decompose.

    Returns sigma (k,) descending, Z (k,k) eigenvectors == POD V-vectors.
    """
    M = S[np.ix_(T, T)]
    rm = M.mean(0, keepdims=True)
    cm = M.mean(1, keepdims=True)
    Gc = M - rm - cm + M.mean()                       # centred Gram of the subset
    lam, Z = np.linalg.eigh(Gc)
    order = np.argsort(lam)[::-1]
    lam = np.clip(lam[order], 0.0, None)
    Z = Z[:, order]
    return np.sqrt(lam), Z


# --------------------------------------------------------------------------- #
# Linear map parameters -> coefficients (z-scored inputs, optional ridge)
# --------------------------------------------------------------------------- #

def standardise_fit(Xp):
    mu, sd = Xp.mean(0), Xp.std(0)
    sd[sd == 0] = 1.0
    return mu, sd


def fit_linear(Xp_std, coeffs, ridge=0.0):
    n, p = Xp_std.shape
    Xb = np.hstack([np.ones((n, 1)), Xp_std])
    A = coeffs.T                                       # (n, r)
    if ridge > 0:
        reg = ridge * np.eye(p + 1); reg[0, 0] = 0.0
        W = np.linalg.solve(Xb.T @ Xb + reg, Xb.T @ A)
    else:
        W, *_ = np.linalg.lstsq(Xb, A, rcond=None)
    return W


def predict_coeffs(Xp_std, W):
    Xb = np.hstack([np.ones((Xp_std.shape[0], 1)), Xp_std])
    return (Xb @ W).T                                   # (r, nQuery)


# --------------------------------------------------------------------------- #
# Snapshot-space weights:  field = X @ alpha
# --------------------------------------------------------------------------- #

def alpha_for(a_pred, sigma, Z, r, T, n_total):
    """Convert predicted modal coeffs to full-length snapshot weights alpha."""
    c = Z[:, :r] @ (a_pred / sigma[:r])                # (k,)
    k = len(T)
    alpha_T = c + (1.0 - c.sum()) / k                  # raw-combination weights
    alpha = np.zeros(n_total)
    alpha[T] = alpha_T
    return alpha


# --------------------------------------------------------------------------- #
# Leave-one-out (works from S only; reconstruction needs the snapshots)
# --------------------------------------------------------------------------- #

def loo_errors(S, X_or_None, Xp, vol_or_paths, n_modes, ridge, recon):
    """recon(alpha) -> predicted field; returns volume-weighted rel-L2 per case."""
    n = S.shape[0]
    errs = []
    for i in range(n):
        T = [j for j in range(n) if j != i]
        sigma, Z = centered_eig(S, T)
        rank = np.count_nonzero(sigma > sigma[0] * 1e-12)
        r = rank if n_modes <= 0 else min(n_modes, rank)
        A = sigma[:r, None] * Z[:, :r].T               # (r, k) coeffs for snapshots in T
        mu, sd = standardise_fit(Xp[T])
        W = fit_linear((Xp[T] - mu) / sd, A, ridge)
        a_pred = predict_coeffs((Xp[i:i + 1] - mu) / sd, W)[:, 0]
        alpha = alpha_for(a_pred, sigma, Z, r, T, n)
        errs.append(recon.error(alpha, i))
    return np.array(errs)


# --------------------------------------------------------------------------- #
# Reconstruction back-ends (in-memory vs streaming) + writing numpyToFoam files
# --------------------------------------------------------------------------- #

class InMemoryRecon:
    def __init__(self, X, vol):
        self.X, self.vol = X, vol

    def field(self, alpha):
        return self.X @ alpha

    def error(self, alpha, i):
        pred = self.X @ alpha
        true = self.X[:, i]
        num = np.sqrt(np.sum(self.vol * (true - pred) ** 2))
        den = np.sqrt(np.sum(self.vol * true ** 2))
        return float(num / den) if den else float(num)


class StreamingRecon:
    def __init__(self, cases_dir, cases, field, time_index, dtype, counts, procs):
        self.cd, self.cases, self.field = cases_dir, cases, field
        self.ti, self.dtype, self.counts, self.procs = time_index, dtype, counts, procs

    def _iter_blocks(self):
        for p, cnt in zip(self.procs, self.counts):
            block = np.empty((cnt, len(self.cases)), dtype=self.dtype)
            for j, c in enumerate(self.cases):
                block[:, j] = np.load(proc_path(self.cd, c, self.field, p))[:, self.ti]
            vp = np.load(vol_path(self.cd, self.cases[0], p)).reshape(-1).astype(np.float64)
            yield p, block, vp

    def error(self, alpha, i):
        num = den = 0.0
        for _, block, vp in self._iter_blocks():
            pred = block @ alpha
            true = block[:, i]
            num += np.sum(vp * (true - pred) ** 2)
            den += np.sum(vp * true ** 2)
        return float(np.sqrt(num) / np.sqrt(den)) if den else float(np.sqrt(num))

    def write(self, alpha, out_dir, field):
        fdir = out_dir / field
        fdir.mkdir(parents=True, exist_ok=True)
        for p, block, _ in self._iter_blocks():
            pred = (block @ alpha).reshape(-1, 1)
            np.save(fdir / f"{field}_proc_{p}.npy", np.asfortranarray(pred))


def write_inmemory(field_vec, counts, procs, out_dir, field):
    fdir = out_dir / field
    fdir.mkdir(parents=True, exist_ok=True)
    start = 0
    for p, cnt in zip(procs, counts):
        np.save(fdir / f"{field}_proc_{p}.npy",
                np.asfortranarray(field_vec[start:start + cnt].reshape(cnt, 1)))
        start += cnt


# --------------------------------------------------------------------------- #
# MAIN
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="Memory-efficient linear PODI (method of snapshots).")
    ap.add_argument("--cases-dir", type=Path, required=True)
    ap.add_argument("--parameters", type=Path, required=True)
    ap.add_argument("--field", required=True, help="Field name as exported (e.g. T_CO, T_NOx).")
    ap.add_argument("--modes", type=int, default=0, help="POD modes to keep (0 = all).")
    ap.add_argument("--ridge", type=float, default=0.0)
    ap.add_argument("--dtype", choices=["float32", "float64"], default="float32",
                    help="In-memory snapshot precision (float32 halves memory).")
    ap.add_argument("--streaming", action="store_true",
                    help="Process one processor at a time (mesh-size-independent memory).")
    ap.add_argument("--time-index", type=int, default=-1, help="Column to use if >1 time exported.")
    ap.add_argument("--no-loo", action="store_true")
    ap.add_argument("--predict", type=Path, help="CSV of new [u,v,G,L] rows to predict.")
    ap.add_argument("--predict-out", type=Path, help="Write predicted fields (numpyToFoam layout).")
    args = ap.parse_args()
    dt = np.float32 if args.dtype == "float32" else np.float64

    cases, Xp, pcols, train = load_parameters(args.parameters)
    n = len(cases)

    if args.streaming:
        S, counts, procs = gram_streaming(args.cases_dir, cases, args.field, args.time_index, dt)
        recon = StreamingRecon(args.cases_dir, cases, args.field, args.time_index, dt, counts, procs)
        X = vol = None
    else:
        m = sum(proc_counts(args.cases_dir, cases[0], args.field, proc_ids(args.cases_dir, cases[0], args.field)))
        gb = m * n * (4 if dt == np.float32 else 8) / 1e9
        print(f"In-memory snapshot matrix: {m} cells x {n} cases ~= {gb:.2f} GB ({args.dtype}).")
        X, vol, S, counts, procs = gram_inmemory(args.cases_dir, cases, args.field, args.time_index, dt)
        recon = InMemoryRecon(X, vol)

    print(f"Loaded {n} cases, parameters: {pcols}. Gram matrix {S.shape}.")

    # POD energy on the (full) training set
    tr = list(np.where(train)[0])
    sigma, Z = centered_eig(S, tr)
    energy = np.cumsum(sigma ** 2) / np.sum(sigma ** 2)
    print("Cumulative POD energy:", np.array2string(energy, precision=4, max_line_width=120))

    # leave-one-out accuracy
    if not args.no_loo:
        loo = loo_errors(S, X, Xp, vol if not args.streaming else None, args.modes, args.ridge, recon)
        print(f"Leave-one-out relative L2: mean={loo.mean():.3e}  max={loo.max():.3e}")
        if (Xp.shape[1] + 1) > len(tr):
            print(f"  WARNING: {Xp.shape[1] + 1} linear coeffs vs {len(tr)} training cases -> underdetermined.")

    # final model on the training set
    rank = np.count_nonzero(sigma > sigma[0] * 1e-12)
    r = rank if args.modes <= 0 else min(args.modes, rank)
    A = sigma[:r, None] * Z[:, :r].T
    mu, sd = standardise_fit(Xp[tr])
    W = fit_linear((Xp[tr] - mu) / sd, A, args.ridge)
    print(f"Trained linear PODI: {r} modes, {Xp.shape[1]} inputs.")

    # optional prediction
    if args.predict:
        q = np.genfromtxt(args.predict, delimiter=",", names=True, encoding="utf-8")
        Xq = np.column_stack([np.asarray(q[c], dtype=np.float64) for c in pcols])
        a_pred = predict_coeffs((Xq - mu) / sd, W)                # (r, nQuery)
        for k in range(Xq.shape[0]):
            alpha = alpha_for(a_pred[:, k], sigma, Z, r, tr, n)
            if args.predict_out:
                out = args.predict_out / f"query_{k:03d}"
                if args.streaming:
                    recon.write(alpha, out, args.field)
                else:
                    write_inmemory(recon.field(alpha), counts, procs, out, args.field)
        if args.predict_out:
            print(f"Wrote {Xq.shape[0]} predicted field(s) under {args.predict_out} (run numpyToFoam to view).")


if __name__ == "__main__":
    main()
