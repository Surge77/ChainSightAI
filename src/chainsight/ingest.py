"""Read the source table and hand back only what the contract allows.

This is the single door into the data. Everything downstream receives a frame that has
already lost the leaks, the personal data, the identifiers, the duplicates and the empty
columns, so no later module has to remember to avoid them. A column that never arrives
cannot be used by accident, and cannot reach a log line or a traceback either.

Two shapes are accepted, and both come out the same:

* the full `DataCoSupplyChainDataset.csv`, 53 columns;
* the committed `data/sample_orders.csv`, 44 columns, already missing the personal data.

Anything else — a missing feature column, an unknown column — is an error naming the
column, because a silently reshaped input produces numbers rather than a crash.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from chainsight import schema
from chainsight.contract import Disposition

#: Rounded away at ingest. The publisher stored the rate as float32, so 0.03 arrives as
#: 0.029999999 and 18 real rates present as 18 slightly different ones.
_RATE_DECIMALS = 2


class SchemaError(ValueError):
    """The frame is not the table this project was written against."""


def read_raw(path: Path | str) -> pd.DataFrame:
    """Read a CSV with the encoding it is actually in, which is not the same for both files.

    `data/dataset_manifest.json` records that the published source is latin-1: reading it as
    UTF-8 raises `UnicodeDecodeError` at byte 1709. The committed slice is not. It is written
    by `scripts/make_sample.py` as UTF-8, because a file in a public repository should render
    in a browser and a text editor rather than arriving as mojibake.

    So UTF-8 is tried first, strictly, and latin-1 is used when that fails. This is a
    decision rather than a guess, and the asymmetry is the reason it is safe: UTF-8 is
    self-validating, so a latin-1 file carrying an accent cannot be read as UTF-8 by
    accident, while a UTF-8 file read as latin-1 succeeds and silently produces
    `AfganistÃ¡n`. Only the failing direction is loud, so that is the direction to try first.
    """
    try:
        return pd.read_csv(path, encoding="utf-8", low_memory=False)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding=schema.ENCODING, low_memory=False)


def check_columns(frame: pd.DataFrame) -> None:
    """Raise unless every column the project needs is present and every column is known.

    The requirement is deliberately the *needed* set rather than the whole source table.
    A frame is acceptable if it carries the feature candidates and the targets, whatever
    else it has lost along the way — which makes the full 53-column table, the committed
    44-column slice, and an already-ingested frame all valid inputs, while a frame missing
    `Shipping Mode` is still an immediate error.

    Requiring the dropped columns to be present would mean demanding the personal data
    back before agreeing to remove it.
    """
    present = set(frame.columns)

    unknown = sorted(present - set(schema.names()))
    if unknown:
        raise SchemaError(
            f"columns absent from the contract: {unknown}. "
            "Add them to src/chainsight/columns.py with a reason, or drop them upstream."
        )

    needed = set(schema.feature_candidates()) | set(schema.targets())
    missing = sorted(needed - present)
    if missing:
        raise SchemaError(f"columns missing from the frame: {missing}")


def ingest(
    source: pd.DataFrame | Path | str,
    *,
    exclude_cancelled: bool = False,
) -> pd.DataFrame:
    """The feature candidates and the two targets, with dates parsed and rates rounded.

    `exclude_cancelled` drops the orders whose shipment was cancelled. It defaults to
    False so that the frame matches the task as published: `Late_delivery_risk` is 0 on
    all 7,754 of those rows, even though the arithmetic that defines the label everywhere
    else would make 4,423 of them 1. A shipment that never went cannot be late.

    Whether that is label noise worth removing is a real question and not a settled one,
    so it is a flag at the call site rather than a decision buried in here. `TODO.md`
    tracks measuring it. The filter runs while `Delivery Status` is still present and the
    column is dropped immediately afterwards either way.
    """
    frame = read_raw(source) if isinstance(source, str | Path) else source.copy()
    check_columns(frame)

    if exclude_cancelled:
        frame = _without_cancelled(frame)

    keep = [
        name for name in schema.names() if name in frame.columns and not schema.get(name).is_dropped
    ]
    frame = frame.loc[:, keep]

    frame[schema.ORDER_DATE] = pd.to_datetime(frame[schema.ORDER_DATE], format=schema.DATE_FORMAT)
    frame[schema.DISCOUNT_RATE] = frame[schema.DISCOUNT_RATE].round(_RATE_DECIMALS)

    return frame.reset_index(drop=True)


def _without_cancelled(frame: pd.DataFrame) -> pd.DataFrame:
    if schema.DELIVERY_STATUS not in frame.columns:
        raise SchemaError(
            f"cannot exclude cancelled orders: {schema.DELIVERY_STATUS!r} is not in the frame"
        )
    return frame.loc[frame[schema.DELIVERY_STATUS] != schema.CANCELLED_STATUS]


def dropped_from(frame: pd.DataFrame) -> dict[str, list[str]]:
    """What `ingest` would remove from this frame, grouped by why. For the CLI and tests."""
    grouped: dict[str, list[str]] = {}
    for name in frame.columns:
        column = schema.get(name)
        if column.is_dropped:
            grouped.setdefault(column.disposition.value, []).append(name)
    return grouped


def describe(frame: pd.DataFrame) -> str:
    """A short report on an ingested frame. Printed by `chainsight describe`."""
    late = frame[schema.LATE_TARGET].mean()
    margin = frame[schema.MARGIN_TARGET]
    span = frame[schema.ORDER_DATE]
    features = [name for name in frame.columns if schema.get(name).disposition is Disposition.USE]
    return "\n".join(
        [
            f"{len(frame):,} rows x {frame.shape[1]} columns ({len(features)} feature candidates)",
            f"orders from {span.min():%Y-%m-%d} to {span.max():%Y-%m-%d}",
            f"late rate {late:.4f}",
            f"margin ratio: mean {margin.mean():.4f}, {(margin < 0).mean():.4%} loss-making",
        ]
    )
