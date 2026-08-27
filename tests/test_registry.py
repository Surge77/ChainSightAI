"""Retraining produces a newer model, and newer is not better.

Everything else in this module is bookkeeping over a JSON file. The behaviour worth testing
is the promotion guard: a retrain on a bad slice, or on a catalogue that has turned over,
can score below the model already serving, and promoting it because it is the most recent
thing in the list is the failure this file exists to prevent.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from chainsight.persistence import Manifest
from chainsight.registry import Registry, RegistryError, Version


def manifest_scoring(roc: float, *, name: str = "one-hot random forest") -> Manifest:
    return Manifest(
        model_name=name,
        encoding="one-hot",
        feature_hash="a" * 64,
        dataset_hash="b" * 64,
        rows_trained=1000,
        threshold=0.2966,
        scores={"roc auc": roc, "f1": 0.7},
    )


@pytest.fixture
def known(tmp_path: Path) -> Registry:
    return Registry(path=tmp_path / "registry.json")


class TestRegister:
    def test_an_empty_registry_has_nothing_and_serves_nothing(self, known: Registry) -> None:
        assert known.versions() == []
        assert known.current() is None

    def test_versions_are_numbered_from_one_and_never_reused(self, known: Registry) -> None:
        first = known.register(manifest_scoring(0.75), "artefact-a")
        second = known.register(manifest_scoring(0.76), "artefact-b")

        assert (first.version, second.version) == (1, 2)

    def test_registering_does_not_promote(self, known: Registry) -> None:
        """A trained model is a candidate. Serving it because it is last is the accident."""
        known.register(manifest_scoring(0.75), "artefact-a")

        assert known.current() is None

    def test_the_scores_and_hashes_are_carried_from_the_manifest(self, known: Registry) -> None:
        entry = known.register(manifest_scoring(0.75), "artefact-a", note="nightly")

        assert entry.score("roc auc") == 0.75
        assert entry.dataset_hash == "b" * 64
        assert entry.note == "nightly"

    def test_the_file_is_readable_by_a_person(self, known: Registry) -> None:
        """The reason this is JSON and not a database: no tooling needed in two years."""
        known.register(manifest_scoring(0.75), "artefact-a")

        state = json.loads(known.path.read_text(encoding="utf-8"))

        assert state["versions"][0]["model_name"] == "one-hot random forest"

    def test_a_registry_survives_being_reopened(self, tmp_path: Path) -> None:
        Registry(path=tmp_path / "registry.json").register(manifest_scoring(0.75), "a")

        assert len(Registry(path=tmp_path / "registry.json").versions()) == 1


class TestPromote:
    def test_the_first_promotion_has_nothing_to_beat(self, known: Registry) -> None:
        known.register(manifest_scoring(0.60), "artefact-a")

        promoted = known.promote(1)

        assert promoted.version == 1
        current = known.current()
        assert current is not None and current.version == 1

    def test_a_better_model_is_promoted(self, known: Registry) -> None:
        known.register(manifest_scoring(0.75), "artefact-a")
        known.register(manifest_scoring(0.78), "artefact-b")
        known.promote(1)

        known.promote(2)

        current = known.current()
        assert current is not None and current.version == 2

    def test_a_worse_model_is_refused_and_the_refusal_names_both_numbers(
        self, known: Registry
    ) -> None:
        known.register(manifest_scoring(0.78), "artefact-a")
        known.register(manifest_scoring(0.70), "artefact-b")
        known.promote(1)

        with pytest.raises(RegistryError, match=r"0\.7000.*0\.7800"):
            known.promote(2)

    def test_the_incumbent_is_still_serving_after_a_refusal(self, known: Registry) -> None:
        known.register(manifest_scoring(0.78), "artefact-a")
        known.register(manifest_scoring(0.70), "artefact-b")
        known.promote(1)

        with pytest.raises(RegistryError):
            known.promote(2)

        current = known.current()
        assert current is not None and current.version == 1

    def test_force_overrides_the_guard(self, known: Registry) -> None:
        """Overriding is deliberate, and appears in the argument list rather than by default."""
        known.register(manifest_scoring(0.78), "artefact-a")
        known.register(manifest_scoring(0.70), "artefact-b")
        known.promote(1)

        known.promote(2, force=True)

        current = known.current()
        assert current is not None and current.version == 2

    def test_promoting_what_is_already_live_is_allowed(self, known: Registry) -> None:
        """Otherwise a version could never be re-promoted after a rollback."""
        known.register(manifest_scoring(0.75), "artefact-a")
        known.promote(1)

        assert known.promote(1).version == 1

    def test_a_candidate_that_records_no_ranking_score_is_refused(self, known: Registry) -> None:
        """Real case: `SVC` has no `predict_proba`, so a model from it has no ranking score."""
        known.register(manifest_scoring(0.75), "artefact-a")
        known.register(replace(manifest_scoring(0.75), scores={"accuracy": 0.9}), "artefact-b")
        known.promote(1)

        with pytest.raises(RegistryError, match="does not record it"):
            known.promote(2)

    def test_a_different_metric_can_be_named(self, known: Registry) -> None:
        known.register(replace(manifest_scoring(0.78), scores={"f1": 0.60}), "artefact-a")
        known.register(replace(manifest_scoring(0.60), scores={"f1": 0.80}), "artefact-b")
        known.promote(1)

        assert known.promote(2, metric="f1").version == 2

    def test_promoting_a_version_that_does_not_exist_names_the_file(self, known: Registry) -> None:
        with pytest.raises(RegistryError, match="no version 9"):
            known.promote(9)


class TestTable:
    def test_an_empty_registry_says_so_rather_than_printing_a_header(self, known: Registry) -> None:
        assert known.table() == "no models registered."

    def test_the_live_version_is_marked(self, known: Registry) -> None:
        known.register(manifest_scoring(0.75), "artefact-a")
        known.register(manifest_scoring(0.78), "artefact-b")
        known.promote(2)

        rows = known.table().splitlines()

        assert "| 1 |" in rows[2]
        assert "| 2 * |" in rows[3]

    def test_the_table_is_readable_before_anything_is_promoted(self, known: Registry) -> None:
        known.register(manifest_scoring(0.75), "artefact-a")

        assert "one-hot random forest" in known.table()


def test_a_version_reports_a_missing_metric_as_none() -> None:
    entry = Version(
        version=1,
        artefact="a",
        model_name="m",
        created="2017-01-01T00:00:00+00:00",
        dataset_hash="0" * 64,
        feature_hash="0" * 64,
    )

    assert entry.score("roc auc") is None
