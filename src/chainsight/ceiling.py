"""Is it the model, or is it the data?

When a regressor fails to beat its baseline there are two explanations, and they lead to
opposite next steps. Either the model class cannot reach the signal — in which case try a
different one — or there is no signal to reach, in which case trying another model is a
waste of an afternoon and the honest move is to say so.

This module answers that question by building a predictor that **cheats**. For a given
column it predicts each group's mean *taken from the test set itself*. No real model can do
better than that using only that column, because no real model gets to see the answers.

If the cheating predictor scores R² 0.002, then a column carrying "signal" in the sense of
a visible spread between group means carries no useful signal at all, and the failure of
every honest model is a property of the data.

The ceiling is deliberately optimistic in three ways at once — it fits on the evaluation
data, it uses the exact group means, and it is scored on the same rows it was built from.
That is the point. A generous upper bound that lands near zero is a much stronger statement
than a tight one.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from chainsight import evaluate

#: Below this many rows per group the oracle is memorising individual rows rather than
#: measuring what the columns are worth, and its score means nothing.
DEGENERATE_ROWS_PER_GROUP = 5.0


@dataclass(frozen=True)
class Ceiling:
    """The best an oracle could do on one target using only these columns."""

    columns: tuple[str, ...]
    groups: int
    rows: int
    scores: dict[str, float]

    @property
    def label(self) -> str:
        return " + ".join(self.columns)

    @property
    def rows_per_group(self) -> float:
        return self.rows / self.groups

    @property
    def is_degenerate(self) -> bool:
        """True when the groups are so fine that the oracle is just reading the answers.

        Combine enough columns and every row lands in a group of its own, at which point
        the oracle scores near 1.0 by memorising the target. That is not a ceiling on what
        the columns are worth, and reporting it as one would invert the whole argument.
        """
        return self.rows_per_group < DEGENERATE_ROWS_PER_GROUP


def oracle(frame: pd.DataFrame, target: str, columns: list[str]) -> Ceiling:
    """Predict each group's own mean, taken from the frame being scored.

    Unbeatable by any honest model restricted to the same columns, and therefore an upper
    bound on what those columns are worth.
    """
    grouped = frame.groupby(columns, observed=True)[target]
    predicted = grouped.transform("mean")
    return Ceiling(
        columns=tuple(columns),
        groups=int(grouped.ngroups),
        rows=len(frame),
        scores=evaluate.regression_scores(frame[target], predicted.to_numpy()),
    )


def survey(frame: pd.DataFrame, target: str, columns: list[str]) -> list[Ceiling]:
    """One ceiling per column, plus one for all of them together, worst first."""
    single = [oracle(frame, target, [column]) for column in columns]
    single.sort(key=lambda ceiling: ceiling.scores["r2"])
    return [*single, oracle(frame, target, columns)]


def table(ceilings: list[Ceiling]) -> str:
    """The survey, with the rows-per-group that says whether each ceiling means anything."""
    frame = pd.DataFrame(
        [
            {
                "columns": ceiling.label,
                "groups": ceiling.groups,
                "rows per group": round(ceiling.rows_per_group, 2),
                "oracle r2": round(ceiling.scores["r2"], 4),
                "oracle mae": round(ceiling.scores["mae"], 4),
                "meaningful": "no - memorising rows" if ceiling.is_degenerate else "yes",
            }
            for ceiling in ceilings
        ]
    ).set_index("columns")
    return evaluate.as_markdown(frame, corner="columns")
