"""`GridSearchCV`, over folds that respect time.

The cheatsheet's grid search uses `cv=5`, which shuffles. Inside a training slice that is
already ordered by date, shuffling reintroduces on a small scale exactly what the
chronological split removed on a large one: a fold trained on June and scored on March.

So the folds are expanding windows. Fold *k* trains on everything before a cut and scores
the block immediately after it:

    fold 1   train [........]  score [....]
    fold 2   train [............]  score [....]
    fold 3   train [................]  score [....]

Nothing after a fold's scoring block is ever in its training set. `GridSearchCV` accepts an
iterable of index pairs, so this needs no machinery beyond a list.

The search scores on F1 rather than accuracy. `docs/results.md` shows why: the
majority-class baseline scores 0.7106 F1 for free, so F1 is the binding constraint and
accuracy is the one already almost satisfied by a one-line rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import GridSearchCV

from chainsight.models import Candidate

#: Enough folds to see variance, few enough that a grid finishes in minutes.
FOLDS = 4

#: F1, because the majority-class baseline already scores 0.7106 of it for nothing.
SCORING = "f1"


def expanding_folds(n_rows: int, folds: int = FOLDS) -> list[tuple[np.ndarray, np.ndarray]]:
    """Index pairs where every scoring block sits strictly after its own training block.

    The first block is held back as the first fold's training data, so `folds` folds need
    `folds + 1` blocks.
    """
    if n_rows < folds + 1:
        raise ValueError(f"{n_rows} rows cannot make {folds} expanding folds")

    edges = np.linspace(0, n_rows, folds + 2, dtype=int)
    return [
        (np.arange(0, edges[index + 1]), np.arange(edges[index + 1], edges[index + 2]))
        for index in range(folds)
    ]


@dataclass(frozen=True)
class Tuned:
    """A fitted estimator, what was searched to get it, and on how many rows."""

    name: str
    estimator: Any
    parameters: dict[str, Any]
    fold_score: float
    rows_used: int
    rows_available: int

    @property
    def was_capped(self) -> bool:
        return self.rows_used < self.rows_available


def tune(
    candidate: Candidate,
    X_train: pd.DataFrame,
    Y_train: pd.Series,
    *,
    folds: int = FOLDS,
) -> Tuned:
    """Grid-search one candidate over expanding folds and refit it on everything it may see.

    A candidate with an empty grid is still fitted through the same path, so the row cap,
    the fold score and the refit happen identically whether or not there is anything to
    search. One path is easier to trust than two.
    """
    available = len(X_train)
    rows = min(available, candidate.max_rows) if candidate.max_rows else available
    # The *most recent* rows the candidate may see, not the oldest. Both respect the
    # chronology; taking the tail keeps the training window adjacent to the period being
    # predicted, which is the half of the data a capped model most needs.
    X_used, Y_used = X_train.iloc[-rows:], Y_train.iloc[-rows:]

    search = GridSearchCV(
        candidate.build(),
        candidate.grid,
        cv=expanding_folds(rows, folds),
        scoring=SCORING,
        n_jobs=1,
        refit=True,
    )
    search.fit(X_used, Y_used)

    return Tuned(
        name=candidate.name,
        estimator=search.best_estimator_,
        parameters=dict(search.best_params_),
        fold_score=float(search.best_score_),
        rows_used=rows,
        rows_available=available,
    )
