"""The fetch script's job is to notice when the file on disk is not the file we expect.

The tests point `fetch_data.RAW` at a temp directory so nothing here depends on whether a
93 MB download happens to be present, and so a failing assertion can never delete it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fetch_data
import pytest


@pytest.fixture
def raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "raw"
    directory.mkdir()
    monkeypatch.setattr(fetch_data, "RAW", directory)
    return directory


def manifest_for(payload: bytes, *, extra: dict | None = None) -> dict:
    spec = {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "required": True,
    }
    return {"files": {"data.csv": spec}, "discarded": extra or {}}


def test_a_matching_file_reports_no_problems(raw: Path) -> None:
    payload = b"Type,Sales\nDEBIT,314.6\n"
    (raw / "data.csv").write_bytes(payload)

    assert fetch_data.verify(manifest_for(payload)) == []


def test_a_missing_required_file_is_a_problem(raw: Path) -> None:
    problems = fetch_data.verify(manifest_for(b"anything"))

    assert len(problems) == 1
    assert "missing" in problems[0]


def test_an_optional_file_may_be_absent(raw: Path) -> None:
    manifest = manifest_for(b"anything")
    manifest["files"]["data.csv"]["required"] = False

    assert fetch_data.verify(manifest) == []


def test_a_file_of_the_wrong_length_is_caught_before_it_is_hashed(raw: Path) -> None:
    manifest = manifest_for(b"the expected payload")
    (raw / "data.csv").write_bytes(b"short")

    problems = fetch_data.verify(manifest)

    assert len(problems) == 1
    assert "bytes" in problems[0]


def test_a_file_of_the_right_length_but_wrong_content_is_caught(raw: Path) -> None:
    """The case a size check alone would wave through: one column silently renamed."""
    manifest = manifest_for(b"Type,Sales\nDEBIT,314.6\n")
    (raw / "data.csv").write_bytes(b"Type,Total\nDEBIT,314.6\n")

    problems = fetch_data.verify(manifest)

    assert len(problems) == 1
    assert "sha256" in problems[0]


def test_discarding_removes_only_what_the_manifest_names(raw: Path) -> None:
    (raw / "data.csv").write_bytes(b"keep me")
    (raw / "logs.csv").write_bytes(b"95 megabytes of clickstream")
    manifest = manifest_for(b"keep me", extra={"logs.csv": "unrelated to any question asked here"})

    removed = fetch_data.discard_unused(manifest)

    assert removed == ["logs.csv"]
    assert not (raw / "logs.csv").exists()
    assert (raw / "data.csv").exists()


def test_discarding_is_quiet_when_there_is_nothing_to_discard(raw: Path) -> None:
    manifest = manifest_for(b"x", extra={"logs.csv": "already gone"})

    assert fetch_data.discard_unused(manifest) == []


def test_the_committed_manifest_is_readable_and_names_the_main_table() -> None:
    manifest = fetch_data.load_manifest()

    assert manifest["encoding"] == "latin-1"
    assert manifest["license"] == "CC0-1.0"
    main = manifest["files"]["DataCoSupplyChainDataset.csv"]
    assert main["rows"] == 180519
    assert main["columns"] == 53
    assert len(main["sha256"]) == 64


def test_verify_mode_never_downloads(raw: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--verify` on an empty directory must report the gap, not go and fill it."""

    def explode(slug: str) -> None:
        raise AssertionError(f"download() was called with {slug!r} under --verify")

    monkeypatch.setattr(fetch_data, "download", explode)
    monkeypatch.setattr(
        fetch_data, "load_manifest", lambda: json.loads(json.dumps(manifest_for(b"absent")))
    )

    assert fetch_data.main(["--verify"]) == 1
