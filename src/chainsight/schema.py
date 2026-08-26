"""Questions the rest of the package asks of the column contract.

Nothing here knows anything about the DataCo table; it all comes from `columns.COLUMNS`.
The point of routing every question through this module is that a column cannot become a
feature by being mentioned in a feature builder. It becomes a feature by being listed in
the contract with `Disposition.USE`, which means it also appears in `docs/data_audit.md`
with a reason, because a test asserts the document and the contract agree.
"""

from __future__ import annotations

from chainsight.columns import COLUMNS
from chainsight.contract import Availability, Column, Disposition

#: The classification target: was this order delivered later than it was scheduled to be.
LATE_TARGET = "Late_delivery_risk"

#: The regression target: margin as a fraction of the order total.
MARGIN_TARGET = "Order Item Profit Ratio"

#: The line value the decision engine multiplies by the predicted margin to get money.
ORDER_VALUE = "Order Item Total"

#: The column the time-aware split orders on.
ORDER_DATE = "order date (DateOrders)"

#: `pandas.read_csv` needs this. The file is not UTF-8; see `data/dataset_manifest.json`.
ENCODING = "latin-1"

#: The publisher's date format, e.g. `1/31/2018 22:56`.
DATE_FORMAT = "%m/%d/%Y %H:%M"

_BY_NAME: dict[str, Column] = {column.name: column for column in COLUMNS}


def all_columns() -> tuple[Column, ...]:
    return COLUMNS


def get(name: str) -> Column:
    """The contract entry for one column, or `KeyError` naming the column that is absent."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"{name!r} is not in the column contract; add it to columns.py") from None


def names() -> list[str]:
    """Every column of the source table, in file order."""
    return [column.name for column in COLUMNS]


def with_disposition(*dispositions: Disposition) -> list[str]:
    return [column.name for column in COLUMNS if column.disposition in dispositions]


def feature_candidates() -> list[str]:
    """Columns the feature builder may draw on. Not the final feature list.

    `features.py` still decides what to derive and what to discard as collinear. This is
    the set it is allowed to look at, which is a different and stricter thing.
    """
    return with_disposition(Disposition.USE)


def targets() -> list[str]:
    return with_disposition(Disposition.TARGET)


def dropped_at_ingest() -> list[str]:
    """Everything `ingest` removes before any other code sees the frame."""
    return [column.name for column in COLUMNS if column.is_dropped]


def personal_data() -> list[str]:
    """The columns `SECURITY.md` promises never reach a log, a traceback or an artefact."""
    return with_disposition(Disposition.DROP_PII)


def leaks() -> list[str]:
    """Columns that exist only after the outcome, excluding the targets themselves."""
    return with_disposition(Disposition.DROP_LEAK)


def post_dispatch() -> list[str]:
    """Every column unknown at order time, targets included.

    `leakage.py` trains once with these present to show what the published 0.98-accuracy
    results on this dataset are actually measuring.
    """
    return [c.name for c in COLUMNS if c.availability is Availability.POST_DISPATCH]
