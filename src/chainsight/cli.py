"""One entry point onto everything the package can do without a browser.

    python -m chainsight describe            # what the table is
    python -m chainsight leakage             # train it twice, print both numbers
    python -m chainsight compare             # the fourteen-model table
    python -m chainsight train --promote     # fit, register, and make it live
    python -m chainsight registry            # what is trained and what is serving
    python -m chainsight predict order.json  # one order, one decision

Every command takes `--sample` to run against the committed 500-row slice instead of the
92 MB source file, which is what makes this testable and what lets somebody who has not
downloaded the dataset see the shape of the output.

The scripts under `scripts/` are not replaced. They exist to regenerate the numbers in the
documents and are pinned to that job; this is the operator's interface, and the difference
matters when a document's numbers have to be reproduced years later by running the same
file that produced them.

Nothing here catches broad exceptions to print a friendly message. A traceback from a
missing dataset file is more useful than "something went wrong", and the two failures worth
translating — an artefact that cannot be trusted, and a promotion that would be a
regression — are caught by name.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from chainsight import compare, decision, ingest, leakage, models, persistence, registry, training
from chainsight.features import ORDER_FIELDS, single_order

_DESCRIPTION = "Pre-dispatch late-delivery risk, the leakage audit behind it, and one decision."

#: The full table, if it has been fetched. `scripts/fetch_data.py` puts it here.
FULL_DATA = Path("data") / "raw" / "DataCoSupplyChainDataset.csv"

#: The committed slice, which is in the repository and needs no download.
SAMPLE_DATA = Path("data") / "sample_orders.csv"


def _source(args: argparse.Namespace) -> Path:
    path = SAMPLE_DATA if args.sample else Path(args.data)
    if not path.is_file():
        raise SystemExit(
            f"{path} is absent. Run `python scripts/fetch_data.py`, or pass --sample to use "
            "the committed 500-row slice."
        )
    return path


def _artefacts(args: argparse.Namespace) -> Path:
    return Path(args.artefacts)


def _registry(args: argparse.Namespace) -> registry.Registry:
    return registry.Registry(path=_artefacts(args) / registry.REGISTRY_NAME)


def describe(args: argparse.Namespace) -> int:
    """What the ingested table looks like, and what ingest removed to get there."""
    raw = ingest.read_raw(_source(args))
    frame = ingest.ingest(raw)
    print(ingest.describe(frame))
    print()
    for reason, names in sorted(ingest.dropped_from(raw).items()):
        print(f"{reason:24s} {len(names):2d}  {', '.join(sorted(names))}")
    return 0


def leak(args: argparse.Namespace) -> int:
    """The same estimators trained twice, with and without what they must not see."""
    print(leakage.report(str(_source(args))))
    return 0


def rank(args: argparse.Namespace) -> int:
    """Every candidate against the same split and the same baselines."""
    frame = ingest.ingest(_source(args))
    if args.margin:
        results = compare.run_margin(frame)
        print(compare.margin_table(results))
        beat = compare.beats_the_mean(results)
        print(f"\nbeats the mean baseline: {', '.join(beat) if beat else 'nothing'}")
        return 0

    results = compare.run(frame, only=args.only)
    print(compare.table(results))
    winners = compare.clears_both_baselines(results)
    print(f"\nclears both baselines: {', '.join(winners) if winners else 'nothing'}")
    return 0


def train(args: argparse.Namespace) -> int:
    """Fit the production model, save it, register it, and optionally make it live."""
    source = _source(args)
    run = training.train(source, model_name=args.model)
    print(run.summary())

    name = training.artefact_name(run)
    path = persistence.save(run.artefact, name, directory=_artefacts(args))
    entry = _registry(args).register(run.manifest, name, note=args.note)
    print(f"\nsaved   {path}")
    print(f"registered as version {entry.version}")

    if args.promote:
        try:
            _registry(args).promote(entry.version, force=args.force)
        except registry.RegistryError as refusal:
            print(f"\nnot promoted: {refusal}", file=sys.stderr)
            return 1
        print(f"promoted version {entry.version}; it is now serving")
    return 0


def show_registry(args: argparse.Namespace) -> int:
    """What has been trained, what is live, and — with --promote — change which."""
    known = _registry(args)
    if args.promote is not None:
        try:
            entry = known.promote(args.promote, metric=args.metric, force=args.force)
        except registry.RegistryError as refusal:
            print(refusal, file=sys.stderr)
            return 1
        print(f"version {entry.version} ({entry.model_name}) is now serving\n")

    print(known.table())
    live = known.current()
    print(f"\nserving: {'version ' + str(live.version) if live else 'nothing promoted yet'}")
    return 0


def predict(args: argparse.Namespace) -> int:
    """One order in, one decision out, through the live model.

    The order arrives as JSON rather than as sixteen command-line flags. A flag per field
    would be unreadable, and worse, it would invite the caller to omit one and get a
    default — and a silently defaulted feature is a prediction about a different order.
    `single_order` refuses a field list that is not exactly right.
    """
    if args.template:
        print(json.dumps(dict.fromkeys(ORDER_FIELDS, ""), indent=2))
        return 0

    if args.order is None:
        raise SystemExit("give an order JSON file, or --template to print a blank one")

    known = _registry(args)
    live = known.current()
    if live is None:
        raise SystemExit("nothing is promoted. Run `chainsight train --promote` first.")

    try:
        artefact = persistence.load(live.artefact, directory=_artefacts(args))
    except persistence.ArtefactError as refusal:
        print(refusal, file=sys.stderr)
        return 1

    fields = json.loads(Path(args.order).read_text(encoding="utf-8"))
    frame = single_order(**fields)
    probability = float(artefact.predict_proba(frame).iloc[0])
    verdict = decision.decide(probability, float(frame["Order Item Total"].iloc[0]))

    print(_render(verdict, live.model_name))
    return 0


def _render(verdict: decision.Decision, model_name: str) -> str:
    """The decision as an operator reads it: the action first, the arithmetic under it."""
    return "\n".join(
        [
            f"{verdict.priority.value.upper()}  {verdict.recommendation}",
            "",
            f"  late-delivery risk   {verdict.probability:.4f}"
            f"  (flagged above {verdict.threshold:.4f})",
            f"  order total          {verdict.order_total:,.2f}",
            f"  expected profit      {verdict.expected_profit:,.2f}",
            f"  value at risk        {verdict.value_at_risk:,.2f}",
            f"  net benefit of act   {verdict.net_benefit:,.2f}",
            "",
            f"  model: {model_name}",
        ]
    )


def _add_source(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data", default=str(FULL_DATA), help="the source CSV")
    parser.add_argument("--sample", action="store_true", help="use the committed 500-row slice")


def _add_artefacts(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artefacts",
        default=str(persistence.ARTEFACTS_DIR),
        help="the directory artefacts are loaded from, and never outside it",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chainsight", description=_DESCRIPTION)
    subcommands = parser.add_subparsers(dest="command", required=True)

    described = subcommands.add_parser("describe", help="what the table is, and what ingest drops")
    _add_source(described)
    described.set_defaults(run=describe)

    leaked = subcommands.add_parser("leakage", help="what the forbidden columns are worth")
    _add_source(leaked)
    leaked.set_defaults(run=leak)

    compared = subcommands.add_parser("compare", help="every candidate against the baselines")
    _add_source(compared)
    compared.add_argument("--only", nargs="+", metavar="MODEL", help=f"one of: {models.names()}")
    compared.add_argument("--margin", action="store_true", help="the margin table instead")
    compared.set_defaults(run=rank)

    trained = subcommands.add_parser("train", help="fit the production model and register it")
    _add_source(trained)
    _add_artefacts(trained)
    trained.add_argument("--model", default=training.PRODUCTION_MODEL, help="which candidate")
    trained.add_argument("--note", default="", help="why this run happened")
    trained.add_argument("--promote", action="store_true", help="make it live if it wins")
    trained.add_argument("--force", action="store_true", help="promote even if it loses")
    trained.set_defaults(run=train)

    listed = subcommands.add_parser("registry", help="what is trained and what is serving")
    _add_artefacts(listed)
    listed.add_argument("--promote", type=int, metavar="VERSION", help="make this version live")
    listed.add_argument("--metric", default=registry.DEFAULT_METRIC, help="what to compare on")
    listed.add_argument("--force", action="store_true", help="promote even if it loses")
    listed.set_defaults(run=show_registry)

    predicted = subcommands.add_parser("predict", help="one order, one decision")
    _add_artefacts(predicted)
    predicted.add_argument("order", nargs="?", help="a JSON file of the at-order fields")
    predicted.add_argument("--template", action="store_true", help="print a blank order and exit")
    predicted.set_defaults(run=predict)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.run
    return handler(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
