"""A split bug does not crash. It produces a better number, which is why these are strict."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from chainsight import ingest, schema, split

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_orders.csv"


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return ingest.ingest(SAMPLE)


@pytest.fixture(scope="module")
def parts(frame: pd.DataFrame) -> split.Split:
    return split.by_date(frame)


def test_no_order_appears_in_two_slices(parts: split.Split) -> None:
    total = sum(parts.sizes.values())
    combined = pd.concat([parts.train, parts.validation, parts.test])

    assert len(combined.drop_duplicates()) == total


def test_every_order_lands_somewhere(parts: split.Split, frame: pd.DataFrame) -> None:
    assert sum(parts.sizes.values()) == len(frame)


def test_training_ends_before_validation_begins(parts: split.Split) -> None:
    assert parts.train[schema.ORDER_DATE].max() < parts.validation[schema.ORDER_DATE].min()


def test_validation_ends_before_test_begins(parts: split.Split) -> None:
    """The one that matters. A day of overlap is a day of the future in the training set."""
    assert parts.validation[schema.ORDER_DATE].max() < parts.test[schema.ORDER_DATE].min()


def test_the_boundaries_are_where_they_were_asked_to_be(parts: split.Split) -> None:
    assert parts.validation[schema.ORDER_DATE].min() >= split.VALIDATION_START
    assert parts.test[schema.ORDER_DATE].min() >= split.TEST_START


def test_custom_boundaries_are_honoured(frame: pd.DataFrame) -> None:
    parts = split.by_date(
        frame,
        validation_start=pd.Timestamp("2016-01-01"),
        test_start=pd.Timestamp("2017-01-01"),
    )

    assert parts.train[schema.ORDER_DATE].max() < pd.Timestamp("2016-01-01")
    assert parts.test[schema.ORDER_DATE].min() >= pd.Timestamp("2017-01-01")


def test_boundaries_in_the_wrong_order_are_refused(frame: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="before test"):
        split.by_date(
            frame,
            validation_start=pd.Timestamp("2017-07-01"),
            test_start=pd.Timestamp("2017-01-01"),
        )


def test_a_boundary_that_empties_a_slice_is_refused(frame: pd.DataFrame) -> None:
    """Silently returning an empty test set would score every model as perfect or as nothing."""
    with pytest.raises(ValueError, match="empty slice"):
        split.by_date(
            frame,
            validation_start=pd.Timestamp("2030-01-01"),
            test_start=pd.Timestamp("2030-06-01"),
        )


def test_the_shuffled_split_is_reproducible(frame: pd.DataFrame) -> None:
    first = split.at_random(frame)
    second = split.at_random(frame)

    pd.testing.assert_frame_equal(first.test, second.test)


def test_the_shuffled_split_is_labelled_as_such(frame: pd.DataFrame) -> None:
    """`how` reaches the results table, so a shuffled number can never be read as a dated one."""
    assert split.at_random(frame).how == "shuffled"
    assert split.by_date(frame).how == "chronological"


def test_the_shuffled_split_mixes_the_years_the_dated_one_separates(frame: pd.DataFrame) -> None:
    shuffled = split.at_random(frame).train[schema.ORDER_DATE]
    dated = split.by_date(frame).train[schema.ORDER_DATE]

    assert shuffled.dt.year.nunique() > dated.dt.year.nunique()


def test_the_summary_names_the_span_and_the_rate_of_each_slice(parts: split.Split) -> None:
    summary = parts.summary()

    assert "chronological" in summary
    for name in ("train", "validation", "test"):
        assert name in summary
    assert "late" in summary
