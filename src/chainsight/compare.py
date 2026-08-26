"""Run every classifier against the same split and the same baselines, and rank them.

One function does the whole comparison, because a comparison assembled differently for each
model is not a comparison. Every candidate sees the identical feature space, fitted on the
identical training slice, and is scored on the identical held-out orders.

The baselines are included as rows rather than mentioned in prose underneath. A model that
does not beat a one-line rule should have to sit next to it in the table.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from chainsight import baselines, evaluate, features, models, schema, split, tuning


@dataclass(frozen=True)
class Result:
    """One row of the comparison."""

    name: str
    scores: dict[str, float]
    parameters: dict[str, object]
    seconds: float
    rows_used: int
    rows_available: int
    probabilities: np.ndarray | None = None

    @property
    def was_capped(self) -> bool:
        return self.rows_used < self.rows_available


def probabilities_of(estimator: object, X: pd.DataFrame) -> np.ndarray | None:
    """The late-class probability, when the estimator offers one.

    `SVC` without `probability=True` does not, and turning it on refits the model five more
    times internally. A missing probability is reported as missing rather than faked from a
    decision function, because the decision engine would multiply a fake by money.
    """
    predict_proba = getattr(estimator, "predict_proba", None)
    if predict_proba is None:
        return None
    return np.asarray(predict_proba(X))[:, 1]


def run(
    frame: pd.DataFrame,
    *,
    only: list[str] | None = None,
) -> list[Result]:
    """Fit, tune and score every candidate on one chronological split."""
    parts = split.by_date(frame)
    space = features.FeatureSpace.fit(parts.train)

    X_train = space.transform(parts.train)
    X_test = space.transform(parts.test)
    Y_train = parts.train[schema.LATE_TARGET]
    Y_test = parts.test[schema.LATE_TARGET]

    results = [
        _baseline_result(
            "baseline: majority class",
            baselines.MajorityClass.fit(parts.train).predict(parts.test),
            Y_test,
            len(parts.train),
        ),
        _baseline_result(
            "baseline: shipping-mode rule",
            baselines.GroupRate.fit(parts.train).predict(parts.test),
            Y_test,
            len(parts.train),
            probabilities=baselines.GroupRate.fit(parts.train).predict_proba(parts.test),
        ),
    ]

    wanted = models.CLASSIFIERS if only is None else [models.by_name(name) for name in only]
    for candidate in wanted:
        started = time.perf_counter()
        tuned = tuning.tune(candidate, X_train, Y_train)
        elapsed = time.perf_counter() - started

        results.append(
            Result(
                name=candidate.name,
                scores=evaluate.classification_scores(Y_test, tuned.estimator.predict(X_test)),
                parameters=tuned.parameters,
                seconds=elapsed,
                rows_used=tuned.rows_used,
                rows_available=tuned.rows_available,
                probabilities=probabilities_of(tuned.estimator, X_test),
            )
        )
    return results


def _baseline_result(
    name: str,
    predicted: np.ndarray,
    Y_test: pd.Series,
    rows: int,
    probabilities: np.ndarray | None = None,
) -> Result:
    return Result(
        name=name,
        scores=evaluate.classification_scores(Y_test, predicted),
        parameters={},
        seconds=0.0,
        rows_used=rows,
        rows_available=rows,
        probabilities=probabilities,
    )


def table(results: list[Result]) -> str:
    """The comparison, sorted by F1, with the row cap and the fit time in the same row."""
    frame = pd.DataFrame(
        [
            {
                "model": result.name,
                **{key: round(value, 4) for key, value in result.scores.items()},
                "fit (s)": round(result.seconds, 1),
                "trained on": (
                    f"{result.rows_used:,} of {result.rows_available:,}"
                    if result.was_capped
                    else f"{result.rows_used:,}"
                ),
            }
            for result in results
        ]
    ).sort_values("f1", ascending=False)
    return evaluate.as_markdown(frame.set_index("model"), corner="model")


def clears_both_baselines(results: list[Result]) -> list[str]:
    """Names of models beating the rule on accuracy and the majority class on F1 at once.

    Neither baseline alone is a bar. The majority class buys F1 0.7106 with recall of 1.0
    for free; the shipping-mode rule buys accuracy 0.6956 with four lines of pandas. Only
    clearing both at the same time means anything.
    """
    by_name = {result.name: result.scores for result in results}
    accuracy_bar = by_name["baseline: shipping-mode rule"]["accuracy"]
    f1_bar = by_name["baseline: majority class"]["f1"]

    return [
        result.name
        for result in results
        if not result.name.startswith("baseline: ")
        and result.scores["accuracy"] > accuracy_bar
        and result.scores["f1"] > f1_bar
    ]
