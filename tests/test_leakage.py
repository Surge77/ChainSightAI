"""This module deliberately reaches for the columns everything else is forbidden to touch.

That makes it the one place where a mistake would be invisible: a leak column escaping
into the honest run would improve the honest number, and an improved number is not
something anybody investigates. So the tests assert the boundary as well as the result.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from chainsight import features, ingest, leakage, schema, split

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_orders.csv"


@pytest.fixture(scope="module")
def raw() -> pd.DataFrame:
    return pd.read_csv(SAMPLE, encoding="utf-8", low_memory=False)


def test_the_honest_feature_matrix_contains_no_leak_column(raw: pd.DataFrame) -> None:
    """The boundary. Everything else in this file is a number; this is the invariant."""
    frame = ingest.ingest(raw)
    parts = split.by_date(frame)
    space = features.FeatureSpace.fit(parts.train)

    built = space.transform(parts.test)

    forbidden = set(leakage.DELIVERY_LEAKS) | set(leakage.MARGIN_LEAKS) | set(schema.targets())
    assert set(built.columns) & forbidden == set()


def test_every_named_leak_is_a_column_the_contract_also_rejects(raw: pd.DataFrame) -> None:
    """The two lists must not drift. A leak known here and allowed there is the worst case."""
    named = set(leakage.DELIVERY_LEAKS) | set(leakage.MARGIN_LEAKS)

    assert named <= set(schema.dropped_at_ingest())


@pytest.fixture(scope="module")
def delivery(raw: pd.DataFrame) -> leakage.Comparison:
    return leakage.delivery_leak(raw)


@pytest.fixture(scope="module")
def margin(raw: pd.DataFrame) -> leakage.Comparison:
    return leakage.margin_leak(raw)


@pytest.fixture(scope="module")
def shuffled(raw: pd.DataFrame) -> leakage.Comparison:
    return leakage.split_leak(raw)


class TestDeliveryLeak:
    def test_the_post_dispatch_columns_produce_a_perfect_score(
        self, delivery: leakage.Comparison
    ) -> None:
        leaked = delivery.rows["with post-dispatch columns"]

        assert leaked["accuracy"] == 1.0
        assert leaked["f1"] == 1.0

    def test_removing_them_costs_a_great_deal(self, delivery: leakage.Comparison) -> None:
        honest = delivery.rows["honest"]
        leaked = delivery.rows["with post-dispatch columns"]

        assert leaked["accuracy"] - honest["accuracy"] > 0.2

    def test_the_honest_run_is_still_better_than_guessing(
        self, delivery: leakage.Comparison
    ) -> None:
        """The point is that the honest number is low, not that it is worthless."""
        assert delivery.rows["honest"]["accuracy"] > 0.5


class TestMarginLeak:
    def test_one_division_recovers_the_target_outright(self, margin: leakage.Comparison) -> None:
        """`Order Profit Per Order` over `Order Item Total` is the target, rounded."""
        recovered = margin.rows["with the profit column and one division"]

        assert recovered["r2"] > 0.99
        assert recovered["mae"] < 0.01

    def test_the_profit_column_alone_understates_the_leak(self, margin: leakage.Comparison) -> None:
        """The reason this leak gets missed: a linear model cannot divide, so it looks mild."""
        alone = margin.rows["with the profit column"]
        recovered = margin.rows["with the profit column and one division"]

        assert alone["r2"] < recovered["r2"]
        assert alone["r2"] > margin.rows["honest"]["r2"]

    def test_the_honest_run_lands_near_the_mean_baseline(self, margin: leakage.Comparison) -> None:
        assert abs(margin.rows["honest"]["r2"]) < 0.2


class TestSplitLeak:
    def test_the_shuffled_split_does_not_flatter_the_model_on_this_table(
        self, shuffled: leakage.Comparison
    ) -> None:
        """The unexpected result, and the reason the comparison is worth running."""
        by_shuffle = shuffled.rows["shuffled split"]["accuracy"]
        by_date = shuffled.rows["honest"]["accuracy"]

        assert by_shuffle - by_date < 0.05

    def test_both_runs_use_the_same_honest_features(self, shuffled: leakage.Comparison) -> None:
        assert set(shuffled.rows) == {"shuffled split", "honest"}


def test_the_report_answers_all_three_questions(raw: pd.DataFrame) -> None:
    rendered = leakage.report(raw)

    assert "Will this order be delivered late?" in rendered
    assert "What margin should we expect on this order?" in rendered
    assert "Does the shuffled split flatter the model?" in rendered


def test_a_comparison_renders_its_note_under_its_table() -> None:
    comparison = leakage.Comparison(
        question="Does it?",
        rows={"a": {"accuracy": 1.0}, "honest": {"accuracy": 0.5}},
        note="Because of the thing.",
    )

    rendered = comparison.render()

    assert rendered.index("| a | 1.0000 |") < rendered.index("Because of the thing.")


def test_a_comparison_without_a_note_renders_only_the_table() -> None:
    comparison = leakage.Comparison(question="Does it?", rows={"honest": {"accuracy": 0.5}})

    assert comparison.render().rstrip().endswith("|")
