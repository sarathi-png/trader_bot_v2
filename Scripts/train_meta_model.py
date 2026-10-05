"""Train the meta-label model (Optuna + purged CV, LightGBM preferred).

Usage: python Scripts/train_meta_model.py [ltf] [bars] [trials]
Reads cached history CSVs, builds Tier-2 features + triple-barrier meta
labels, tunes a small param space with a purged-CV AUC objective, retrains
on all data, and writes output/meta_model.json (+ .pkl when possible).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np
import pandas as pd

from ml4t.features import FEATURE_COLUMNS, build_features
from ml4t.gbm import fit_model, pick_model
from ml4t.labeling import BarrierConfig, triple_barrier_labels
from ml4t.purged_cv import purged_walk_forward


def _auc(y: np.ndarray, p: np.ndarray) -> float:
    try:
        from sklearn.metrics import roc_auc_score
        return float(roc_auc_score(y, p))
    except Exception:
        order = np.argsort(p, kind="mergesort"); r = y[order]
        n1, n0 = r.sum(), len(r) - r.sum()
        if n1 == 0 or n0 == 0:
            return 0.5
        return float((np.searchsorted(np.sort(p[y == 0]), p[y == 1])).mean() / n0)


def main():
    ltf = sys.argv[1] if len(sys.argv) > 1 else "15m"
    bars = int(sys.argv[2]) if len(sys.argv) > 2 else 12000
    trials = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    cache = os.path.join(ROOT, "output", "history_BTCUSD_%s.csv" % ltf)
    if not os.path.exists(cache):
        print("no cache at %s; run run_walk_forward.py first" % cache)
        sys.exit(1)
    df = pd.read_csv(cache, index_col=0, parse_dates=True).tail(bars).iloc[:-1]
    feats = build_features(df)
    cfg = BarrierConfig()
    labels = triple_barrier_labels(df, cfg)
    primary = labels["primary"].to_numpy(float)
    # Meta task: predict whether the PRIMARY side would have been
    # profitable (1) or not (0). Rows where primary == 0 carry no
    # directional call and are excluded from training.
    ret = np.where(primary > 0, labels["ret_long"].to_numpy(float),
                   np.where(primary < 0, labels["ret_short"].to_numpy(float), np.nan))
    X = feats[FEATURE_COLUMNS].to_numpy(float)
    valid = np.isfinite(X).all(axis=1) & np.isfinite(ret) & (primary != 0)
    X, y = X[valid], (ret[valid] > 0).astype(int)
    print("rows=%d pos_rate=%.3f" % (len(y), y.mean() if len(y) else 0))
    if len(y) < 1000 or y.sum() < 50 or y.sum() > len(y) - 50:
        print("not enough labelled data; abort")
        sys.exit(2)
    splits = purged_walk_forward(len(y), n_splits=4)

    def objective(trial):
        params = {"learning_rate": trial.suggest_float("lr", 0.01, 0.2, log=True),
                  "num_leaves": trial.suggest_int("leaves", 15, 127),
                  "max_depth": trial.suggest_int("depth", 3, 8),
                  "reg_lambda": trial.suggest_float("reg", 0.1, 10.0, log=True),
                  "n_estimators": 200, "seed": 42}
        aucs = []
        for tr, te in [(s.train, s.test) for s in splits]:
            spec = pick_model(params)
            model = fit_model(spec, X[tr], y[tr])
            aucs.append(_auc(y[te], model.predict_proba(X[te])[:, 1]))
        return float(np.mean(aucs))

    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=trials)
    print("best AUC=%.4f params=%s" % (study.best_value, study.best_params))
    best = {"learning_rate": study.best_params["lr"],
            "num_leaves": study.best_params["leaves"],
            "max_depth": study.best_params["depth"],
            "reg_lambda": study.best_params["reg"],
            "n_estimators": 300, "seed": 42}
    spec = pick_model(best)
    model = fit_model(spec, X, y)
    out = {"backend": spec.backend, "params": best,
           "features": FEATURE_COLUMNS, "ltf": ltf, "rows": len(y),
           "pos_rate": float(y.mean()), "cv_auc": float(study.best_value),
           "barrier": {"atr_mult": cfg.atr_mult, "max_hold": cfg.max_hold}}
    # Export the inference weights alongside the metrics so downstream
    # runtimes (the TypeScript terminal in D:\Projects\trading-command-v3)
    # can score without reimplementing training. Only the logistic backend
    # is portable; tree models need their own runtime.
    if spec.backend == "logistic" and all(hasattr(model, a) for a in ("w", "b", "mu", "sd")):
        out["inference"] = {
            "kind": "logistic",
            "w": [float(v) for v in getattr(model, "w")],
            "b": float(getattr(model, "b")),
            "mu": [float(v) for v in getattr(model, "mu")],
            "sd": [float(v) for v in getattr(model, "sd")],
        }
    os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)
    with open(os.path.join(ROOT, "output", "meta_model.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    try:
        import pickle
        with open(os.path.join(ROOT, "output", "meta_model.pkl"), "wb") as fh:
            pickle.dump(model, fh)
        print("saved output/meta_model.json + .pkl (backend=%s)" % spec.backend)
    except Exception as exc:
        print("saved output/meta_model.json (pkl skipped: %s)" % exc)


if __name__ == "__main__":
    main()
