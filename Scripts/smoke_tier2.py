"""Smoke Tier-2: features + labels + regime on cached history."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np
import pandas as pd

from ml4t.features import FEATURE_COLUMNS, build_features
from ml4t.labeling import triple_barrier_labels
from ml4t.regime import fit_predict_regimes


def main():
    cache = os.path.join(ROOT, "output", "history_BTCUSD_15m.csv")
    df = pd.read_csv(cache, index_col=0, parse_dates=True).tail(600)
    feats = build_features(df)
    print("FEATS-OK n=%d cols=%d" % (len(feats), len(FEATURE_COLUMNS)))
    print("LAST", feats[FEATURE_COLUMNS].iloc[-1].round(3).to_dict())
    labels = triple_barrier_labels(df)
    print("LABELS", labels["primary"].value_counts(dropna=False).to_dict())
    regs = fit_predict_regimes(df["close"].pct_change().fillna(0).to_numpy())
    uniq, counts = np.unique(regs, return_counts=True)
    print("REGIME", dict(zip(uniq.tolist(), counts.tolist())))


if __name__ == "__main__":
    main()
