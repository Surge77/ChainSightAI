"""The committed slice is the only real data CI ever sees, so its shape is asserted here.

The first test is the one that matters: it is the mechanical check behind the promise in
SECURITY.md that no personal data reaches the repository.
"""

from __future__ import annotations

from pathlib import Path

import make_sample
import pandas as pd
import pytest

from chainsight import schema

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_orders.csv"


@pytest.fixture(scope="module")
def sample() -> pd.DataFrame:
    return pd.read_csv(SAMPLE, encoding="utf-8", low_memory=False)


def test_the_committed_sample_carries_no_personal_data(sample: pd.DataFrame) -> None:
    assert set(sample.columns) & set(schema.personal_data()) == set()


def test_the_sample_holds_every_column_that_is_not_personal_data(sample: pd.DataFrame) -> None:
    expected = [name for name in schema.names() if name not in set(schema.personal_data())]

    assert list(sample.columns) == expected


def test_the_sample_keeps_the_leak_columns_on_purpose(sample: pd.DataFrame) -> None:
    """`chainsight leakage` has to train with them. They are a methodology problem, not privacy."""
    assert set(schema.leaks()) <= set(sample.columns)


def test_the_sample_contains_both_target_classes(sample: pd.DataFrame) -> None:
    assert set(sample[schema.LATE_TARGET].unique()) == {0, 1}


def test_the_sample_contains_every_shipping_mode(sample: pd.DataFrame) -> None:
    """Shipping Mode is the dominant signal; a slice missing one mode would hide it."""
    assert sample["Shipping Mode"].nunique() == 4


def test_the_sample_spans_the_whole_period(sample: pd.DataFrame) -> None:
    years = pd.to_datetime(sample[schema.ORDER_DATE], format=schema.DATE_FORMAT).dt.year

    assert set(years.unique()) == {2015, 2016, 2017, 2018}


def test_the_sample_contains_loss_making_orders(sample: pd.DataFrame) -> None:
    """The margin target is negative on 18.7% of the full table; a slice without any is useless."""
    assert (sample[schema.MARGIN_TARGET] < 0).any()


def test_building_the_same_slice_twice_gives_the_same_rows() -> None:
    frame = pd.DataFrame(
        {
            "Shipping Mode": ["Standard Class", "First Class"] * 20,
            schema.ORDER_DATE: ["1/2/2015 10:00", "6/9/2017 14:30"] * 20,
            schema.LATE_TARGET: [0, 1] * 20,
            "Customer Password": ["XXXXXXXXX"] * 40,
            "Customer Email": ["XXXXXXXXX"] * 40,
            "Customer Fname": ["A"] * 40,
            "Customer Lname": ["B"] * 40,
            "Customer Street": ["C"] * 40,
            "Customer Zipcode": [1] * 40,
            "Latitude": [0.0] * 40,
            "Longitude": [0.0] * 40,
            "Order Zipcode": [1] * 40,
        }
    )

    first = make_sample.build(frame, rows=10)
    second = make_sample.build(frame, rows=10)

    pd.testing.assert_frame_equal(first, second)


def test_building_removes_personal_data_using_the_contract_not_a_retyped_list() -> None:
    frame = pd.DataFrame(
        {
            "Shipping Mode": ["Standard Class"] * 4,
            schema.ORDER_DATE: ["1/2/2015 10:00"] * 4,
            **{name: ["secret"] * 4 for name in schema.personal_data()},
        }
    )

    built = make_sample.build(frame, rows=2)

    assert set(built.columns) == {"Shipping Mode", schema.ORDER_DATE}
