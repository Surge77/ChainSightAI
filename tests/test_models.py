"""The registry, the folds, and the comparison that puts models next to baselines.

The fold tests are the important ones. A shuffled fold inside an ordered training slice
reintroduces on a small scale exactly what the chronological split removed on a large one,
and it does it silently — the only symptom is a better number.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.pipeline import Pipeline

from chainsight import compare, evaluate, features, ingest, models, schema, split, tuning

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_orders.csv"

#: Fast candidates, so the suite stays runnable. The slow ones are covered by their metadata.
QUICK = ["logistic regression", "naive bayes", "decision tree"]


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return ingest.ingest(SAMPLE)


@pytest.fixture(scope="module")
def matrices(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    parts = split.by_date(frame)
    space = features.FeatureSpace.fit(parts.train)
    return space.transform(parts.train), parts.train[schema.LATE_TARGET]


class TestRegistry:
    def test_every_candidate_has_a_unique_name(self) -> None:
        assert len(models.names()) == len(set(models.names()))

    def test_an_unknown_name_lists_what_is_available(self) -> None:
        with pytest.raises(KeyError, match="logistic regression"):
            models.by_name("xgboost")

    @pytest.mark.parametrize(
        "name", ["logistic regression", "k nearest neighbours", "support vector machine"]
    )
    def test_distance_and_margin_models_are_scaled(self, name: str) -> None:
        """The cheatsheet's rule: KNN, SVM and logistic need a scaler; trees do not."""
        built = models.by_name(name).build()

        assert isinstance(built, Pipeline)
        assert "Scaler" in dict(built.named_steps)

    @pytest.mark.parametrize("name", ["decision tree", "random forest"])
    def test_tree_models_are_not_scaled(self, name: str) -> None:
        """Rescaling an axis moves the threshold with it, so the split is identical."""
        assert not isinstance(models.by_name(name).build(), Pipeline)

    def test_every_grid_key_addresses_a_real_parameter(self) -> None:
        for candidate in models.CLASSIFIERS:
            available = candidate.build().get_params()
            for key in candidate.grid:
                assert key in available, f"{candidate.name} has no parameter {key}"

    def test_capped_candidates_explain_why_they_are_capped(self) -> None:
        """A cap changes what the score means, so it may not be silent."""
        for candidate in models.CLASSIFIERS:
            if candidate.max_rows is not None:
                assert candidate.note, f"{candidate.name} is capped without saying why"


class TestExpandingFolds:
    def test_no_fold_trains_on_anything_after_what_it_scores(self) -> None:
        """The whole reason these exist instead of `cv=4`."""
        for train_index, score_index in tuning.expanding_folds(100, folds=4):
            assert train_index.max() < score_index.min()

    def test_each_fold_trains_on_more_than_the_last(self) -> None:
        sizes = [len(train) for train, _ in tuning.expanding_folds(100, folds=4)]

        assert sizes == sorted(sizes)
        assert len(set(sizes)) == len(sizes)

    def test_the_scoring_blocks_do_not_overlap(self) -> None:
        blocks = [set(score.tolist()) for _, score in tuning.expanding_folds(100, folds=4)]

        for earlier, later in pairwise(blocks):
            assert earlier & later == set()

    def test_it_makes_the_number_of_folds_asked_for(self) -> None:
        assert len(tuning.expanding_folds(100, folds=3)) == 3

    def test_too_few_rows_to_fold_is_an_error_naming_the_shortfall(self) -> None:
        with pytest.raises(ValueError, match="expanding folds"):
            tuning.expanding_folds(3, folds=4)


class TestTuning:
    def test_it_returns_a_fitted_estimator(self, matrices: tuple[pd.DataFrame, pd.Series]) -> None:
        X, Y = matrices

        tuned = tuning.tune(models.by_name("naive bayes"), X, Y, folds=2)

        assert tuned.estimator.predict(X.head(5)).shape == (5,)

    def test_a_candidate_with_no_grid_still_goes_through_the_same_path(
        self, matrices: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        X, Y = matrices

        tuned = tuning.tune(models.by_name("naive bayes"), X, Y, folds=2)

        assert tuned.parameters == {}
        assert tuned.rows_used == len(X)

    def test_a_capped_candidate_uses_the_most_recent_rows_not_the_oldest(
        self, matrices: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        """Both respect the chronology; the tail is adjacent to the period being predicted."""
        X, Y = matrices
        capped = models.Candidate(
            name="capped", build=models.by_name("naive bayes").build, max_rows=40, note="test"
        )

        tuned = tuning.tune(capped, X, Y, folds=2)

        assert tuned.rows_used == 40
        assert tuned.was_capped

    def test_an_uncapped_candidate_is_not_reported_as_capped(
        self, matrices: tuple[pd.DataFrame, pd.Series]
    ) -> None:
        X, Y = matrices

        assert not tuning.tune(models.by_name("naive bayes"), X, Y, folds=2).was_capped


@pytest.fixture(scope="module")
def results(frame: pd.DataFrame) -> list[compare.Result]:
    return compare.run(frame, only=QUICK)


class TestCompare:
    def test_the_baselines_are_rows_in_the_table_not_a_footnote(
        self, results: list[compare.Result]
    ) -> None:
        names = {result.name for result in results}

        assert "baseline: majority class" in names
        assert "baseline: shipping-mode rule" in names

    def test_every_requested_model_appears(self, results: list[compare.Result]) -> None:
        names = {result.name for result in results}

        assert set(QUICK) <= names

    def test_the_table_is_sorted_by_f1(self, results: list[compare.Result]) -> None:
        rendered = compare.table(results)
        ordered = sorted(results, key=lambda result: result.scores["f1"], reverse=True)

        positions = [rendered.index(f"| {result.name} |") for result in ordered]
        assert positions == sorted(positions)

    def test_the_table_reports_the_cap_in_the_same_row_as_the_score(
        self, results: list[compare.Result]
    ) -> None:
        """A cap changes what a score means, so it travels with the score, not a footnote."""
        capped = compare.Result(
            name="capped model",
            scores={"accuracy": 0.5, "precision": 0.5, "recall": 0.5, "f1": 0.5},
            parameters={},
            seconds=1.0,
            rows_used=5_000,
            rows_available=125_200,
        )

        rendered = compare.table([*results, capped])

        assert "5,000 of 125,200" in rendered

    def test_clearing_the_bar_requires_beating_both_baselines_at_once(
        self, results: list[compare.Result]
    ) -> None:
        """Neither baseline alone is a bar: one buys recall 1.0, the other buys accuracy."""
        winners = compare.clears_both_baselines(results)
        by_name = {result.name: result.scores for result in results}

        for name in winners:
            assert by_name[name]["accuracy"] > by_name["baseline: shipping-mode rule"]["accuracy"]
            assert by_name[name]["f1"] > by_name["baseline: majority class"]["f1"]

    def test_a_baseline_is_never_counted_as_clearing_the_bar(
        self, results: list[compare.Result]
    ) -> None:
        assert not any(
            name.startswith("baseline: ") for name in compare.clears_both_baselines(results)
        )


def test_a_model_without_predict_proba_reports_no_probability_rather_than_faking_one() -> None:
    """`SVC` has no probability unless asked, and a fake would be multiplied by money."""

    class NoProbability:
        pass

    assert compare.probabilities_of(NoProbability(), pd.DataFrame({"a": [1]})) is None


class TestThresholdSweep:
    def test_lowering_the_threshold_never_lowers_recall(self) -> None:
        truth = pd.Series([1, 0, 1, 1, 0, 1])
        probabilities = np.array([0.9, 0.1, 0.6, 0.45, 0.3, 0.35])

        sweep = evaluate.threshold_sweep(truth, probabilities)

        assert sweep["recall"].is_monotonic_decreasing

    def test_it_reports_how_many_orders_each_threshold_flags(self) -> None:
        """The column that turns a metric into an operational decision."""
        truth = pd.Series([1, 0, 1])
        probabilities = np.array([0.9, 0.1, 0.6])

        sweep = evaluate.threshold_sweep(truth, probabilities, steps=(0.5, 0.8))

        flagged = sweep["flagged"]
        assert flagged.loc[0.5] == 2
        assert flagged.loc[0.8] == 1


class TestReliability:
    def test_a_perfectly_calibrated_model_shows_no_gap(self) -> None:
        truth = pd.Series([1] * 90 + [0] * 10)
        probabilities = np.full(100, 0.9)

        table = evaluate.reliability(truth, probabilities)

        assert table["gap"].abs().max() < 0.01

    def test_an_overconfident_model_shows_a_positive_gap(self) -> None:
        """Says 0.9, delivers 0.5. The decision engine would multiply that error by money."""
        truth = pd.Series([1] * 50 + [0] * 50)
        probabilities = np.full(100, 0.9)

        table = evaluate.reliability(truth, probabilities)

        assert table["gap"].iloc[0] > 0.35

    def test_empty_bands_are_left_out_rather_than_shown_as_zero(self) -> None:
        truth = pd.Series([1, 0])
        probabilities = np.array([0.95, 0.92])

        assert len(evaluate.reliability(truth, probabilities)) == 1
