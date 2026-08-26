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

from chainsight import (
    baselines,
    evaluate,
    features,
    models,
    regressors,
    schema,
    split,
    tuning,
)


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
    #: True when this row reaches outside the course material, so the table can say so.
    declared: bool = False

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
    # Both encodings are fitted once on the training slice, and each candidate is scored on
    # the one it declares. Fitting per candidate would re-learn the same mappings ten times.
    spaces = {
        encoding: features.FeatureSpace.fit(parts.train, encoding=encoding)
        for encoding in ("codes", "one-hot")
    }
    matrices = {
        encoding: (space.transform(parts.train), space.transform(parts.test))
        for encoding, space in spaces.items()
    }
    Y_train = parts.train[schema.LATE_TARGET]
    Y_test = parts.test[schema.LATE_TARGET]

    rule = baselines.GroupRate.fit(parts.train)
    rule_probabilities = rule.predict_proba(parts.test)
    results = [
        _baseline_result(
            "baseline: majority class",
            baselines.MajorityClass.fit(parts.train).predict(parts.test),
            Y_test,
            len(parts.train),
        ),
        _baseline_result(
            "baseline: shipping-mode rule",
            rule.predict(parts.test),
            Y_test,
            len(parts.train),
            probabilities=rule_probabilities,
            # Without this the models would be compared on a metric their baseline lacks.
            extra=evaluate.ranking_scores(Y_test, rule_probabilities),
        ),
    ]

    available = (*models.CLASSIFIERS, *models.DECLARED_CLASSIFIERS)
    wanted = available if only is None else [models.by_name(name) for name in only]
    for candidate in wanted:
        X_train, X_test = matrices[candidate.encoding]
        started = time.perf_counter()
        tuned = tuning.tune(candidate, X_train, Y_train)
        elapsed = time.perf_counter() - started

        probabilities = probabilities_of(tuned.estimator, X_test)
        scores = evaluate.classification_scores(Y_test, tuned.estimator.predict(X_test))
        if probabilities is not None:
            scores |= evaluate.ranking_scores(Y_test, probabilities)

        results.append(
            Result(
                name=candidate.name,
                scores=scores,
                parameters=tuned.parameters,
                seconds=elapsed,
                rows_used=tuned.rows_used,
                rows_available=tuned.rows_available,
                probabilities=probabilities,
                declared=models.is_declared(candidate.name),
            )
        )
    return results


def run_margin(frame: pd.DataFrame, *, only: list[str] | None = None) -> list[Result]:
    """The same shape of comparison for the margin target, against the mean baseline.

    `tuning.tune` scores folds on F1, which is meaningless for a regressor, so the margin
    candidates are fitted directly. They have small grids or none, and the finding recorded
    in `docs/results.md` is that none of them separates from the baseline at all -- tuning
    harder would be tuning something that is not there.
    """
    parts = split.by_date(frame)
    space = features.FeatureSpace.fit(parts.train)

    X_train, X_test = space.transform(parts.train), space.transform(parts.test)
    Y_train = parts.train[schema.MARGIN_TARGET]
    Y_test = parts.test[schema.MARGIN_TARGET]

    results = [
        Result(
            name="baseline: mean margin",
            scores=evaluate.regression_scores(
                Y_test, baselines.MeanValue.fit(parts.train).predict(parts.test)
            ),
            parameters={},
            seconds=0.0,
            rows_used=len(parts.train),
            rows_available=len(parts.train),
        )
    ]

    wanted = regressors.REGRESSORS if only is None else [regressors.by_name(n) for n in only]
    for candidate in wanted:
        started = time.perf_counter()
        estimator = candidate.build()
        estimator.fit(X_train, Y_train)
        results.append(
            Result(
                name=candidate.name,
                scores=evaluate.regression_scores(Y_test, estimator.predict(X_test)),
                parameters={},
                seconds=time.perf_counter() - started,
                rows_used=len(X_train),
                rows_available=len(X_train),
            )
        )
    return results


def margin_table(results: list[Result]) -> str:
    """Sorted by MAE, lowest first, because MAE is the one that can be said out loud."""
    frame = pd.DataFrame(
        [
            {
                "model": result.name,
                **{key: round(value, 4) for key, value in result.scores.items()},
                "fit (s)": round(result.seconds, 1),
            }
            for result in results
        ]
    ).sort_values("mae")
    return evaluate.as_markdown(frame.set_index("model"), corner="model")


def beats_the_mean(results: list[Result]) -> list[str]:
    """Names of margin models with a lower MAE than predicting the training mean."""
    bar = next(r.scores["mae"] for r in results if r.name == "baseline: mean margin")
    return [
        result.name
        for result in results
        if not result.name.startswith("baseline: ") and result.scores["mae"] < bar
    ]


def _baseline_result(
    name: str,
    predicted: np.ndarray,
    Y_test: pd.Series,
    rows: int,
    probabilities: np.ndarray | None = None,
    extra: dict[str, float] | None = None,
) -> Result:
    return Result(
        name=name,
        scores=evaluate.classification_scores(Y_test, predicted) | (extra or {}),
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
                "tier": "declared" if result.declared else "course",
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
