"""The column contract is the spine of the project, so its invariants are tested, not trusted.

Most of these would be caught eventually by a model scoring suspiciously well. "Eventually"
is the problem: by then the number is in a results table and somebody believes it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import render_audit

from chainsight import schema
from chainsight.contract import Availability, Disposition

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_the_contract_covers_the_whole_source_table() -> None:
    manifest = json.loads(
        (REPO_ROOT / "data" / "dataset_manifest.json").read_text(encoding="utf-8")
    )

    assert len(schema.all_columns()) == manifest["files"]["DataCoSupplyChainDataset.csv"]["columns"]


def test_no_column_is_listed_twice() -> None:
    names = schema.names()

    assert len(names) == len(set(names))


def test_no_post_dispatch_column_is_a_feature() -> None:
    """The whole point. A value that exists only after the shipment cannot be an input."""
    late = [
        column.name
        for column in schema.all_columns()
        if column.availability is Availability.POST_DISPATCH
        and column.disposition is Disposition.USE
    ]

    assert late == []


def test_personal_data_is_never_a_feature_or_a_target() -> None:
    allowed = {Disposition.DROP_PII}
    offenders = [
        column.name
        for column in schema.all_columns()
        if column.availability is Availability.NEVER and column.disposition not in allowed
    ]

    assert offenders == []


def test_every_column_marked_personal_is_marked_never_available() -> None:
    """The two axes have to agree, or one of them is decoration."""
    for name in schema.personal_data():
        assert schema.get(name).availability is Availability.NEVER, name


def test_the_dispositions_partition_the_table() -> None:
    """Every column is used, a target, or dropped. Nothing falls between the cases."""
    accounted = (
        set(schema.feature_candidates()) | set(schema.targets()) | set(schema.dropped_at_ingest())
    )

    assert accounted == set(schema.names())


def test_the_two_targets_are_the_ones_the_project_claims_to_predict() -> None:
    assert sorted(schema.targets()) == sorted([schema.LATE_TARGET, schema.MARGIN_TARGET])

    for name in schema.targets():
        assert schema.get(name).availability is Availability.POST_DISPATCH, name


def test_the_named_working_columns_exist_in_the_contract() -> None:
    for name in (schema.LATE_TARGET, schema.MARGIN_TARGET, schema.ORDER_VALUE, schema.ORDER_DATE):
        assert schema.get(name).name == name


def test_the_order_value_survives_ingest_because_the_decision_engine_needs_it() -> None:
    """Profit is the predicted margin times this column. Dropping it breaks the product."""
    assert schema.ORDER_VALUE in schema.feature_candidates()


def test_every_decision_carries_a_reason() -> None:
    """A drop-list without reasons decays into superstition; nobody dares put a column back."""
    for column in schema.all_columns():
        assert column.why.strip(), column.name
        assert column.why.rstrip().endswith("."), column.name


def test_an_unknown_column_names_itself_in_the_error() -> None:
    with pytest.raises(KeyError, match="Shipping Cost"):
        schema.get("Shipping Cost")


def test_the_audit_document_agrees_with_the_contract() -> None:
    """`docs/data_audit.md` is generated from `columns.py`; a stale copy fails here and in CI."""
    assert render_audit.main(["--check"]) == 0


def test_the_leak_list_holds_the_four_columns_the_audit_argues_about() -> None:
    expected = {
        "Days for shipping (real)",
        "Delivery Status",
        "shipping date (DateOrders)",
        "Order Status",
    }

    assert expected <= set(schema.leaks())


def test_post_dispatch_includes_the_targets_so_the_leakage_demo_can_reach_them() -> None:
    assert set(schema.targets()) <= set(schema.post_dispatch())
