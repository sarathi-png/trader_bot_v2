"""HMM regime detection (trend vs range) with a volatility fallback.

hmmlearn is optional: when unavailable, regimes fall back to an
ATR-normalised-range rule so the pipeline stays dependency-light.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def fit_predict_regimes(returns: np.ndarray, n_states: int = 2,
                        seed: int = 42) -> np.ndarray:
    r = np.asarray(returns, dtype=float)
    mask = np.isfinite(r)
    labels = np.zeros(len(r), dtype=int)
    try:
        from hmmlearn.hmm import GaussianHMM
        model = GaussianHMM(n_components=n_states, covariance_type="diag",
                            n_iter=100, random_state=seed)
        model.fit(r[mask].reshape(-1, 1))
        labels[mask] = model.predict(r[mask].reshape(-1, 1))
        vols = [np.std(r[mask][labels[mask] == k]) for k in range(n_states)]
        if vols[0] < vols[1]:
            labels = 1 - labels  # state 1 == high-vol / range regime
    except Exception:
        vol = pd.Series(r).rolling(20).std().to_numpy()
        labels = (vol > np.nanmedian(vol)).astype(int)
    return labels
