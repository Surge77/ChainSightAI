"""Fetch the DataCo Smart Supply Chain dataset into `data/raw/`, and prove it is the right one.

    python scripts/fetch_data.py            # download if absent, then verify
    python scripts/fetch_data.py --verify   # verify what is already on disk, download nothing
    python scripts/fetch_data.py --force    # download again over an existing copy

The dataset is ~92 MB and is not committed. `data/dataset_manifest.json` records the
SHA-256 of every file this project was built against, so a checkout can prove it is
looking at the same bytes rather than at a re-upload with a column quietly renamed. A
mismatch is an error, not a warning: silently training on a different file produces
numbers that disagree with `docs/results.md` for reasons nobody will find.

The archive also contains `tokenized_access_logs.csv`, a 95 MB clickstream table that
shares no key with the order table. It is deleted after extraction rather than left to
confuse a reader, and `data/dataset_manifest.json` records that it was.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW = REPO_ROOT / "data" / "raw"
MANIFEST = REPO_ROOT / "data" / "dataset_manifest.json"

READ_SIZE = 1 << 20


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(READ_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(manifest: dict) -> list[str]:
    """Return one message per file that is missing or does not match. Empty means good."""
    problems: list[str] = []
    for name, expected in manifest["files"].items():
        path = RAW / name
        if not path.is_file():
            if expected.get("required", True):
                problems.append(f"{name}: missing")
            continue
        actual_size = path.stat().st_size
        if actual_size != expected["bytes"]:
            problems.append(f"{name}: {actual_size} bytes, manifest says {expected['bytes']}")
            continue
        actual_hash = sha256(path)
        if actual_hash != expected["sha256"]:
            problems.append(
                f"{name}: sha256 {actual_hash[:16]}..., manifest says {expected['sha256'][:16]}..."
            )
    return problems


def download(slug: str) -> None:
    """Shell out to the Kaggle CLI.

    The argument vector is fixed and `shell` is left False, so nothing here can be turned
    into a command by a surprising value. The one variable, the dataset slug, comes from
    the committed manifest rather than from the caller.
    """
    kaggle = shutil.which("kaggle")
    if kaggle is None:
        raise SystemExit(MANUAL_INSTRUCTIONS)

    RAW.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [kaggle, "datasets", "download", "-d", slug, "-p", str(RAW), "--unzip"],
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "the Kaggle CLI exited non-zero. Most often this is authentication: run\n"
            "`kaggle datasets list` on its own to see the real error.\n" + MANUAL_INSTRUCTIONS
        )


MANUAL_INSTRUCTIONS = """
Download it by hand instead:

  1. https://www.kaggle.com/datasets/shashwatwork/dataco-smart-supply-chain-for-big-data-analysis
  2. Unzip DataCoSupplyChainDataset.csv into data/raw/
  3. python scripts/fetch_data.py --verify

The dataset is CC0-1.0, so a Kaggle account is the only barrier, not a licence.
""".strip()


def discard_unused(manifest: dict) -> list[str]:
    removed: list[str] = []
    for name in manifest.get("discarded", {}):
        path = RAW / name
        if path.is_file():
            path.unlink()
            removed.append(name)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify", action="store_true", help="check what is on disk, download nothing"
    )
    parser.add_argument("--force", action="store_true", help="download again over an existing copy")
    args = parser.parse_args(argv)

    manifest = load_manifest()
    required = [name for name, spec in manifest["files"].items() if spec.get("required", True)]
    have_all = all((RAW / name).is_file() for name in required)

    if not args.verify and (args.force or not have_all):
        print(f"downloading {manifest['kaggle_slug']} ({manifest['license']}) ...")
        download(manifest["kaggle_slug"])
        for name in discard_unused(manifest):
            print(f"discarded {name} - see data/dataset_manifest.json for why")

    problems = verify(manifest)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        print(
            "\nThis is not the file this project was built against. Re-download it, or "
            "update data/dataset_manifest.json in a commit that says why the bytes moved.",
            file=sys.stderr,
        )
        return 1

    spec = manifest["files"]["DataCoSupplyChainDataset.csv"]
    print(
        f"verified: DataCoSupplyChainDataset.csv, {spec['rows']:,} rows x {spec['columns']} "
        f"columns, sha256 {spec['sha256'][:16]}..."
    )
    print(f"encoding is {manifest['encoding']} - {manifest['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
