"""Gradient-boosting meta-model with graceful backend fallback.

Prefers LightGBM; falls back to sklearn HistGradientBoosting; falls back
to a logistic baseline when neither is installed. All paths expose the
same fit/predict_proba interface so the training script is backend-free.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass
class ModelSpec:
    backend: str  # lightgbm | sklearn-hgb | logistic
    params: dict


def _spec_lightgbm(params: dict) -> Optional[ModelSpec]:
    try:
        import lightgbm  # noqa: F401
        return ModelSpec("lightgbm", params)
    except Exception:
        return None


def _spec_sklearn(params: dict) -> Optional[ModelSpec]:
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: F401
        return ModelSpec("sklearn-hgb", params)
    except Exception:
        return None


def pick_model(params: dict) -> ModelSpec:
    return (_spec_lightgbm(params) or _spec_sklearn(params)
            or ModelSpec("logistic", params))


def fit_model(spec: ModelSpec, X: np.ndarray, y: np.ndarray):
    lr = float(spec.params.get("learning_rate", 0.05))
    depth = int(spec.params.get("max_depth", 5))
    leaves = int(spec.params.get("num_leaves", 31))
    reg = float(spec.params.get("reg_lambda", 1.0))
    seed = int(spec.params.get("seed", 42))
    if spec.backend == "lightgbm":
        import lightgbm as lgb
        train = lgb.Dataset(X, label=y)
        booster = lgb.train(
            {"objective": "binary", "learning_rate": lr, "num_leaves": leaves,
             "max_depth": depth, "lambda_l2": reg, "verbosity": -1,
             "seed": seed},
            train, num_boost_round=int(spec.params.get("n_estimators", 200)))

        class W:
            def predict_proba(self, Xq):
                p = booster.predict(Xq)
                return np.column_stack([1 - p, p])

        return W()
    if spec.backend == "sklearn-hgb":
        from sklearn.ensemble import HistGradientBoostingClassifier
        clf = HistGradientBoostingClassifier(
            learning_rate=lr, max_depth=max(depth, 1) if depth > 0 else None,
            max_iter=int(spec.params.get("n_estimators", 200)),
            l2_regularization=reg, random_state=seed)
        clf.fit(X, y)
        return clf
    # Pure-numpy logistic baseline (no sklearn/scipy needed).
    from ml4t.nblogistic import NumpyLogistic
    w = np.zeros(X.shape[1]); b = 0.0
    mu = X.mean(axis=0); sd = X.std(axis=0) + 1e-9
    Xs = (X - mu) / sd
    for _ in range(300):
        p = 1.0 / (1.0 + np.exp(-(Xs @ w + b)))
        g = Xs.T @ (p - y) / len(y) + reg * w / len(y)
        gb = float((p - y).mean())
        w -= lr * g; b -= lr * gb
    return NumpyLogistic(w, b, mu, sd)
