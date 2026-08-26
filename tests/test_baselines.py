"""Baselines are the yardstick, so they are tested as carefully as the models will be.

A baseline that is quietly wrong makes every later model look better than it is, and
nothing anywhere will flag it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from chainsight import baselines, evaluate, ingest, schema, split

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_orders.csv"


@pytest.fixture(scope="module")
def parts() -> split.Split:
    return split.by_date(ingest.ingest(SAMPLE))


class TestMajorityClass:
    def test_it_predicts_the_training_majority_for_every_row(self, parts: split.Split) -> None:
        model = baselines.MajorityClass.fit(parts.train)

        predictions = model.predict(parts.test)

        assert set(predictions) == {model.label}
        assert len(predictions) == len(parts.test)

    def test_it_learns_the_majority_from_training_not_from_test(self) -> None:
        train = pd.DataFrame({schema.LATE_TARGET: [0, 0, 0, 1]})

        assert baselines.MajorityClass.fit(train).label == 0

    def test_its_recall_is_one_when_it_always_predicts_late(self, parts: split.Split) -> None:
        """This is why F1 alone cannot pick a winner: always-late scores 1.0 recall for free."""
        train = pd.DataFrame({schema.LATE_TARGET: [1, 1, 1, 0]})
        model = baselines.MajorityClass.fit(train)

        scores = evaluate.classification_scores(
            parts.test[schema.LATE_TARGET], model.predict(parts.test)
        )

        assert scores["recall"] == 1.0


class TestGroupRate:
    def test_it_predicts_each_groups_training_rate(self) -> None:
        train = pd.DataFrame(
            {
                "Shipping Mode": ["First Class"] * 4 + ["Standard Class"] * 4,
                schema.LATE_TARGET: [1, 1, 1, 1, 0, 0, 0, 1],
            }
        )
        model = baselines.GroupRate.fit(train)

        assert model.rates == {"First Class": 1.0, "Standard Class": 0.25}

    def test_a_group_unseen_in_training_falls_back_to_the_overall_rate(self) -> None:
        train = pd.DataFrame({"Shipping Mode": ["First Class"] * 3, schema.LATE_TARGET: [1, 1, 0]})
        model = baselines.GroupRate.fit(train)

        probability = model.predict_proba(pd.DataFrame({"Shipping Mode": ["Drone Delivery"]}))

        assert probability[0] == pytest.approx(2 / 3)

    def test_it_reports_a_probability_not_only_a_label(self, parts: split.Split) -> None:
        """The decision engine consumes probability, so the baseline has to offer one too."""
        model = baselines.GroupRate.fit(parts.train)

        probabilities = set(model.predict_proba(parts.test))

        assert len(probabilities) > 2
        assert all(0.0 <= value <= 1.0 for value in probabilities)

    def test_it_beats_the_majority_class_on_accuracy(self, parts: split.Split) -> None:
        """0.6956 against 0.5511 on the full table. One `if` statement, most of the signal."""
        truth = parts.test[schema.LATE_TARGET]

        rule = evaluate.classification_scores(
            truth, baselines.GroupRate.fit(parts.train).predict(parts.test)
        )
        majority = evaluate.classification_scores(
            truth, baselines.MajorityClass.fit(parts.train).predict(parts.test)
        )

        assert rule["accuracy"] > majority["accuracy"]

    def test_it_can_group_on_a_column_other_than_shipping_mode(self, parts: split.Split) -> None:
        model = baselines.GroupRate.fit(parts.train, column="Type")

        assert model.column == "Type"
        assert set(model.rates) <= set(parts.train["Type"].astype(str))


class TestMeanValue:
    def test_it_predicts_the_training_mean_margin(self, parts: split.Split) -> None:
        model = baselines.MeanValue.fit(parts.train)

        predictions = model.predict(parts.test)

        assert predictions[0] == pytest.approx(parts.train[schema.MARGIN_TARGET].mean())
        assert len(set(predictions)) == 1

    def test_its_r2_is_about_zero_which_is_what_r2_means(self, parts: split.Split) -> None:
        """R-squared is measured against exactly this predictor, so it must land near nothing."""
        model = baselines.MeanValue.fit(parts.train)

        scores = evaluate.regression_scores(
            parts.test[schema.MARGIN_TARGET], model.predict(parts.test)
        )

        assert abs(scores["r2"]) < 0.05
