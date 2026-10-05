"""Meta-model gate: veto signals the LightGBM/meta model rejects.

Loads output/meta_model.json (+ .pkl). When the model file is absent the
gate is inert (returns passed=True) so a Space without trained artifacts
behaves exactly as before. Probability threshold comes from
META_MODEL_MIN_PROB (default 0.5).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)

_MODEL = None
_MODEL_META = None


def _paths():
    root = Path(__file__).parent.parent
    return (root / "output" / "meta_model.json", root / "output" / "meta_model.pkl")


def model_available() -> bool:
    json_path, _ = _paths()
    return json_path.is_file()


def _load():
    global _MODEL, _MODEL_META
    if _MODEL is not None:
        return _MODEL, _MODEL_META
    json_path, pkl_path = _paths()
    if not json_path.is_file():
        return None, None
    _MODEL_META = json.loads(json_path.read_text())
    _MODEL = None
    if pkl_path.is_file():
        try:
            import pickle
            with open(pkl_path, "rb") as fh:
                _MODEL = pickle.load(fh)
        except Exception as exc:
            logger.warning("meta model pkl unloadable: %s", exc)
    return _MODEL, _MODEL_META


def meta_probability(feature_row: np.ndarray) -> Tuple[bool, float, str]:
    """Return (ok, probability, reason) for a single feature row."""
    model, meta = _load()
    if meta is None:
        return True, float("nan"), "meta model absent"
    if model is None:
        return True, float("nan"), "meta model weights unloadable"
    try:
        proba = float(model.predict_proba(np.asarray(feature_row, dtype=float).reshape(1, -1))[0, 1])
    except Exception as exc:
        return True, float("nan"), "meta model error: %s" % exc
    return True, proba, "meta p=%.3f" % proba


def gate_with_meta(feature_row: np.ndarray,
                   min_prob: float | None = None) -> Tuple[bool, str]:
    """Veto a confluence-passed signal when P(profitable) < threshold."""
    if min_prob is None:
        min_prob = float(os.getenv("META_MODEL_MIN_PROB", "0.5"))
    _, proba, reason = meta_probability(feature_row)
    if np.isnan(proba):
        return True, reason  # inert without a usable model
    if proba < min_prob:
        return False, "META_VETO: %s < min %.2f" % (reason, min_prob)
    return True, "meta ok (%s >= min %.2f)" % (reason, min_prob)
