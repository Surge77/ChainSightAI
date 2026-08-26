"""One feature builder means one set of columns, in one order, whichever path calls it.

The test that earns its keep here is
`test_a_single_order_produces_the_same_columns_in_the_same_order_as_training`. scikit-learn
indexes features positionally once fitted, so a serving frame with the right columns in the
wrong order predicts confidently and wrongly, with nothing in the traceback to notice.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from chainsight import features, ingest, schema
from chainsight.encoding import UNSEEN, CategoryCodes

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_orders.csv"


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return ingest.ingest(pd.read_csv(SAMPLE, encoding="utf-8", low_memory=False))


@pytest.fixture(scope="module")
def space(frame: pd.DataFrame) -> features.FeatureSpace:
    return features.FeatureSpace.fit(frame)


def order_from(frame: pd.DataFrame, position: int = 0) -> dict[str, object]:
    row = frame.iloc[position]
    return {name: row[name] for name in features.ORDER_FIELDS}


def test_every_feature_is_numeric(space: features.FeatureSpace, frame: pd.DataFrame) -> None:
    built = space.transform(frame)

    assert all(pd.api.types.is_numeric_dtype(built[name]) for name in built.columns)


def test_no_target_reaches_the_feature_matrix(
    space: features.FeatureSpace, frame: pd.DataFrame
) -> None:
    built = space.transform(frame)

    assert set(built.columns) & set(schema.targets()) == set()


def test_no_raw_date_reaches_the_feature_matrix(
    space: features.FeatureSpace, frame: pd.DataFrame
) -> None:
    """A model reading the timestamp as a number learns "later is different"."""
    built = space.transform(frame)

    assert schema.ORDER_DATE not in built.columns


def test_a_single_order_produces_the_same_columns_in_the_same_order_as_training(
    space: features.FeatureSpace, frame: pd.DataFrame
) -> None:
    trained = space.transform(frame)

    served = space.transform(features.single_order(**order_from(frame)))

    assert list(served.columns) == list(trained.columns)


def test_a_single_order_produces_the_same_values_as_its_row_in_training(
    space: features.FeatureSpace, frame: pd.DataFrame
) -> None:
    """Not just the same columns — the same numbers. Otherwise serving is a second builder."""
    position = 7
    from_training = space.transform(frame).iloc[[position]].reset_index(drop=True)

    from_serving = space.transform(
        features.single_order(**order_from(frame, position))
    ).reset_index(drop=True)

    pd.testing.assert_frame_equal(from_serving, from_training, check_dtype=False)


def test_an_order_missing_a_field_says_which(frame: pd.DataFrame) -> None:
    fields = order_from(frame)
    fields.pop("Shipping Mode")

    with pytest.raises(KeyError, match="Shipping Mode"):
        features.single_order(**fields)


def test_an_order_with_an_invented_field_says_which(frame: pd.DataFrame) -> None:
    fields = order_from(frame) | {"Carrier Rating": 5}

    with pytest.raises(KeyError, match="Carrier Rating"):
        features.single_order(**fields)


def test_fit_transform_refuses_rather_than_leaking_the_test_slice(
    space: features.FeatureSpace, frame: pd.DataFrame
) -> None:
    with pytest.raises(NotImplementedError, match="training slice"):
        space.fit_transform(frame)


def test_the_column_order_is_stable_across_two_fits(frame: pd.DataFrame) -> None:
    first = features.FeatureSpace.fit(frame)
    second = features.FeatureSpace.fit(frame)

    assert first.columns == second.columns


def test_the_weekend_flag_agrees_with_the_day_of_week(frame: pd.DataFrame) -> None:
    derived = features.derive(frame)

    weekend = derived["order_day_of_week"] >= 5
    assert (derived["order_is_weekend"] == weekend.astype("int64")).all()


def test_the_domestic_flag_uses_the_destination_vocabulary_not_the_customer_one(
    frame: pd.DataFrame,
) -> None:
    """`Customer Country` says "EE. UU."; `Order Country` says "Estados Unidos". Same place."""
    derived = features.derive(frame)

    expected = (frame["Order Country"] == "Estados Unidos").astype("int64")
    assert (derived["is_domestic_destination"] == expected).all()
    assert derived["is_domestic_destination"].sum() > 0


def test_value_per_unit_divides_the_discounted_total_not_the_list_price(
    frame: pd.DataFrame,
) -> None:
    derived = features.derive(frame)

    expected = frame["Order Item Total"] / frame["Order Item Quantity"]
    assert (derived["value_per_unit"] - expected).abs().max() < 1e-9


class TestCategoryCodes:
    def test_a_category_seen_in_training_keeps_a_stable_code(self, frame: pd.DataFrame) -> None:
        codes = CategoryCodes.fit(frame, ["Shipping Mode"])

        first = codes.transform(frame.head(10))["Shipping Mode"]
        second = codes.transform(frame.head(10))["Shipping Mode"]

        assert first.equals(second)

    def test_an_unseen_category_becomes_unseen_rather_than_raising(self) -> None:
        """`LabelEncoder.transform` raises here, which would turn an unusual order into a 500."""
        trained = pd.DataFrame({"Shipping Mode": ["Standard Class", "First Class"]})
        codes = CategoryCodes.fit(trained, ["Shipping Mode"])

        served = codes.transform(pd.DataFrame({"Shipping Mode": ["Drone Delivery"]}))

        assert served.loc[0, "Shipping Mode"] == UNSEEN

    def test_the_unseen_code_cannot_collide_with_a_real_one(self, frame: pd.DataFrame) -> None:
        codes = CategoryCodes.fit(frame, list(features.CATEGORICAL))

        encoded = codes.transform(frame)
        assert (encoded >= 0).all().all()
        assert UNSEEN < 0

    def test_the_unseen_rate_is_zero_on_the_data_it_was_fitted_to(
        self, frame: pd.DataFrame
    ) -> None:
        codes = CategoryCodes.fit(frame, list(features.CATEGORICAL))

        assert set(codes.unseen_rate(frame).values()) == {0.0}

    def test_a_missing_encoded_column_is_named(self, frame: pd.DataFrame) -> None:
        codes = CategoryCodes.fit(frame, ["Shipping Mode"])

        with pytest.raises(KeyError, match="Shipping Mode"):
            codes.transform(frame.drop(columns=["Shipping Mode"]))

    def test_levels_counts_what_was_seen(self, frame: pd.DataFrame) -> None:
        codes = CategoryCodes.fit(frame, ["Shipping Mode"])

        assert codes.levels("Shipping Mode") == frame["Shipping Mode"].nunique()
