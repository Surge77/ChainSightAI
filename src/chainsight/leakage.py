"""Train the same model twice and print what the forbidden columns are worth.

This is the module the project exists to justify. Published notebooks on the DataCo table
report accuracy around 0.98 on `Late_delivery_risk`. That number is not a model; it is
`Delivery Status` spelling the answer out in English. Asserting so in a README is cheap.
Training the identical estimator on both feature sets and printing the two numbers next to
each other is not, and it is the only version anybody should believe.

Three comparisons, each isolating one thing:

**Delivery leak** — the same decision tree, once with the post-dispatch columns and once
without. The headline.

**Margin leak** — the same linear model, in three feature sets. The delivery leak is well
known; this one is usually missed, and it is worse, because it produces a number that reads
as success. It is also the more interesting of the two, because how much it is worth
depends on the model class: `LinearRegression` cannot divide, so handing it the profit
column alone recovers only part of the target. Hand it one ratio as well and it recovers
the target outright.

**Split leak** — honest features, scored on a chronological split and on a shuffled one.
Included because the expected result is that it barely matters on this table, and a
demonstration that lands where nobody expects is worth more than one confirming a slogan.

Every estimator is the cheatsheet's own: `DecisionTreeClassifier(max_depth=5)` and
`LinearRegression`. Depth is capped so the honest run cannot be dismissed as an
under-trained straw man set up to lose.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.tree import DecisionTreeClassifier

from chainsight import evaluate, features, ingest, schema, split
from chainsight.encoding import CategoryCodes

#: Post-dispatch columns that give away the delivery outcome. `Days for shipping (real)`
#: compared against the scheduled days *is* the label; `Delivery Status` says it in words.
DELIVERY_LEAKS: tuple[str, ...] = (
    "Days for shipping (real)",
    "Delivery Status",
    "Order Status",
)

#: `Order Profit Per Order` is the margin target multiplied by a column we legitimately
#: keep, and `Benefit per order` is byte-identical to it.
MARGIN_LEAKS: tuple[str, ...] = (
    "Order Profit Per Order",
    "Benefit per order",
)

#: The cheatsheet's own tree, depth-capped so neither run can be called under-trained.
TREE_DEPTH = 5
RANDOM_STATE = 42

_HONEST = "honest"


@dataclass(frozen=True)
class Comparison:
    """Runs that differ in exactly one thing, and the question they answer."""

    question: str
    rows: dict[str, dict[str, float]]
    note: str = ""

    def table(self) -> str:
        return evaluate.as_table(self.rows)

    def render(self) -> str:
        parts = [f"### {self.question}", "", self.table()]
        if self.note:
            parts += ["", self.note]
        return "\n".join(parts)


def _raw_and_ingested(source: pd.DataFrame | str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The source table and its ingested form, sharing a row index.

    `ingest` drops columns but never rows here, so a positional reset on the way in lets
    the leak columns be reattached by index afterwards. Doing this anywhere but in this
    module would be the bug the whole project is about.
    """
    raw = (ingest.read_raw(source) if isinstance(source, str) else source).reset_index(drop=True)
    return raw, ingest.ingest(raw)


def _is_text(column: pd.Series) -> bool:
    return not pd.api.types.is_numeric_dtype(column)


def delivery_leak(source: pd.DataFrame | str) -> Comparison:
    """The headline: what the post-dispatch columns are worth on the delivery target."""
    raw, honest = _raw_and_ingested(source)
    carried = honest.assign(**{name: raw[name] for name in DELIVERY_LEAKS})
    parts = split.by_date(carried)

    space = features.FeatureSpace.fit(parts.train)
    categorical = [name for name in DELIVERY_LEAKS if _is_text(raw[name])]
    numeric = [name for name in DELIVERY_LEAKS if name not in categorical]
    codes = CategoryCodes.fit(parts.train, categorical)

    def matrix(part: pd.DataFrame) -> pd.DataFrame:
        extra = pd.concat([codes.transform(part), part.loc[:, numeric]], axis=1)
        return pd.concat([space.transform(part), extra], axis=1)

    truth = parts.test[schema.LATE_TARGET]
    labels = parts.train[schema.LATE_TARGET]
    return Comparison(
        question="Will this order be delivered late?",
        rows={
            "with post-dispatch columns": _score_tree(
                matrix(parts.train), labels, matrix(parts.test), truth
            ),
            _HONEST: _score_tree(
                space.transform(parts.train), labels, space.transform(parts.test), truth
            ),
        },
        note=(
            "The leaked run does not merely score well, it scores perfectly. A depth-5 tree "
            "needs one split on `Delivery Status` and it is finished."
        ),
    )


def margin_leak(source: pd.DataFrame | str) -> Comparison:
    """The leak usually missed, and the reason its size depends on the model class."""
    raw, honest = _raw_and_ingested(source)
    carried = honest.assign(**{name: raw[name] for name in MARGIN_LEAKS})
    parts = split.by_date(carried)
    space = features.FeatureSpace.fit(parts.train)

    def matrix(part: pd.DataFrame, *, with_ratio: bool) -> pd.DataFrame:
        built = space.transform(part).copy()
        for name in MARGIN_LEAKS:
            built[name] = part[name].to_numpy()
        if with_ratio:
            built["profit over total"] = (
                part["Order Profit Per Order"] / part[schema.ORDER_VALUE]
            ).to_numpy()
        return built

    truth = parts.test[schema.MARGIN_TARGET]
    values = parts.train[schema.MARGIN_TARGET]
    return Comparison(
        question="What margin should we expect on this order?",
        rows={
            "with the profit column": _score_linear(
                matrix(parts.train, with_ratio=False),
                values,
                matrix(parts.test, with_ratio=False),
                truth,
            ),
            "with the profit column and one division": _score_linear(
                matrix(parts.train, with_ratio=True),
                values,
                matrix(parts.test, with_ratio=True),
                truth,
            ),
            _HONEST: _score_linear(
                space.transform(parts.train), values, space.transform(parts.test), truth
            ),
        },
        note=(
            "The middle row is the whole argument. `Order Profit Per Order` divided by "
            "`Order Item Total` *is* the target, so a feature set containing both recovers "
            "it outright. It is not exact only because the publisher rounds the ratio to "
            "two decimals. A linear model cannot perform that division for itself, which is "
            "why the first row looks like a mediocre model rather than an alarm."
        ),
    )


def split_leak(source: pd.DataFrame | str) -> Comparison:
    """Honest features, scored two ways. Expected to be a small difference on this table."""
    _, honest = _raw_and_ingested(source)

    scores: dict[str, dict[str, float]] = {}
    for label, parts in (
        ("shuffled split", split.at_random(honest)),
        (_HONEST, split.by_date(honest)),
    ):
        space = features.FeatureSpace.fit(parts.train)
        scores[label] = _score_tree(
            space.transform(parts.train),
            parts.train[schema.LATE_TARGET],
            space.transform(parts.test),
            parts.test[schema.LATE_TARGET],
        )
    return Comparison(
        question="Does the shuffled split flatter the model?",
        rows=scores,
        note=(
            "No, and on this table it does not even help. The late rate moves by less than "
            "a point across 2015, 2016 and 2017, so there is almost nothing for a shuffle "
            "to smuggle across the boundary. The chronological split is still the one "
            "reported, because it is the one that matches the question being asked."
        ),
    )


def _score_tree(
    X_train: pd.DataFrame, Y_train: pd.Series, X_test: pd.DataFrame, Y_test: pd.Series
) -> dict[str, float]:
    model = DecisionTreeClassifier(max_depth=TREE_DEPTH, random_state=RANDOM_STATE)
    model.fit(X_train, Y_train)
    return evaluate.classification_scores(Y_test, model.predict(X_test))


def _score_linear(
    X_train: pd.DataFrame, Y_train: pd.Series, X_test: pd.DataFrame, Y_test: pd.Series
) -> dict[str, float]:
    model = LinearRegression()
    model.fit(X_train, Y_train)
    return evaluate.regression_scores(Y_test, model.predict(X_test))


def report(source: pd.DataFrame | str) -> str:
    """All three comparisons, rendered. Printed by `chainsight leakage`."""
    comparisons = (delivery_leak(source), margin_leak(source), split_leak(source))
    return "\n\n".join(comparison.render() for comparison in comparisons)
