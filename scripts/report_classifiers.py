"""Print the classifier comparison, the threshold sweep and the reliability table.

    python scripts/report_classifiers.py             # the full table, if fetched
    python scripts/report_classifiers.py --sample    # the committed 500-row slice

Every number in the model section of `docs/results.md` comes from here. It moves into
`chainsight compare` in phase 11; until the CLI exists this keeps the document
reproducible.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

from chainsight import compare, evaluate, ingest, schema, split

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

    # Convergence warnings from the capped runs would drown the tables; the caps and the
    # iteration limit are both recorded in `models.py` where they can be argued with.
    warnings.filterwarnings("ignore")

    frame = ingest.ingest(source)
    results = compare.run(frame)

    print(compare.table(results))
    winners = compare.clears_both_baselines(results)
    print(
        f"\nclears both baselines at threshold 0.5: {', '.join(winners) if winners else 'nothing'}"
    )

    scored = [r for r in results if r.probabilities is not None and "baseline" not in r.name]
    best = max(scored, key=lambda result: result.scores["f1"])
    probabilities = best.probabilities
    if probabilities is None:  # narrowed by the filter above; keeps the type checker honest
        raise SystemExit("no candidate reported a probability")
    truth = split.by_date(frame).test[schema.LATE_TARGET]

    print(f"\nthreshold sweep, {best.name}\n")
    sweep = evaluate.threshold_sweep(truth, probabilities).round(4)
    print(evaluate.as_markdown(sweep, corner="threshold"))

    print(f"\nreliability, {best.name}\n")
    print(evaluate.as_markdown(evaluate.reliability(truth, probabilities), corner="band"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
