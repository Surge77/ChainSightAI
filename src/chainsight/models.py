"""The classifiers, exactly as the course builds them.

Every entry is a `Pipeline` when the estimator needs scaling and a bare estimator when it
does not, following the cheatsheet's rule verbatim: distance and margin models need
`StandardScaler`, tree models do not, because a tree splits on thresholds and rescaling an
axis moves the threshold with it.

Two entries carry a row cap, and the cap is reported alongside their scores rather than
hidden. `SVC` is roughly quadratic in rows and `KNeighborsClassifier` does its work at
predict time against every training row; on 125,200 training rows neither finishes in a
usable time. Capping them and saying so is honest. Quietly dropping them, or quietly
training them on less data and printing the score next to models that saw everything, is
not.

The grids are deliberately small. `GridSearchCV` over time-ordered folds multiplies fits by
folds, and a grid that takes an hour is a grid nobody re-runs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import (
    AdaBoostClassifier,
    BaggingClassifier,
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    VotingClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from chainsight.encoding import Encoding

RANDOM_STATE = 42

#: `lbfgs` does not converge on this feature set within 1,000 iterations even scaled, and a
#: convergence warning on every fit trains a reader to ignore warnings.
LOGISTIC_ITERATIONS = 5000

#: `SVC` fit time grows about quadratically in rows. Measured: 0.5s at 5,000 rows.
SVC_MAX_ROWS = 5000

#: `KNeighborsClassifier` defers its work to predict time, against every training row.
KNN_MAX_ROWS = 20000

#: `BaggingClassifier` fits ten logistic regressions, so it inherits their cost ten times.
BAGGING_MAX_ROWS = 20000


def _scaled(model: Any) -> Pipeline:
    """The cheatsheet's own construction, names included."""
    return Pipeline([("Scaler", StandardScaler()), ("Model", model)])


def _logistic() -> LogisticRegression:
    return LogisticRegression(max_iter=LOGISTIC_ITERATIONS, random_state=RANDOM_STATE)


@dataclass(frozen=True)
class Candidate:
    """One model in the comparison, with its grid and its honest cost.

    `max_rows` is not an optimisation. It is a limitation, it changes what the score means,
    and `results.md` prints it in the same row as the score for that reason.
    """

    name: str
    build: Callable[[], Any]
    grid: dict[str, list[Any]] = field(default_factory=dict)
    max_rows: int | None = None
    note: str = ""
    #: Which feature space this candidate is fitted on. `codes` is the course's
    #: `LabelEncoder`; `one-hot` is declared in `scripts/check_taught.py`.
    encoding: Encoding = "codes"


CLASSIFIERS: tuple[Candidate, ...] = (
    Candidate(
        name="logistic regression",
        build=lambda: _scaled(_logistic()),
        grid={"Model__C": [0.1, 1.0, 10.0]},
    ),
    Candidate(
        name="naive bayes",
        build=lambda: _scaled(GaussianNB()),
    ),
    Candidate(
        name="k nearest neighbours",
        build=lambda: _scaled(KNeighborsClassifier(n_jobs=-1)),
        grid={"Model__n_neighbors": [11, 25, 51]},
        max_rows=KNN_MAX_ROWS,
        note="predicts against every training row, so the cost is at predict time",
    ),
    Candidate(
        name="support vector machine",
        build=lambda: _scaled(SVC(kernel="linear", random_state=RANDOM_STATE)),
        grid={"Model__C": [0.1, 1.0]},
        max_rows=SVC_MAX_ROWS,
        note="fit time grows about quadratically in rows",
    ),
    Candidate(
        name="decision tree",
        build=lambda: DecisionTreeClassifier(random_state=RANDOM_STATE),
        grid={"max_depth": [3, 5, 10, None]},
    ),
    Candidate(
        name="random forest",
        build=lambda: RandomForestClassifier(random_state=RANDOM_STATE, n_jobs=-1),
        grid={"n_estimators": [100], "max_depth": [5, 10, None]},
    ),
    Candidate(
        name="bagging logistic",
        build=lambda: BaggingClassifier(
            estimator=_logistic(), n_estimators=10, random_state=RANDOM_STATE, n_jobs=-1
        ),
        max_rows=BAGGING_MAX_ROWS,
        note="ten logistic regressions, so ten times their cost",
    ),
    Candidate(
        name="adaboost",
        build=lambda: AdaBoostClassifier(random_state=RANDOM_STATE),
        grid={"n_estimators": [50, 100]},
    ),
    Candidate(
        name="gradient boosting",
        build=lambda: GradientBoostingClassifier(random_state=RANDOM_STATE),
        grid={"n_estimators": [50, 100]},
    ),
    Candidate(
        name="voting",
        build=lambda: VotingClassifier(
            estimators=[
                ("logistic", _scaled(_logistic())),
                ("tree", DecisionTreeClassifier(max_depth=5, random_state=RANDOM_STATE)),
                (
                    "forest",
                    RandomForestClassifier(max_depth=10, random_state=RANDOM_STATE, n_jobs=-1),
                ),
            ],
            voting="soft",
        ),
        note="soft voting, so it averages probabilities rather than counting labels",
    ),
)


#: Candidates that reach outside the course material. Every name they use is declared in
#: `scripts/check_taught.py` with the measurement that justified it, and they are listed
#: separately here so the results table can say which side of the line each row sits on.
DECLARED_CLASSIFIERS: tuple[Candidate, ...] = (
    Candidate(
        name="one-hot logistic",
        build=lambda: _scaled(_logistic()),
        encoding="one-hot",
        note="the taught logistic, over a one-hot feature space instead of integer codes",
    ),
    Candidate(
        name="one-hot random forest",
        build=lambda: RandomForestClassifier(
            n_estimators=200, max_depth=12, random_state=RANDOM_STATE, n_jobs=-1
        ),
        encoding="one-hot",
        note="best measured ranking: 0.7518 ROC-AUC against the rule baseline's 0.7341",
    ),
    Candidate(
        name="hist gradient boosting",
        build=lambda: HistGradientBoostingClassifier(random_state=RANDOM_STATE, max_iter=300),
        note="the strongest learner available, included to test whether the ceiling is real",
    ),
    Candidate(
        name="calibrated hist gradient boosting",
        build=lambda: CalibratedClassifierCV(
            HistGradientBoostingClassifier(random_state=RANDOM_STATE, max_iter=300),
            method="isotonic",
            cv=3,
        ),
        note="isotonic recalibration, because the probability ordering was inverted",
    ),
)


def by_name(name: str) -> Candidate:
    for candidate in (*CLASSIFIERS, *DECLARED_CLASSIFIERS):
        if candidate.name == name:
            return candidate
    available = ", ".join(c.name for c in (*CLASSIFIERS, *DECLARED_CLASSIFIERS))
    raise KeyError(f"no classifier called {name!r}. Available: {available}")


def names() -> list[str]:
    return [candidate.name for candidate in (*CLASSIFIERS, *DECLARED_CLASSIFIERS)]


def is_declared(name: str) -> bool:
    """True when this candidate reaches outside the course material."""
    return any(candidate.name == name for candidate in DECLARED_CLASSIFIERS)
