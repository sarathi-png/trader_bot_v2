"""Numpy-logistic meta-model wrapper (picklable, backend='logistic')."""
from __future__ import annotations
import numpy as np


class NumpyLogistic:
    def __init__(self, w, b, mu, sd):
        self.w = np.asarray(w, dtype=float)
        self.b = float(b)
        self.mu = np.asarray(mu, dtype=float)
        self.sd = np.asarray(sd, dtype=float)

    def predict_proba(self, Xq):
        Xq = np.asarray(Xq, dtype=float)
        z = ((Xq - self.mu) / self.sd) @ self.w + self.b
        p = 1.0 / (1.0 + np.exp(-z))
        return np.column_stack([1 - p, p])
