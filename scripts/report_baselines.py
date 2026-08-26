"""Print the split and the baseline table that open `docs/results.md`.

    python scripts/report_baselines.py                     # the full table, if fetched
    python scripts/report_baselines.py --sample            # the committed 500-row slice

Every number in the opening section of `docs/results.md` comes from here, so a reader can
regenerate it rather than trust it. It moves into `chainsight compare` in phase 11; until
the CLI exists this keeps the document reproducible.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chainsight import baselines, evaluate, ingest, schema, split

REPO_ROOT = Path(__file__).resolve().parent.parent
FULL = REPO_ROOT / "data" / "raw" / "DataCoSupplyChainDataset.csv"
SAMPLE = REPO_ROOT / "data" / "sample_orders.csv"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="use the committed slice")
    args = parser.parse_args(argv)

    source = SAMPLE if args.sample else FULL
    if not source.is_file():
        print(f"{source} is absent. Run `python scripts/fetch_data.py` first.", file=sys.stderr)
        return 1

    frame = ingest.ingest(source)
    parts = split.by_date(frame)
    print(parts.summary())
    print()

    train, test = parts.train, parts.test
    late_true = test[schema.LATE_TARGET]
    margin_true = test[schema.MARGIN_TARGET]

    classification = {
        "majority class": evaluate.classification_scores(
            late_true, baselines.MajorityClass.fit(train).predict(test)
        ),
        "shipping-mode rule": evaluate.classification_scores(
            late_true, baselines.GroupRate.fit(train).predict(test)
        ),
    }
    regression = {
        "mean margin": evaluate.regression_scores(
            margin_true, baselines.MeanValue.fit(train).predict(test)
        )
    }

    print("classification baselines, on the held-out test slice\n")
    print(evaluate.as_table(classification))
    print("\nregression baselines, on the held-out test slice\n")
    print(evaluate.as_table(regression))
    print("\nconfusion matrix, shipping-mode rule\n")
    rule_predictions = baselines.GroupRate.fit(train).predict(test)
    print(evaluate.as_markdown(evaluate.confusion(late_true, rule_predictions)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
