"""One-hot encoding, ranking metrics, and the models that reach outside the course material.

Each addition here had to earn its place against a measurement, and these tests assert the
properties those measurements relied on rather than re-running the measurements themselves.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from chainsight import compare, encoding, evaluate, features, ingest, models, schema, split
from chainsight.encoding import Encoding

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_orders.csv"


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return ingest.ingest(SAMPLE)


class TestOneHotColumns:
    def test_it_makes_one_indicator_per_frequent_category(self) -> None:
        frame = pd.DataFrame({"mode": (["a"] * 60) + (["b"] * 60)})

        encoded = encoding.OneHotColumns.fit(frame, ["mode"]).transform(frame)

        assert encoded.shape[1] == 2
        assert set(encoded.iloc[0]) == {0.0, 1.0}

    def test_rare_categories_are_folded_together_rather_than_each_getting_a_column(self) -> None:
        """`Order Country` has 164 levels, several appearing a handful of times in three years."""
        frame = pd.DataFrame({"country": (["common"] * 200) + ["rare one", "rare two"]})

        encoder = encoding.OneHotColumns.fit(frame, ["country"])

        assert len(encoder.columns) < 3

    def test_an_unseen_category_produces_a_row_rather_than_an_exception(self) -> None:
        """Same problem `UNSEEN` solves for the codes: the catalogue turns over yearly."""
        trained = pd.DataFrame({"mode": (["a"] * 60) + (["b"] * 60)})
        encoder = encoding.OneHotColumns.fit(trained, ["mode"])

        served = encoder.transform(pd.DataFrame({"mode": ["drone"]}))

        assert len(served) == 1

    def test_a_missing_encoded_column_is_named(self) -> None:
        frame = pd.DataFrame({"mode": ["a"] * 60})
        encoder = encoding.OneHotColumns.fit(frame, ["mode"])

        with pytest.raises(KeyError, match="mode"):
            encoder.transform(pd.DataFrame({"other": [1]}))

    def test_it_produces_the_same_columns_for_training_and_serving(
        self, frame: pd.DataFrame
    ) -> None:
        encoder = encoding.OneHotColumns.fit(frame, list(features.CATEGORICAL))

        trained = encoder.transform(frame)
        served = encoder.transform(frame.head(1))

        assert list(served.columns) == list(trained.columns)


class TestFeatureSpaceEncodings:
    def test_the_default_is_the_course_encoder(self, frame: pd.DataFrame) -> None:
        assert features.FeatureSpace.fit(frame).encoding == "codes"

    def test_one_hot_produces_a_wider_matrix_than_integer_codes(self, frame: pd.DataFrame) -> None:
        codes = features.FeatureSpace.fit(frame, encoding="codes")
        one_hot = features.FeatureSpace.fit(frame, encoding="one-hot")

        assert len(one_hot.columns) > len(codes.columns)

    def test_both_encodings_keep_the_numeric_and_derived_columns(self, frame: pd.DataFrame) -> None:
        for how in ("codes", "one-hot"):
            columns = set(features.FeatureSpace.fit(frame, encoding=how).columns)

            assert set(features.NUMERIC) <= columns
            assert "order_is_weekend" in columns

    def test_a_single_order_matches_training_under_one_hot_too(self, frame: pd.DataFrame) -> None:
        """The invariant that matters for serving, asserted for the second encoder as well."""
        space = features.FeatureSpace.fit(frame, encoding="one-hot")
        fields = {name: frame.iloc[0][name] for name in features.ORDER_FIELDS}

        served = space.transform(features.single_order(**fields))

        assert list(served.columns) == list(space.columns)

    def test_no_target_reaches_either_feature_matrix(self, frame: pd.DataFrame) -> None:
        for how in ("codes", "one-hot"):
            built = features.FeatureSpace.fit(frame, encoding=how).transform(frame)

            assert set(built.columns) & set(schema.targets()) == set()


class TestRankingScores:
    def test_a_perfect_ranking_scores_one(self) -> None:
        truth = pd.Series([0, 0, 1, 1])

        scores = evaluate.ranking_scores(truth, np.array([0.1, 0.2, 0.8, 0.9]))

        assert scores["roc auc"] == pytest.approx(1.0)
        assert scores["avg precision"] == pytest.approx(1.0)

    def test_a_reversed_ranking_scores_zero_auc(self) -> None:
        truth = pd.Series([0, 0, 1, 1])

        scores = evaluate.ranking_scores(truth, np.array([0.9, 0.8, 0.2, 0.1]))

        assert scores["roc auc"] == pytest.approx(0.0)

    def test_ranking_ignores_the_threshold_that_accuracy_depends_on(self) -> None:
        """The reason it was added: every model scored alike on accuracy and differed here."""
        truth = pd.Series([0, 0, 1, 1])
        confident = np.array([0.01, 0.02, 0.98, 0.99])
        timid = np.array([0.49, 0.49, 0.51, 0.51])

        assert evaluate.ranking_scores(truth, confident) == evaluate.ranking_scores(truth, timid)


class TestDeclaredCandidates:
    def test_every_declared_candidate_says_why_it_exists(self) -> None:
        for candidate in models.DECLARED_CLASSIFIERS:
            assert candidate.note, f"{candidate.name} reaches outside the course without a reason"

    def test_declared_candidates_are_reported_as_declared(self) -> None:
        for candidate in models.DECLARED_CLASSIFIERS:
            assert models.is_declared(candidate.name)

    def test_course_candidates_are_not(self) -> None:
        for candidate in models.CLASSIFIERS:
            assert not models.is_declared(candidate.name)

    def test_the_one_hot_candidates_ask_for_the_one_hot_feature_space(self) -> None:
        for name in ("one-hot logistic", "one-hot random forest"):
            assert models.by_name(name).encoding == "one-hot"

    def test_the_course_candidates_stay_on_the_course_encoder(self) -> None:
        for candidate in models.CLASSIFIERS:
            assert candidate.encoding == "codes"


def test_the_comparison_labels_which_side_of_the_line_each_row_sits_on(
    frame: pd.DataFrame,
) -> None:
    results = compare.run(frame, only=["naive bayes", "one-hot logistic"])

    rendered = compare.table(results)
    assert "declared" in rendered
    assert "course" in rendered


def test_a_model_without_probabilities_shows_a_dash_rather_than_nan(
    frame: pd.DataFrame,
) -> None:
    """`SVC` has no `predict_proba`, and `nan` in a results table reads as a bug."""
    results = compare.run(frame, only=["support vector machine"])

    assert "nan" not in compare.table(results)


def test_the_rule_baseline_is_given_a_ranking_score_too(frame: pd.DataFrame) -> None:
    """Otherwise the models would be compared on a metric the baseline does not have."""
    results = compare.run(frame, only=["naive bayes"])
    rule = next(r for r in results if r.name == "baseline: shipping-mode rule")

    assert "roc auc" in rule.scores


def _logistic_probabilities(
    frame: pd.DataFrame, how: Encoding
) -> tuple[np.ndarray, pd.Series, int]:
    parts = split.by_date(frame)
    space = features.FeatureSpace.fit(parts.train, encoding=how)
    model = models.by_name("logistic regression").build()
    model.fit(space.transform(parts.train), parts.train[schema.LATE_TARGET])
    probabilities = model.predict_proba(space.transform(parts.test))[:, 1]
    return probabilities, parts.test[schema.LATE_TARGET], len(space.columns)


def test_one_hot_ranks_better_than_integer_codes(frame: pd.DataFrame) -> None:
    """Half of the measurement that justified declaring `OneHotEncoder`, and the half that
    survives on 347 training rows.

    Full table: ROC-AUC 0.7449 against 0.7346. Here: 0.6569 against 0.6481. Smaller, same
    direction, and it is the ranking that the product depends on.
    """
    ranked = {}
    for how in ("codes", "one-hot"):
        probabilities, truth, _ = _logistic_probabilities(frame, how)
        ranked[how] = evaluate.ranking_scores(truth, probabilities)["roc auc"]

    assert ranked["one-hot"] > ranked["codes"]


def test_the_calibration_half_of_that_claim_needs_more_rows_than_the_slice_has(
    frame: pd.DataFrame,
) -> None:
    """The other half, and an honest note about where it does and does not hold.

    On the full 125,200-row training slice one-hot cuts the worst calibration gap from
    0.334 to 0.074. On these 347 rows it makes calibration *worse* -- 0.67 against 0.51 --
    because 44 columns over 347 rows is a different problem from 44 columns over 125,200.

    The test asserts the cause rather than the effect, so the claim in `docs/results.md`
    stays attached to the dataset size it was measured at instead of quietly becoming a
    universal one.
    """
    parts = split.by_date(frame)
    _, _, columns = _logistic_probabilities(frame, "one-hot")

    rows_per_column = len(parts.train) / columns

    assert rows_per_column < 20, "the slice has grown; recheck whether the claim now holds here"
