"""Loading a model is a security boundary and a correctness boundary at once.

`joblib.load` unpickles, so the loader must never accept a path from a caller; and an
estimator indexes its features positionally, so a model served against the wrong columns
predicts confidently rather than raising. Both failures are silent, which is why they are
tested here rather than left to a docstring.
"""

from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from chainsight import ingest, persistence, split
from chainsight.features import FeatureSpace
from chainsight.persistence import (
    Artefact,
    ArtefactError,
    Manifest,
    ManifestMismatchError,
    UnsafePathError,
)

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_orders.csv"


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return ingest.ingest(SAMPLE)


@pytest.fixture(scope="module")
def space(frame: pd.DataFrame) -> FeatureSpace:
    return FeatureSpace.fit(split.by_date(frame).train)


@pytest.fixture
def manifest(space: FeatureSpace) -> Manifest:
    return Manifest(
        model_name="a test model",
        encoding=space.encoding,
        feature_hash=persistence.feature_hash(space),
        dataset_hash="0" * 64,
        rows_trained=100,
        threshold=0.2966,
        scores={"roc auc": 0.75},
    )


class _AlwaysLate:
    """A stand-in estimator, so these tests do not pay to fit a real one."""

    def predict_proba(self, X: pd.DataFrame) -> object:
        return np.column_stack([np.zeros(len(X)), np.ones(len(X))])


@pytest.fixture
def artefact(space: FeatureSpace, manifest: Manifest) -> Artefact:
    return Artefact(space=space, estimator=_AlwaysLate(), manifest=manifest)


class TestFeatureHash:
    def test_the_same_feature_space_hashes_the_same_way(self, space: FeatureSpace) -> None:
        assert persistence.feature_hash(space) == persistence.feature_hash(space)

    def test_reordering_the_columns_changes_the_hash(self, space: FeatureSpace) -> None:
        """The order is the point. The same columns in a different order predicts wrongly."""
        reversed_space = replace(space, columns=tuple(reversed(space.columns)))

        assert persistence.feature_hash(reversed_space) != persistence.feature_hash(space)

    def test_changing_the_encoding_changes_the_hash(self, space: FeatureSpace) -> None:
        assert persistence.feature_hash(replace(space, encoding="one-hot")) != (
            persistence.feature_hash(space)
        )


class TestDatasetHash:
    def test_a_file_hashes_to_its_bytes(self, tmp_path: Path) -> None:
        path = tmp_path / "orders.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")

        assert persistence.dataset_hash(path) == persistence.dataset_hash(str(path))

    def test_two_different_frames_hash_differently(self, frame: pd.DataFrame) -> None:
        assert persistence.dataset_hash(frame) != persistence.dataset_hash(frame.iloc[:-1])

    def test_reordering_rows_changes_the_hash(self, frame: pd.DataFrame) -> None:
        """A reshuffled training slice is a different training set, and says so."""
        assert persistence.dataset_hash(frame.iloc[::-1]) != persistence.dataset_hash(frame)


class TestResolve:
    def test_a_plain_name_lands_in_the_artefacts_directory(self, tmp_path: Path) -> None:
        assert persistence.resolve("model", directory=tmp_path).parent == tmp_path.resolve()

    def test_the_suffix_is_added_once(self, tmp_path: Path) -> None:
        with_suffix = persistence.resolve("model.joblib", directory=tmp_path)

        assert with_suffix == persistence.resolve("model", directory=tmp_path)

    def test_a_name_climbing_out_of_the_directory_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(UnsafePathError, match="outside"):
            persistence.resolve("../../etc/passwd", directory=tmp_path)

    def test_an_absolute_path_is_refused(self, tmp_path: Path) -> None:
        """A caller cannot ask for a file elsewhere by spelling out where it is."""
        with pytest.raises(UnsafePathError, match="outside"):
            persistence.resolve("C:/Windows/System32/config", directory=tmp_path)

    def test_the_default_directory_is_used_when_none_is_given(self) -> None:
        assert persistence.resolve("model").parent == persistence.ARTEFACTS_DIR.resolve()


class TestSaveAndLoad:
    def test_a_saved_artefact_comes_back_identical(
        self, artefact: Artefact, tmp_path: Path
    ) -> None:
        persistence.save(artefact, "model", directory=tmp_path)

        loaded = persistence.load("model", directory=tmp_path)

        assert loaded.manifest == artefact.manifest
        assert loaded.space.columns == artefact.space.columns

    def test_the_manifest_is_also_written_as_readable_json(
        self, artefact: Artefact, tmp_path: Path
    ) -> None:
        """Reading a joblib file to find out whether it is safe to read is the wrong order."""
        path = persistence.save(artefact, "model", directory=tmp_path)

        assert path.with_suffix(".json").is_file()
        assert "a test model" in path.with_suffix(".json").read_text(encoding="utf-8")

    def test_an_artefact_is_never_overwritten(self, artefact: Artefact, tmp_path: Path) -> None:
        persistence.save(artefact, "model", directory=tmp_path)

        with pytest.raises(ArtefactError, match="already exists"):
            persistence.save(artefact, "model", directory=tmp_path)

    def test_loading_a_name_that_is_not_there_names_the_directory(self, tmp_path: Path) -> None:
        with pytest.raises(ArtefactError, match="no artefact called"):
            persistence.load("absent", directory=tmp_path)

    def test_a_pickle_this_project_did_not_write_is_refused(self, tmp_path: Path) -> None:
        """`joblib.load` runs whatever is inside, so what came out is checked before use."""
        joblib.dump({"not": "an artefact"}, tmp_path / "hostile.joblib")

        with pytest.raises(ArtefactError, match="not an Artefact"):
            persistence.load("hostile", directory=tmp_path)

    def test_a_loaded_artefact_predicts_through_its_own_feature_space(
        self, artefact: Artefact, frame: pd.DataFrame, tmp_path: Path
    ) -> None:
        persistence.save(artefact, "model", directory=tmp_path)

        probabilities = persistence.load("model", directory=tmp_path).predict_proba(frame.head(3))

        assert list(probabilities) == [1.0, 1.0, 1.0]
        assert probabilities.name == "probability"


class TestVerify:
    def test_a_feature_hash_that_does_not_match_is_a_hard_error(
        self, space: FeatureSpace, manifest: Manifest
    ) -> None:
        """The whole point. A model reading the wrong column in the wrong slot does not raise."""
        wrong = replace(manifest, feature_hash="0" * 64)

        with pytest.raises(ManifestMismatchError, match="wrong column"):
            wrong.verify(space)

    def test_a_library_that_has_moved_since_fitting_is_a_hard_error(
        self, space: FeatureSpace, manifest: Manifest
    ) -> None:
        drifted = replace(manifest, libraries={"scikit-learn": "0.1.0"})

        with pytest.raises(ManifestMismatchError, match=r"scikit-learn was 0\.1\.0"):
            drifted.verify(space)

    def test_a_saved_artefact_with_a_tampered_manifest_will_not_load(
        self, artefact: Artefact, tmp_path: Path
    ) -> None:
        tampered = Artefact(
            space=artefact.space,
            estimator=artefact.estimator,
            manifest=replace(artefact.manifest, feature_hash="f" * 64),
        )
        persistence.save(tampered, "tampered", directory=tmp_path)

        with pytest.raises(ManifestMismatchError):
            persistence.load("tampered", directory=tmp_path)

    def test_the_matching_case_passes_silently(
        self, space: FeatureSpace, manifest: Manifest
    ) -> None:
        assert manifest.verify(space) is None


class TestManifest:
    def test_the_timestamp_is_stamped_at_save_not_at_import(self, manifest: Manifest) -> None:
        assert manifest.created.endswith("+00:00")

    def test_a_supplied_timestamp_is_kept(self, space: FeatureSpace) -> None:
        stamped = Manifest(
            model_name="m",
            encoding="codes",
            feature_hash=persistence.feature_hash(space),
            dataset_hash="0" * 64,
            rows_trained=1,
            threshold=0.5,
            created="2017-01-01T00:00:00+00:00",
        )

        assert stamped.created == "2017-01-01T00:00:00+00:00"

    def test_the_summary_says_what_the_artefact_is(self, manifest: Manifest) -> None:
        summary = manifest.summary()

        assert "a test model" in summary
        assert "roc auc 0.7500" in summary

    def test_a_manifest_with_no_scores_says_so_rather_than_printing_nothing(
        self, manifest: Manifest
    ) -> None:
        assert "none recorded" in replace(manifest, scores={}).summary()

    def test_every_pinned_library_is_recorded(self, manifest: Manifest) -> None:
        assert set(manifest.libraries) == set(persistence.PINNED_LIBRARIES)


class TestStored:
    def test_an_absent_directory_lists_nothing(self, tmp_path: Path) -> None:
        assert persistence.stored(tmp_path / "never-created") == []

    def test_artefacts_are_listed_newest_first(self, artefact: Artefact, tmp_path: Path) -> None:
        persistence.save(artefact, "older", directory=tmp_path)
        time.sleep(0.01)
        persistence.save(artefact, "newer", directory=tmp_path)
        os.utime(tmp_path / "newer.joblib", (time.time() + 10, time.time() + 10))

        assert persistence.stored(tmp_path) == ["newer", "older"]
