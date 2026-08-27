"""The serving model is fitted through the same path everything else is measured on.

A model fitted by a second code path is the same class of bug as a second feature builder:
the two agree until they quietly do not. So the assertions here are mostly about provenance
— that the artefact records what it was fitted on, and that the recorded hashes are the ones
`persistence.load` will check against.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from chainsight import ingest, persistence, split, training
from chainsight.decision import CostModel

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_orders.csv"


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return ingest.ingest(SAMPLE)


@pytest.fixture(scope="module")
def run(frame: pd.DataFrame) -> training.TrainingRun:
    return training.train(frame)


class TestTrain:
    def test_the_default_model_is_chosen_on_ranking_rather_than_accuracy(
        self, run: training.TrainingRun
    ) -> None:
        """`docs/results.md` argues this. The default should not quietly disagree with it."""
        assert run.manifest.model_name == "one-hot random forest"
        assert run.manifest.encoding == "one-hot"

    def test_a_ranking_score_is_recorded_because_that_is_what_promotion_compares_on(
        self, run: training.TrainingRun
    ) -> None:
        assert "roc auc" in run.scores
        assert "avg precision" in run.scores

    def test_the_threshold_is_derived_from_the_cost_model_not_assumed(
        self, run: training.TrainingRun
    ) -> None:
        assert run.manifest.threshold != 0.5
        assert 0.0 < run.manifest.threshold < 0.5

    def test_the_feature_hash_is_the_one_the_loader_will_check(
        self, run: training.TrainingRun
    ) -> None:
        assert run.manifest.feature_hash == persistence.feature_hash(run.artefact.space)

    def test_the_artefact_it_produced_verifies(self, run: training.TrainingRun) -> None:
        assert run.manifest.verify(run.artefact.space) is None

    def test_it_is_fitted_on_the_training_slice_only(
        self, run: training.TrainingRun, frame: pd.DataFrame
    ) -> None:
        """The held-out slice is scored once. Fitting on it would make the score a fiction."""
        parts = split.by_date(frame)

        assert run.rows_trained == len(parts.train)
        assert run.rows_tested == len(parts.test)

    def test_the_validation_slice_is_left_alone(
        self, run: training.TrainingRun, frame: pd.DataFrame
    ) -> None:
        """It was spent choosing between models. Spending it again would be reading it twice."""
        parts = split.by_date(frame)

        assert run.rows_trained + run.rows_tested == len(frame) - len(parts.validation)

    def test_a_path_is_hashed_as_the_file_it_is(self) -> None:
        from_path = training.train(SAMPLE)

        assert from_path.manifest.dataset_hash == persistence.dataset_hash(SAMPLE)

    def test_another_candidate_can_be_named(self, frame: pd.DataFrame) -> None:
        other = training.train(frame, model_name="decision tree")

        assert other.manifest.model_name == "decision tree"
        assert other.manifest.encoding == "codes"

    def test_a_model_that_does_not_exist_names_the_ones_that_do(self, frame: pd.DataFrame) -> None:
        with pytest.raises(KeyError, match="Available"):
            training.train(frame, model_name="a gradient boosted xgboost")

    def test_a_model_without_predict_proba_records_no_ranking_score(
        self, frame: pd.DataFrame
    ) -> None:
        """`SVC` has none, and `registry.promote` refuses to compare a model that lacks one.

        Faking the number from a decision function would be worse than not having it: the
        decision engine multiplies this probability by money.
        """
        blind = training.train(frame, model_name="support vector machine")

        assert "roc auc" not in blind.scores
        assert "accuracy" in blind.scores

    def test_the_grid_search_parameters_are_recorded(self, frame: pd.DataFrame) -> None:
        tuned = training.train(frame, model_name="decision tree")

        assert "max_depth" in tuned.manifest.parameters

    def test_a_different_cost_model_moves_the_threshold(self, frame: pd.DataFrame) -> None:
        cheap = training.train(frame, costs=CostModel(intervention=1.0))

        assert cheap.manifest.threshold < CostModel().threshold


class TestSummary:
    def test_the_summary_names_the_slice_sizes_and_the_threshold(
        self, run: training.TrainingRun
    ) -> None:
        summary = run.summary()

        assert f"{run.rows_trained:,} orders" in summary
        assert "not assumed" in summary

    def test_the_fold_score_is_reported_beside_the_held_out_score(
        self, run: training.TrainingRun
    ) -> None:
        """A fold score far above the held-out score is the shape of overfitting."""
        assert "fold score" in run.summary()
        assert 0.0 <= run.fold_score <= 1.0


class TestArtefactName:
    def test_the_name_says_what_the_artefact_is_without_opening_it(
        self, run: training.TrainingRun
    ) -> None:
        name = training.artefact_name(run)

        assert name.startswith("one-hot-random-forest-")
        assert ":" not in name

    def test_the_name_is_a_safe_filename(self, run: training.TrainingRun) -> None:
        """It becomes a path, and `persistence.resolve` would refuse it if it were not."""
        assert persistence.resolve(training.artefact_name(run)).name.endswith(".joblib")
