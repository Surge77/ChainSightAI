"""The margin regressors, and the tool that decides whether their failure is their fault.

`ceiling.py` is the important part of this file. When a model fails to beat its baseline
there are two explanations with opposite next steps -- the model class cannot reach the
signal, or there is no signal -- and guessing wrong costs an afternoon at best and a
dishonest results table at worst.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.pipeline import Pipeline

from chainsight import ceiling, compare, ingest, regressors, schema, split

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_orders.csv"


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return ingest.ingest(SAMPLE)


class TestRegistry:
    def test_every_regressor_has_a_unique_name(self) -> None:
        assert len(regressors.names()) == len(set(regressors.names()))

    def test_an_unknown_name_lists_what_is_available(self) -> None:
        with pytest.raises(KeyError, match="ridge"):
            regressors.by_name("random forest regressor")

    def test_every_regressor_is_scaled(self) -> None:
        """All four are linear or polynomial, and every one of them needs the scaler."""
        for candidate in regressors.REGRESSORS:
            assert isinstance(candidate.build(), Pipeline)

    def test_the_polynomial_pipeline_expands_before_it_scales(self) -> None:
        """The cheatsheet is explicit about the order: poly first, then scale."""
        steps = [name for name, _ in regressors.by_name("polynomial linear").build().steps]

        assert steps.index("Poly") < steps.index("Scaler")

    def test_every_grid_key_addresses_a_real_parameter(self) -> None:
        for candidate in regressors.REGRESSORS:
            available = candidate.build().get_params()
            for key in candidate.grid:
                assert key in available, f"{candidate.name} has no parameter {key}"


class TestMarginComparison:
    @staticmethod
    def results(frame: pd.DataFrame) -> list[compare.Result]:
        return compare.run_margin(frame, only=["linear regression", "ridge"])

    def test_the_mean_baseline_is_a_row_in_the_table(self, frame: pd.DataFrame) -> None:
        names = {result.name for result in self.results(frame)}

        assert "baseline: mean margin" in names

    def test_the_table_is_sorted_by_mae(self, frame: pd.DataFrame) -> None:
        results = self.results(frame)
        rendered = compare.margin_table(results)
        ordered = sorted(results, key=lambda result: result.scores["mae"])

        positions = [rendered.index(f"| {result.name} |") for result in ordered]
        assert positions == sorted(positions)

    def test_beating_the_mean_is_measured_against_the_mean(self, frame: pd.DataFrame) -> None:
        results = self.results(frame)
        bar = next(r.scores["mae"] for r in results if r.name == "baseline: mean margin")

        for name in compare.beats_the_mean(results):
            assert next(r.scores["mae"] for r in results if r.name == name) < bar

    def test_a_baseline_is_never_counted_as_beating_itself(self, frame: pd.DataFrame) -> None:
        winners = compare.beats_the_mean(self.results(frame))

        assert not any(name.startswith("baseline: ") for name in winners)


class TestCeiling:
    def test_a_column_that_perfectly_determines_the_target_reaches_r2_of_one(self) -> None:
        frame = pd.DataFrame({"group": ["a", "a", "b", "b"], "y": [1.0, 1.0, 5.0, 5.0]})

        result = ceiling.oracle(frame, "y", ["group"])

        assert result.scores["r2"] == pytest.approx(1.0)

    def test_a_column_unrelated_to_the_target_reaches_about_zero(self) -> None:
        rng = np.random.default_rng(42)
        frame = pd.DataFrame({"group": rng.integers(0, 4, 400), "y": rng.normal(size=400)})

        result = ceiling.oracle(frame, "y", ["group"])

        assert abs(result.scores["r2"]) < 0.05

    def test_the_oracle_is_an_upper_bound_on_an_honest_model(self) -> None:
        """It fits on the rows it is scored on, using the exact group means. It cannot lose."""
        frame = pd.DataFrame({"group": ["a", "a", "b", "b"], "y": [1.0, 2.0, 5.0, 6.0]})

        result = ceiling.oracle(frame, "y", ["group"])
        honest = np.full(4, frame["y"].mean())

        assert result.scores["mae"] < float(np.abs(frame["y"] - honest).mean())

    def test_one_row_per_group_is_reported_as_memorising_not_as_a_ceiling(self) -> None:
        """Combine enough columns and the oracle scores 1.0 by reading the answers."""
        frame = pd.DataFrame({"group": list("abcd"), "y": [1.0, 2.0, 3.0, 4.0]})

        result = ceiling.oracle(frame, "y", ["group"])

        assert result.scores["r2"] == pytest.approx(1.0)
        assert result.is_degenerate
        assert result.rows_per_group == 1.0

    def test_a_coarse_grouping_is_not_reported_as_memorising(self) -> None:
        frame = pd.DataFrame({"group": ["a"] * 50 + ["b"] * 50, "y": list(range(100))})

        assert not ceiling.oracle(frame, "y", ["group"]).is_degenerate

    def test_the_survey_orders_columns_worst_first_and_ends_with_the_combination(self) -> None:
        frame = pd.DataFrame(
            {
                "useless": ["x"] * 100,
                "useful": (["a"] * 50) + (["b"] * 50),
                "y": ([1.0] * 50) + ([9.0] * 50),
            }
        )

        survey = ceiling.survey(frame, "y", ["useless", "useful"])

        assert survey[0].columns == ("useless",)
        assert survey[-1].columns == ("useless", "useful")

    def test_the_table_says_whether_each_row_means_anything(self) -> None:
        frame = pd.DataFrame({"group": list("abcd"), "y": [1.0, 2.0, 3.0, 4.0]})

        rendered = ceiling.table([ceiling.oracle(frame, "y", ["group"])])

        assert "memorising rows" in rendered

    def test_the_margin_target_has_no_reachable_signal_in_this_dataset(
        self, frame: pd.DataFrame
    ) -> None:
        """The finding phase 8 exists to establish, asserted so it cannot quietly change.

        Only the coarse columns are checked here. The slice is 500 rows, and a 45-level
        column over 500 rows inflates its own ceiling -- see the test below. On the full
        24,369-row test slice `Category Name` scores 0.0024; `docs/results.md` carries that
        table.
        """
        best = max(
            ceiling.oracle(frame, schema.MARGIN_TARGET, [column]).scores["r2"]
            for column in ("Shipping Mode", "Type", "Market", "Customer Segment")
        )

        assert best < 0.05

    def test_a_high_cardinality_column_inflates_its_own_ceiling_on_a_small_slice(
        self, frame: pd.DataFrame
    ) -> None:
        """Why `rows per group` is printed next to every score rather than left implicit.

        `Category Name` reaches 0.0024 on the 24,369-row test slice and roughly 0.06 on
        these 500 rows. Nothing about the column changed; there are simply few enough rows
        per category for the group means to start fitting noise. A ceiling is only as
        trustworthy as the count beside it.
        """
        fine = ceiling.oracle(frame, schema.MARGIN_TARGET, ["Category Name"])
        coarse = ceiling.oracle(frame, schema.MARGIN_TARGET, ["Market"])

        assert fine.rows_per_group < coarse.rows_per_group
        assert fine.scores["r2"] > coarse.scores["r2"]


def test_no_margin_regressor_meaningfully_beats_the_mean(frame: pd.DataFrame) -> None:
    """Two of them edge it by ~0.0003 MAE, which is noise, not a model."""
    results = compare.run_margin(frame, only=["linear regression", "ridge", "lasso"])
    bar = next(r.scores["mae"] for r in results if r.name == "baseline: mean margin")

    best = min(r.scores["mae"] for r in results if not r.name.startswith("baseline: "))
    assert bar - best < 0.02


def test_the_split_used_for_the_margin_comparison_is_the_chronological_one(
    frame: pd.DataFrame,
) -> None:
    parts = split.by_date(frame)

    assert parts.validation[schema.ORDER_DATE].max() < parts.test[schema.ORDER_DATE].min()
