"""Render the column table in `docs/data_audit.md` from the contract in `columns.py`.

    python scripts/render_audit.py           # rewrite the generated block
    python scripts/render_audit.py --check   # exit 1 if the committed block is stale

Fifty-three rows maintained by hand in two places drift within a week, and the drift is
invisible: the document keeps saying a column was dropped for a reason the code stopped
believing. Generating one from the other makes that impossible, and `--check` in CI makes
it impossible to commit the two out of step.

Only the block between the markers is touched. Everything above it is the argument, which
is written by a person because it is not derivable from a table.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chainsight.columns import COLUMNS
from chainsight.contract import Disposition

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "docs" / "data_audit.md"

BEGIN = "<!-- BEGIN GENERATED: python scripts/render_audit.py -->"
END = "<!-- END GENERATED -->"

_ORDER = [
    Disposition.USE,
    Disposition.TARGET,
    Disposition.DROP_LEAK,
    Disposition.DROP_PII,
    Disposition.DROP_ID,
    Disposition.DROP_DUPLICATE,
    Disposition.DROP_CONSTANT,
]


def summary() -> str:
    counts = {d: sum(1 for c in COLUMNS if c.disposition is d) for d in _ORDER}
    rows = "\n".join(f"| {d.value} | {counts[d]} |" for d in _ORDER)
    return f"| disposition | columns |\n|---|---:|\n{rows}\n| **total** | **{len(COLUMNS)}** |\n"


def table() -> str:
    header = "| # | column | available | disposition | why |\n|---:|---|---|---|---|\n"
    rows = "\n".join(
        f"| {i} | `{c.name}` | {c.availability.value} | {c.disposition.value} | {c.why} |"
        for i, c in enumerate(COLUMNS)
    )
    return header + rows + "\n"


def block() -> str:
    return f"{BEGIN}\n\n{summary()}\n{table()}\n{END}"


def rewritten(text: str) -> str:
    start = text.index(BEGIN)
    stop = text.index(END) + len(END)
    return text[:start] + block() + text[stop:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="do not write; exit 1 if stale")
    args = parser.parse_args(argv)

    current = DOC.read_text(encoding="utf-8")
    if BEGIN not in current or END not in current:
        print(f"{DOC.name} has lost its generated-block markers", file=sys.stderr)
        return 1

    updated = rewritten(current)
    if args.check:
        if updated != current:
            print(
                f"{DOC.name} is out of step with src/chainsight/columns.py.\n"
                "Run `python scripts/render_audit.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"{DOC.name} matches the column contract ({len(COLUMNS)} columns).")
        return 0

    DOC.write_text(updated, encoding="utf-8")
    print(f"wrote {len(COLUMNS)} columns into {DOC.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
