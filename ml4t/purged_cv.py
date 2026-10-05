"""Purged walk-forward splits for financial CV (no train/test leakage)."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterator, List, Tuple
import numpy as np


@dataclass(frozen=True)
class PurgedSplit:
    train: np.ndarray; test: np.ndarray


def purged_walk_forward(n: int, n_splits: int = 4, embargo_pct: float = 0.01,
                        min_train: int = 500) -> List[PurgedSplit]:
    """Chronological folds; each test block excludes neighbours by embargo."""
    bounds = np.array_split(np.arange(n), n_splits)
    out: List[PurgedSplit] = []
    for k in range(1, n_splits):
        test = bounds[k]
        embargo = max(1, int(len(test) * embargo_pct) + 1)
        train = np.concatenate(bounds[:k])
        train = train[train < test[0] - embargo]
        if len(train) >= min_train and len(test) > 0:
            out.append(PurgedSplit(train=train, test=test))
    return out


def iter_purged(n: int, n_splits: int = 4,
                embargo_pct: float = 0.01) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
    for s in purged_walk_forward(n, n_splits, embargo_pct):
        yield s.train, s.test
