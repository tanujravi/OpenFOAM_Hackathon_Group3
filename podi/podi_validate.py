#!/usr/bin/env python3
"""
podi_validate.py
================
Validation study + model export for the linear PODI surrogate.

  1. Split the cases 75/25 (train/test), stratified by (G,L) scenario so every
     scenario appears in both sets.
  2. Sweep the number of POD modes and record train (leave-one-out) and test
     error, to choose the mode count.
  3. Save diagnostic plots to ./plot/ :
        pod_spectrum.png     singular values + cumulative energy
        mode_selection.png   error vs #modes (train-LOO and test), chosen r marked
        parity.png           predicted vs true field values on the test set
        per_case_error.png   relative-L2 per case (train vs test)
        coeff_fit.png        linearity of parameters -> modal coefficients
     and a text summary (validation_summary.txt).
  4. Refit on ALL cases at the chosen r and pickle the model OPERATORS
        {mean, modes (nCells x r), W, standardizer, beta (scale model), ...}
     so fields can be predicted later with no training data:
        shape(x) = mean + modes @ ( [1, standardise(shape_features(x))] @ W )
        field(x) = magnitude(x) * shape(x)
     Magnitude and shape are decoupled: concentration dilutes ~1/|wind| and
     scales exactly with emission G, a ~50x dynamic range no single linear map
     can hold.  So the SHAPE (x/||x||) is handled by POD + linear regression,
     and the scalar MAGNITUDE ||x|| by a separate multiplicative model (RBF
     interpolation over the wind vector; see fit_scale).

Usage:
    python3 podi_validate.py --cases-dir staging/CO --parameters parameters.csv \
        --field T_CO --out-model model_CO.pkl
    # choose the mode count automatically (min test error) or force it with --modes

Reuse a saved model later:
    python3 podi_validate.py --from-model model_CO.pkl --predict q.csv --predict-out preds
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import yaml

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --------------------------------------------------------------------------- #
# Method-of-snapshots core + per-processor loaders (inlined; self-contained)
# --------------------------------------------------------------------------- #
import re

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

def load_parameters(csv_path: Path):
    raw = np.genfromtxt(csv_path, delimiter=",", names=True, dtype=None, encoding="utf-8")
    cols = list(raw.dtype.names)
    cases = [str(v) for v in raw["case"]]
    pcols = [c for c in cols if c not in ("case", "train")]
    X = np.column_stack([np.asarray(raw[c], dtype=np.float64) for c in pcols])
    train = (np.asarray(raw["train"], dtype=int) == 1) if "train" in cols \
        else np.ones(len(cases), dtype=bool)
    return cases, X, pcols, train

def resolve_workers(workers):
    """0/None -> use SLURM_CPUS_PER_TASK if set, else a sensible default."""
    if workers and int(workers) > 0:
        return int(workers)
    env = os.environ.get("SLURM_CPUS_PER_TASK")
    if env and env.isdigit():
        return max(1, int(env))
    return min(16, os.cpu_count() or 8)


def gram_inmemory(cases_dir, cases, field, time_index, dtype, workers=0):
    """Load all snapshots once; return X (m,n) raw, vol (m,), S (n,n), counts, procs.

    File reads (nCases x nProcs of them) are done with a thread pool: np.load
    releases the GIL during the read, and each task writes a DISJOINT slice of X,
    so the reads overlap on the parallel filesystem with no locking or copying.
    """
    procs = proc_ids(cases_dir, cases[0], field)
    counts = proc_counts(cases_dir, cases[0], field, procs)
    m, n = sum(counts), len(cases)
    offs = np.zeros(len(procs), dtype=np.int64)
    if len(procs) > 1:
        offs[1:] = np.cumsum(counts)[:-1]
    X = np.empty((m, n), dtype=dtype)

    tasks = [(j, c, p, int(offs[pi]), int(counts[pi]))
             for j, c in enumerate(cases) for pi, p in enumerate(procs)]

    def _load(task):
        j, c, p, row0, cnt = task
        arr = np.load(proc_path(cases_dir, c, field, p))[:, time_index]
        X[row0:row0 + cnt, j] = np.asarray(arr, dtype=dtype)

    nw = resolve_workers(workers)
    if nw > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=nw) as ex:
            for _ in ex.map(_load, tasks):   # iterate so exceptions surface
                pass
    else:
        for t in tasks:
            _load(t)

    vol = np.concatenate([np.load(vol_path(cases_dir, cases[0], p)).reshape(-1) for p in procs]).astype(np.float64)
    return X, vol, counts, procs


def build_gram(X, vol):
    """Weighted Gram S = X^T diag(vol) X, one m-vector at a time (no m x n temp)."""
    n = X.shape[1]
    S = np.empty((n, n))
    for j in range(n):
        S[:, j] = X.T @ (vol * X[:, j])
    return S

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

def standardise_fit(Xp):
    mu, sd = Xp.mean(0), Xp.std(0)
    sd[sd == 0] = 1.0
    return mu, sd


# --------------------------------------------------------------------------- #
# Shape / scale decoupling
# --------------------------------------------------------------------------- #
# The pollutant field magnitude spans ~50x across cases because concentration
# dilutes as ~1/|wind| and scales linearly with emission G.  A single linear map
# in (u,v,G,L) cannot represent that, and the per-case relative-L2 metric then
# explodes on the small (high-wind) cases.  So we split the problem:
#   * POD/regress the SHAPE  x/||x||   (unit-norm snapshots)
#   * predict the scalar MAGNITUDE ||x|| with a log-linear model (dilution is
#     multiplicative), then reconstruct  field = magnitude * shape.

def _speed(Xp, idx):
    return np.sqrt(Xp[:, idx["u"]] ** 2 + Xp[:, idx["v"]] ** 2)


def shape_features(Xp, pcols):
    """Augment the raw parameters with wind-physics terms for the SHAPE fit."""
    idx = {c: i for i, c in enumerate(pcols)}
    extra = []
    if "u" in idx and "v" in idx:
        sp = np.clip(_speed(Xp, idx), 1e-30, None)
        extra += [sp, 1.0 / sp]
        if "G" in idx:
            extra.append(Xp[:, idx["G"]] / sp)          # emission / dilution
    return np.column_stack([Xp, *extra]) if extra else Xp


def _logc(a):
    return np.log(np.clip(a, 1e-30, None))


def fit_scale(Xp, scale, pcols):
    """Model the scalar magnitude ||x|| multiplicatively:

        log||x|| = logG              (emission scales concentration EXACTLY)
                 + b0 + bL*logL      (partial local-road factor)
                 + f(u, v)           (wind: interpolated over the wind vector)

    The same wind vectors recur across scenarios, so f is a thin-plate-spline
    RBF interpolation of the residual over (u,v): a held-out hour is recovered
    from the identical wind in another scenario -- far better than a global
    slope in |U|.  Falls back to a log-linear model if SciPy/RBF is unavailable.
    """
    idx = {c: i for i, c in enumerate(pcols)}
    y = _logc(scale)
    if "G" in idx:
        y = y - _logc(Xp[:, idx["G"]])                # remove exact emission linearity
    bL = None
    if "L" in idx:
        FL = np.column_stack([np.ones(len(Xp)), _logc(Xp[:, idx["L"]])])
        bL, *_ = np.linalg.lstsq(FL, y, rcond=None)
        y = y - FL @ bL                               # residual after the L factor
    rbf = beta = None
    ymean = float(y.mean())
    if "u" in idx and "v" in idx:
        pts = np.column_stack([Xp[:, idx["u"]], Xp[:, idx["v"]]])
        try:
            from scipy.interpolate import RBFInterpolator
            rbf = RBFInterpolator(pts, y, kernel="thin_plate_spline", smoothing=1e-3)
        except Exception:                             # no SciPy -> global log-linear in log|U|
            F = np.column_stack([np.ones(len(Xp)), _logc(_speed(Xp, idx))])
            beta, *_ = np.linalg.lstsq(F, y, rcond=None)
    return {"bL": bL, "rbf": rbf, "beta": beta, "ymean": ymean}


def predict_scale(Xp, model, pcols):
    idx = {c: i for i, c in enumerate(pcols)}
    if model["rbf"] is not None:
        y = model["rbf"](np.column_stack([Xp[:, idx["u"]], Xp[:, idx["v"]]]))
    elif model["beta"] is not None:
        y = np.column_stack([np.ones(len(Xp)), _logc(_speed(Xp, idx))]) @ model["beta"]
    else:
        y = np.full(len(Xp), model["ymean"])
    if model["bL"] is not None:
        y = y + np.column_stack([np.ones(len(Xp)), _logc(Xp[:, idx["L"]])]) @ model["bL"]
    if "G" in idx:
        y = y + _logc(Xp[:, idx["G"]])
    return np.exp(y)

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
    return (Xb @ W).T

def alpha_for(a_pred, sigma, Z, r, T, n_total):
    """Convert predicted modal coeffs to full-length snapshot weights alpha."""
    c = Z[:, :r] @ (a_pred / sigma[:r])                # (k,)
    k = len(T)
    alpha_T = c + (1.0 - c.sum()) / k                  # raw-combination weights
    alpha = np.zeros(n_total)
    alpha[T] = alpha_T
    return alpha


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def rel_l2(true, pred, vol):
    num = np.sqrt(np.sum(vol * (true - pred) ** 2))
    den = np.sqrt(np.sum(vol * true ** 2))
    return float(num / den) if den else float(num)


def stratified_split(Xp, pcols, test_frac, seed):
    """75/25 split, stratified by the (G,L) columns so each scenario is covered."""
    gi = [pcols.index(c) for c in ("G", "L") if c in pcols]
    rng = np.random.default_rng(seed)
    keys = {}
    for i in range(Xp.shape[0]):
        k = tuple(np.round(Xp[i, gi], 6)) if gi else (0,)
        keys.setdefault(k, []).append(i)
    train, test = [], []
    for members in keys.values():
        members = list(members)
        rng.shuffle(members)
        ntest = max(1, round(test_frac * len(members))) if len(members) > 1 else 0
        test += members[:ntest]
        train += members[ntest:]
    return sorted(train), sorted(test)


def train_operators(S, Xp, scale, train, r, ridge, pcols):
    """Shape regression (on the unit-norm Gram S) + log-linear scale model."""
    sigma, Z = centered_eig(S, train)
    rank = int(np.count_nonzero(sigma > sigma[0] * 1e-12))
    r_use = rank if r <= 0 else min(r, rank)
    A = sigma[:r_use, None] * Z[:, :r_use].T           # (r_use, |train|)
    F = shape_features(Xp, pcols)
    mu, sd = standardise_fit(F[train])
    W = fit_linear((F[train] - mu) / sd, A, ridge)
    beta = fit_scale(Xp[train], scale[train], pcols)
    return sigma, Z, r_use, mu, sd, W, beta


def fold_error_curve(S, Xp, scale, T, q, ridge, pcols):
    """Relative-L2 error of predicting case q from train subset T, for r=1..rank.

    S is the Gram of the UNIT-NORM snapshots.  The reconstructed field is
    magnitude * shape, so the error combines the shape (POD) error and the
    predicted-magnitude error.  For unit-norm snapshots xn, with predicted
    shape  xn_pred = Xn @ alpha  and predicted magnitude s_pred,

        ||s_q xn_q - s_pred xn_pred||^2
            = s_q^2 <xn_q,xn_q> - 2 s_q s_pred <xn_q,xn_pred> + s_pred^2 <xn_pred,xn_pred>

    and every inner product is an entry of / a bilinear form in S -- no 20M-cell
    reconstruction.  Normalised by ||x_q|| = s_q * sqrt(S[q,q]).
    """
    sigma, Z = centered_eig(S, T)
    rank = int(np.count_nonzero(sigma > sigma[0] * 1e-12))
    if rank == 0:
        return np.array([1.0])
    A = sigma[:rank, None] * Z[:, :rank].T
    F = shape_features(Xp, pcols)
    mu, sd = standardise_fit(F[T])
    W = fit_linear((F[T] - mu) / sd, A, ridge)
    a = predict_coeffs((F[q][None] - mu) / sd, W)[:, 0]          # (rank,)

    beta = fit_scale(Xp[T], scale[T], pcols)
    s_pred = float(predict_scale(Xp[q:q + 1], beta, pcols)[0])
    s_true = float(scale[q])
    Sqq = float(S[q, q])
    n = S.shape[0]
    Sq = S[q]                                                     # (n,) row q
    errs = []
    for r in range(1, rank + 1):
        alpha = alpha_for(a[:r], sigma, Z, r, T, n)               # xn_pred = Xn @ alpha
        cross = float(Sq @ alpha)                                # <xn_q, xn_pred>
        selfp = float(alpha @ (S @ alpha))                       # <xn_pred, xn_pred>
        e2 = s_true ** 2 * Sqq - 2 * s_true * s_pred * cross + s_pred ** 2 * selfp
        den = s_true * np.sqrt(Sqq) if Sqq > 0 else 1.0
        errs.append(np.sqrt(max(e2, 0.0)) / den)
    return np.array(errs)


# --------------------------------------------------------------------------- #
# reuse a pickled model (no training data needed)
# --------------------------------------------------------------------------- #

def predict_from_model(model_path, query_csv, out_dir):
    with open(model_path, "rb") as f:
        M = pickle.load(f)
    q = np.genfromtxt(query_csv, delimiter=",", names=True, encoding="utf-8")
    pcols = M["param_names"]
    Xq = np.column_stack([np.asarray(q[c], dtype=np.float64) for c in pcols])
    # shape coefficients from the augmented, standardised features
    Fq = shape_features(Xq, pcols)
    Xb = np.hstack([np.ones((Xq.shape[0], 1)), (Fq - M["mu"]) / M["sd"]])
    coeffs = Xb @ M["W"]                                # (nQuery, r)
    scale = predict_scale(Xq, M["beta"], pcols)         # (nQuery,) magnitude
    out_dir = Path(out_dir)
    for k in range(Xq.shape[0]):
        field = scale[k] * (M["mean"] + M["modes"] @ coeffs[k])
        fdir = out_dir / f"query_{k:03d}" / M["field"]
        fdir.mkdir(parents=True, exist_ok=True)
        start = 0
        for p, cnt in zip(M["procs"], M["counts"]):
            np.save(fdir / f"{M['field']}_proc_{p}.npy",
                    np.asfortranarray(field[start:start + cnt].reshape(cnt, 1)))
            start += cnt
    print(f"Wrote {Xq.shape[0]} predicted field(s) under {out_dir} using {model_path}.")


# --------------------------------------------------------------------------- #
# plots
# --------------------------------------------------------------------------- #

def plot_spectrum(sigma, plotdir):
    energy = np.cumsum(sigma ** 2) / np.sum(sigma ** 2)
    k = np.arange(1, len(sigma) + 1)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    ax[0].semilogy(k, sigma, "o-")
    ax[0].set(xlabel="mode", ylabel="singular value", title="POD spectrum")
    ax[0].grid(True, alpha=.3)
    ax[1].plot(k, energy, "s-")
    ax[1].axhline(0.99, ls="--", c="grey"); ax[1].axhline(0.999, ls=":", c="grey")
    ax[1].set(xlabel="modes kept", ylabel="cumulative energy", title="captured variance",
              ylim=(min(0.5, energy[0]), 1.01))
    ax[1].grid(True, alpha=.3)
    fig.tight_layout(); fig.savefig(plotdir / "pod_spectrum.png", dpi=130); plt.close(fig)


def plot_mode_selection(rs, loo, test, r_star, plotdir):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(rs, loo, "o-", label="train (leave-one-out)")
    ax.plot(rs, test, "s-", label="test (25% hold-out)")
    ax.axvline(r_star, ls="--", c="k", alpha=.7, label=f"chosen r = {r_star}")
    ax.set(xlabel="number of POD modes", ylabel="mean relative L2 error",
           title="mode selection")
    ax.grid(True, alpha=.3); ax.legend()
    fig.tight_layout(); fig.savefig(plotdir / "mode_selection.png", dpi=130); plt.close(fig)


def plot_parity(true_vals, pred_vals, plotdir, field):
    lo = min(true_vals.min(), pred_vals.min()); hi = max(true_vals.max(), pred_vals.max())
    ss_res = np.sum((true_vals - pred_vals) ** 2)
    ss_tot = np.sum((true_vals - true_vals.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    ax.scatter(true_vals, pred_vals, s=4, alpha=.25, edgecolors="none")
    ax.plot([lo, hi], [lo, hi], "k--", lw=1)
    ax.set(xlabel=f"true {field}", ylabel=f"predicted {field}",
           title=f"test-set parity  (R^2 = {r2:.4f})")
    ax.grid(True, alpha=.3)
    fig.tight_layout(); fig.savefig(plotdir / "parity.png", dpi=130); plt.close(fig)
    return r2


def plot_per_case(cases, errs, train, test, plotdir):
    colors = ["#1f77b4" if i in set(train) else "#d62728" for i in range(len(cases))]
    fig, ax = plt.subplots(figsize=(max(7, len(cases) * 0.28), 4))
    ax.bar(range(len(cases)), errs, color=colors)
    ax.set_xticks(range(len(cases))); ax.set_xticklabels(cases, rotation=90, fontsize=7)
    ax.set(ylabel="relative L2 error", title="per-case error (blue=train, red=test)")
    ax.grid(True, axis="y", alpha=.3)
    fig.tight_layout(); fig.savefig(plotdir / "per_case_error.png", dpi=130); plt.close(fig)


def plot_coeff_fit(A_true, A_pred, plotdir):
    nmodes = min(4, A_true.shape[0])
    fig, ax = plt.subplots(1, nmodes, figsize=(3.2 * nmodes, 3.2))
    if nmodes == 1:
        ax = [ax]
    for k in range(nmodes):
        t, p = A_true[k], A_pred[k]
        lo, hi = min(t.min(), p.min()), max(t.max(), p.max())
        ax[k].scatter(t, p, s=14)
        ax[k].plot([lo, hi], [lo, hi], "k--", lw=1)
        ax[k].set(title=f"mode {k+1}", xlabel="true coeff", ylabel="predicted coeff")
        ax[k].grid(True, alpha=.3)
    fig.suptitle("parameters -> modal coefficient (linearity check)")
    fig.tight_layout(); fig.savefig(plotdir / "coeff_fit.png", dpi=130); plt.close(fig)


# --------------------------------------------------------------------------- #
# MAIN
# --------------------------------------------------------------------------- #

def run_study(parameters, cases_dir, field, plotdir, out_model,
              test_frac, seed, modes, ridge, dtype, workers):
    """Full validation study + pickled model for one pollutant."""
    dt = np.float32 if dtype == "float32" else np.float64
    plotdir = Path(plotdir); plotdir.mkdir(parents=True, exist_ok=True)
    out_model = Path(out_model); out_model.parent.mkdir(parents=True, exist_ok=True)

    cases, Xp, pcols, _ = load_parameters(parameters)
    n = len(cases)
    print(f"Loading snapshots with {resolve_workers(workers)} threads ...", flush=True)
    X, vol, counts, procs = gram_inmemory(cases_dir, cases, field, -1, dt, workers)
    print(f"Loaded {n} cases, {X.shape[0]} cells. Computing error curves (Gram space) ...", flush=True)

    # Decouple magnitude from shape: normalise each snapshot to unit volume-norm
    # (concentration spans ~50x across cases via dilution ~ 1/|wind|).  POD/regress
    # the shape; predict the scalar magnitude separately with a log-linear model.
    scale = np.empty(n)                                          # (n,) ||x_c||_vol
    for j in range(n):                                           # per column: no (m,n) f64 temp
        xj = X[:, j].astype(np.float64)
        scale[j] = np.sqrt(vol @ (xj * xj))
    scale[scale == 0] = 1.0
    X /= scale                                                    # X is now unit-norm (in place)
    S = build_gram(X, vol)                                        # Gram of the shapes

    train, test = stratified_split(Xp, pcols, test_frac, seed)

    # All validation errors come from the (n x n) Gram matrix + the per-case
    # scalar magnitudes -- no field reconstruction, so this is instant.
    loo_fold = [fold_error_curve(S, Xp, scale, [j for j in train if j != i], i, ridge, pcols) for i in train]
    test_fold = [fold_error_curve(S, Xp, scale, train, t, ridge, pcols) for t in test]
    max_r = min(min(len(c) for c in loo_fold), min(len(c) for c in test_fold))
    rs = list(range(1, max_r + 1))
    loo_curve = np.mean(np.array([c[:max_r] for c in loo_fold]), axis=0)
    test_curve = np.mean(np.array([c[:max_r] for c in test_fold]), axis=0)

    if modes > 0:
        r_star = min(modes, max_r)
    else:
        tmin = test_curve.min()
        r_star = int(min(rs[i] for i in range(len(rs)) if test_curve[i] <= tmin * 1.02))
    print(f"Split: {len(train)} train / {len(test)} test (stratified by G,L).")
    print(f"Chosen modes r = {r_star}  (test error {test_curve[r_star-1]:.3e}, "
          f"train-LOO {loo_curve[r_star-1]:.3e})", flush=True)

    # plots that need only small data
    sig_tr, _ = centered_eig(S, train)
    plot_spectrum(sig_tr, plotdir)
    plot_mode_selection(rs, loo_curve, test_curve, r_star, plotdir)

    # per-case error at r_star straight from the curves (no reconstruction)
    per_case_err = np.zeros(n)
    for k, i in enumerate(train):
        per_case_err[i] = loo_fold[k][min(r_star, len(loo_fold[k])) - 1]
    for k, t in enumerate(test):
        per_case_err[t] = test_fold[k][min(r_star, len(test_fold[k])) - 1]
    plot_per_case(cases, per_case_err, train, test, plotdir)

    # parity: reconstruct ONLY sampled cells for the test cases (cheap).
    # X holds unit-norm shapes, so raw = magnitude * shape.
    sig, Z, r_use, mu, sd, W, beta = train_operators(S, Xp, scale, train, r_star, ridge, pcols)
    Ftr = shape_features(Xp, pcols)
    rng = np.random.default_rng(seed)
    samp = rng.choice(X.shape[0], size=min(4000, X.shape[0]), replace=False)
    Xsamp = X[samp, :]
    tv, pv = [], []
    for t in test:
        a = predict_coeffs((Ftr[t][None] - mu) / sd, W)[:, 0]
        alpha = alpha_for(a, sig, Z, r_use, train, n)
        s_pred = float(predict_scale(Xp[t:t + 1], beta, pcols)[0])
        tv.append(scale[t] * Xsamp[:, t]); pv.append(s_pred * (Xsamp @ alpha))
    r2 = plot_parity(np.concatenate(tv), np.concatenate(pv), plotdir, field)

    sig_all, Z_all = centered_eig(S, list(range(n)))
    A_all = sig_all[:r_star, None] * Z_all[:, :r_star].T
    Fall = shape_features(Xp, pcols)
    muA, sdA = standardise_fit(Fall)
    WA = fit_linear((Fall - muA) / sdA, A_all, ridge)
    A_pred = predict_coeffs((Fall - muA) / sdA, WA)
    plot_coeff_fit(A_all, A_pred, plotdir)
    beta_all = fit_scale(Xp, scale, pcols)

    # ---- final model: the ONLY full-mesh operation (one m x r matmul) ---- #
    print("Building final model operators ...", flush=True)
    mean_all = X.mean(axis=1)                                     # mean SHAPE
    # modes = (X - mean) @ M without materialising the (m x n) centred copy:
    #   (X - mean 1^T) @ M = X@M - mean * (1^T M)
    Mmat = Z_all[:, :r_star] / sig_all[:r_star]                   # (n x r)
    modes_arr = (X @ Mmat - np.outer(mean_all, Mmat.sum(axis=0))).astype(np.float32)
    model = {
        "field": field, "param_names": pcols,
        "mu": muA, "sd": sdA, "W": WA.astype(np.float64),
        "beta": beta_all,                                        # log-linear magnitude model
        "mean": mean_all.astype(np.float32), "modes": modes_arr,
        "sigma": sig_all[:r_star], "n_modes": r_star,
        "counts": counts, "procs": procs,
        "split": {"train": train, "test": test, "seed": seed},
    }
    with open(out_model, "wb") as f:
        pickle.dump(model, f, protocol=4)
    size_mb = (modes_arr.nbytes + mean_all.astype(np.float32).nbytes) / 1e6
    print(f"Saved model operators -> {out_model}  (modes {modes_arr.shape}, ~{size_mb:.1f} MB).")

    with open(plotdir / "validation_summary.txt", "w") as f:
        f.write(f"field: {field}\ncases: {n}  train: {len(train)}  test: {len(test)}\n")
        f.write(f"train indices: {train}\ntest indices:  {test}\n\n")
        f.write("modes  train_LOO      test\n")
        for r, l, t in zip(rs, loo_curve, test_curve):
            mark = "  <-- chosen" if r == r_star else ""
            f.write(f"{r:5d}  {l:.6e}  {t:.6e}{mark}\n")
        f.write(f"\nchosen r = {r_star}\ntest-set parity R^2 = {r2:.5f}\n")
        f.write(f"mean test relative-L2 = {test_curve[r_star-1]:.5e}\n")
    print(f"Plots + summary written to {plotdir}/")
    return {"pollutant_field": field, "r": r_star, "test_relL2": float(test_curve[r_star-1]), "R2": r2}


def load_config(path):
    cfg = yaml.safe_load(open(path)) or {}
    p = cfg.get("podi", {})
    p.setdefault("parameters", "collected/parameters.csv")
    p.setdefault("staging_root", "collected/staging")
    p.setdefault("plot_root", "plot")
    p.setdefault("model_dir", "models")
    p.setdefault("test_frac", 0.25)
    p.setdefault("seed", 0)
    p.setdefault("modes", 0)
    p.setdefault("ridge", 0.0)
    p.setdefault("dtype", "float32")
    p.setdefault("workers", 0)   # 0 = auto (SLURM_CPUS_PER_TASK)
    if not p.get("pollutants"):
        sys.exit("config: 'podi.pollutants' is required (list of {name, field}).")
    return p


def main():
    ap = argparse.ArgumentParser(description="Config-driven PODI validation for all pollutants.")
    ap.add_argument("config", nargs="?", default="config.yaml", help="YAML config (default config.yaml).")
    ap.add_argument("--from-model", type=Path, help="Reuse a pickled model to predict, then exit.")
    ap.add_argument("--predict", type=Path)
    ap.add_argument("--predict-out", type=Path)
    args = ap.parse_args()

    if args.from_model:
        if not (args.predict and args.predict_out):
            ap.error("--from-model needs --predict and --predict-out")
        predict_from_model(args.from_model, args.predict, args.predict_out)
        return

    p = load_config(args.config)
    results = []
    for pol in p["pollutants"]:
        name, field = pol["name"], pol["field"]
        print(f"\n########## {name}  (field={field}) ##########")
        res = run_study(
            parameters=Path(p["parameters"]),
            cases_dir=Path(p["staging_root"]) / name,
            field=field,
            plotdir=Path(p["plot_root"]) / name,
            out_model=Path(p["model_dir"]) / f"model_{name}.pkl",
            test_frac=p["test_frac"], seed=p["seed"], modes=p["modes"],
            ridge=p["ridge"], dtype=p["dtype"], workers=p["workers"],
        )
        results.append((name, res))

    print("\n================ ALL POLLUTANTS ================")
    for name, r in results:
        print(f"  {name:4s}  field={r['pollutant_field']:6s}  modes={r['r']:3d}  "
              f"test relL2={r['test_relL2']:.3e}  R2={r['R2']:.4f}")


if __name__ == "__main__":
    main()
