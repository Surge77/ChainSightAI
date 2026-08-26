"""`ingest` is the only door into the data, so what it refuses matters as much as what it returns.

The first two tests are the mechanical form of promises made in `SECURITY.md` and
`docs/data_audit.md`: no personal data and no post-dispatch column survives the door.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from chainsight import ingest, schema
from chainsight.contract import Availability

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_orders.csv"


@pytest.fixture(scope="module")
def raw_sample() -> pd.DataFrame:
    return pd.read_csv(SAMPLE, encoding="utf-8", low_memory=False)


@pytest.fixture(scope="module")
def ingested(raw_sample: pd.DataFrame) -> pd.DataFrame:
    return ingest.ingest(raw_sample)


def test_no_personal_data_survives(ingested: pd.DataFrame) -> None:
    assert set(ingested.columns) & set(schema.personal_data()) == set()


def test_no_post_dispatch_column_survives_except_the_targets(ingested: pd.DataFrame) -> None:
    survivors = {
        name
        for name in ingested.columns
        if schema.get(name).availability is Availability.POST_DISPATCH
    }

    assert survivors == set(schema.targets())


def test_the_result_is_exactly_the_feature_candidates_and_the_targets(
    ingested: pd.DataFrame,
) -> None:
    assert set(ingested.columns) == set(schema.feature_candidates()) | set(schema.targets())


def test_the_order_date_arrives_as_a_timestamp_not_a_string(ingested: pd.DataFrame) -> None:
    assert pd.api.types.is_datetime64_any_dtype(ingested[schema.ORDER_DATE])


def test_the_discount_rate_loses_its_float32_noise(ingested: pd.DataFrame) -> None:
    """0.03 arrives from the publisher as 0.029999999, which would present as a distinct rate."""
    rates = ingested[schema.DISCOUNT_RATE]

    assert (rates == rates.round(2)).all()


def test_the_row_count_is_unchanged_by_default(
    ingested: pd.DataFrame, raw_sample: pd.DataFrame
) -> None:
    assert len(ingested) == len(raw_sample)


def test_excluding_cancelled_orders_removes_rows_and_nothing_else(
    raw_sample: pd.DataFrame,
) -> None:
    cancelled = (raw_sample[schema.DELIVERY_STATUS] == schema.CANCELLED_STATUS).sum()

    kept = ingest.ingest(raw_sample, exclude_cancelled=True)

    assert len(kept) == len(raw_sample) - cancelled
    assert cancelled > 0, "the slice should contain some cancelled shipments to test against"


def test_excluding_cancelled_orders_needs_the_column_it_filters_on(
    raw_sample: pd.DataFrame,
) -> None:
    already_ingested = ingest.ingest(raw_sample)

    with pytest.raises(ingest.SchemaError, match="Delivery Status"):
        ingest.ingest(already_ingested, exclude_cancelled=True)


def test_an_unknown_column_is_named_in_the_error(raw_sample: pd.DataFrame) -> None:
    frame = raw_sample.assign(**{"Carrier Rating": 5})

    with pytest.raises(ingest.SchemaError, match="Carrier Rating"):
        ingest.ingest(frame)


def test_a_missing_feature_column_is_named_in_the_error(raw_sample: pd.DataFrame) -> None:
    frame = raw_sample.drop(columns=["Shipping Mode"])

    with pytest.raises(ingest.SchemaError, match="Shipping Mode"):
        ingest.ingest(frame)


def test_a_frame_already_missing_its_personal_data_is_accepted(raw_sample: pd.DataFrame) -> None:
    """The committed slice is exactly this case, and it must not look like a broken input."""
    ingest.check_columns(raw_sample)


def test_a_missing_target_is_named_in_the_error(raw_sample: pd.DataFrame) -> None:
    """Tolerating absent dropped columns must not extend to tolerating an absent target."""
    frame = raw_sample.drop(columns=[schema.MARGIN_TARGET])

    with pytest.raises(ingest.SchemaError, match=schema.MARGIN_TARGET):
        ingest.ingest(frame)


def test_ingesting_twice_is_the_same_as_ingesting_once(ingested: pd.DataFrame) -> None:
    pd.testing.assert_frame_equal(ingest.ingest(ingested), ingested)


def test_reading_the_source_file_uses_the_encoding_it_is_actually_in(tmp_path: Path) -> None:
    """UTF-8 would raise on this byte; the whole point of pinning latin-1 in the schema."""
    path = tmp_path / "latin.csv"
    path.write_bytes(b"Product Name,Product Price\nCaf\xe9 Mug,12.5\n")

    frame = ingest.read_raw(path)

    assert frame.loc[0, "Product Name"] == "Café Mug"


def test_dropped_columns_are_grouped_by_the_reason_they_are_dropped(
    raw_sample: pd.DataFrame,
) -> None:
    grouped = ingest.dropped_from(raw_sample)

    assert "Delivery Status" in grouped["drop: leak"]
    assert "Sales per customer" in grouped["drop: duplicate"]
    assert "Product Status" in grouped["drop: constant or empty"]


def test_describe_reports_the_span_the_rate_and_the_losses(ingested: pd.DataFrame) -> None:
    report = ingest.describe(ingested)

    assert "late rate" in report
    assert "loss-making" in report
    assert "2015-01" in report
