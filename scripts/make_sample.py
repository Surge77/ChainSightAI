"""Cut the committed slice that the tests run on.

    python scripts/make_sample.py            # rewrite data/sample_orders.csv
    python scripts/make_sample.py --rows 800

The full table is 92 MB and is not committed, so without a slice every test that touches
real data would need a 92 MB download and CI could not run at all. The slice is 500 rows,
sampled proportionally within each (Shipping Mode, order year) cell with a fixed seed, so
it keeps the shape that matters — all four shipping modes, both target classes, the whole
2015-2018 span — and produces the same file on every machine.

**The nine personal-data columns are removed here, using `schema.personal_data()` rather
than a list retyped in this file.** That is what makes the committed slice post-redaction
by construction instead of by inspection: the drop-list cannot fall out of step with the
contract, because there is only one of it.

The leak columns are deliberately *kept*. They are a methodology problem, not a privacy
one, and `chainsight leakage` has to be able to train with them to show what they are
worth. `ingest` removes them on the way in.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from chainsight import schema

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "raw" / "DataCoSupplyChainDataset.csv"
SAMPLE = REPO_ROOT / "data" / "sample_orders.csv"

DEFAULT_ROWS = 500
SEED = 42

#: Sample within these cells so the slice keeps every shipping mode and every year.
STRATA = ["Shipping Mode", "_year"]


def build(frame: pd.DataFrame, rows: int) -> pd.DataFrame:
    """A deterministic, proportionally stratified slice with the personal data removed."""
    frame = frame.drop(columns=schema.personal_data())
    frame = frame.assign(
        _year=pd.to_datetime(frame[schema.ORDER_DATE], format=schema.DATE_FORMAT).dt.year
    )

    # An explicit loop rather than `groupby().apply()`: pandas 3 drops the grouping columns
    # from the frame handed to `apply`, so the helper column vanishes before it can be
    # removed. Iterating keeps the behaviour the same across pandas versions.
    share = rows / len(frame)
    cells = [
        cell.sample(n=max(1, round(len(cell) * share)), random_state=SEED)
        for _, cell in frame.groupby(STRATA, sort=True)
    ]
    taken = pd.concat(cells).drop(columns="_year")
    return taken.sort_values(schema.ORDER_DATE).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS, help="approximate row count")
    args = parser.parse_args(argv)

    if not RAW.is_file():
        print(f"{RAW} is absent. Run `python scripts/fetch_data.py` first.", file=sys.stderr)
        return 1

    frame = pd.read_csv(RAW, encoding=schema.ENCODING, low_memory=False)
    sample = build(frame, args.rows)

    leaked = sorted(set(sample.columns) & set(schema.personal_data()))
    if leaked:
        print(f"refusing to write: personal data survived — {leaked}", file=sys.stderr)
        return 1

    SAMPLE.write_text(sample.to_csv(index=False), encoding="utf-8", newline="")
    late = sample[schema.LATE_TARGET].mean()
    print(
        f"wrote {len(sample)} rows x {sample.shape[1]} columns to {SAMPLE.name} "
        f"(late rate {late:.4f}, {sample['Shipping Mode'].nunique()} shipping modes)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
