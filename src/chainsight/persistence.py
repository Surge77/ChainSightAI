"""Save a fitted model, and refuse to load one that would quietly be wrong.

`joblib.load` unpickles, and unpickling executes arbitrary code in the current process.
Loading an artefact somebody sent you is equivalent to running a script they sent you, so
this module never takes a path from a caller. It takes a *name*, resolves it inside the
artefacts directory, and refuses anything that resolves outside — which is what
`SECURITY.md` promises, and this is the file that has to keep the promise rather than
restate it.

The second job is the quieter one. An estimator is fitted against a feature matrix and
indexes it positionally forever after, so a model served against the wrong columns does not
raise: it predicts, confidently, and the wrongness is invisible from the outside. The
manifest exists to make that case loud. It records the feature-set hash, the training
dataset hash and the versions of every library whose objects are inside the pickle, and
`load` checks them before handing the artefact back.

A version mismatch is a hard error rather than a warning. The dependencies are pinned
exactly in `pyproject.toml` for the same reason: an artefact that loads under a scikit-learn
it was not fitted under is the failure mode where everything appears to work. The fix is to
retrain, which costs minutes, and the CLI says so.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from chainsight.encoding import Encoding
from chainsight.features import FeatureSpace

#: Where artefacts live. Matches the `artifacts/` entry in `.gitignore`; nothing in this
#: repository ships a pre-trained binary a reader is invited to load.
ARTEFACTS_DIR = Path("artifacts")

#: The libraries whose objects are inside the pickle. A drift in any of them changes what
#: `joblib.load` reconstructs, so all four are recorded and all four are checked.
PINNED_LIBRARIES: tuple[str, ...] = ("scikit-learn", "numpy", "pandas", "joblib")

_SUFFIX = ".joblib"


class ArtefactError(Exception):
    """The artefact cannot be trusted, so it is not returned."""


class UnsafePathError(ArtefactError):
    """The requested name resolves outside the artefacts directory."""


class ManifestMismatchError(ArtefactError):
    """The artefact and the environment disagree about something load-bearing."""


def library_versions() -> dict[str, str]:
    """The installed version of everything the pickle depends on.

    A library that is somehow absent records as `absent` rather than raising here, so the
    mismatch is reported by `Manifest.verify` with the rest of the comparison instead of
    from inside a dictionary comprehension.
    """
    installed = {}
    for name in PINNED_LIBRARIES:
        try:
            installed[name] = version(name)
        except PackageNotFoundError:  # pragma: no cover - every one is a hard dependency
            installed[name] = "absent"
    return installed


def feature_hash(space: FeatureSpace) -> str:
    """A digest of the fitted column order and the encoding that produced it.

    The column *order* is included deliberately. The same columns in a different order is
    exactly the input that predicts without complaining.
    """
    material = "\n".join([space.encoding, *space.columns])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def dataset_hash(source: pd.DataFrame | Path | str) -> str:
    """A digest of the training data: the file's bytes, or the frame's contents.

    A path is hashed as bytes so the number matches `data/dataset_manifest.json` and
    `scripts/fetch_data.py --verify`. A frame is hashed through `hash_pandas_object`, which
    is row-order dependent and therefore catches a reshuffled training slice too.
    """
    if isinstance(source, str | Path):
        digest = hashlib.sha256()
        with Path(source).open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()

    rows = pd.util.hash_pandas_object(source, index=False).to_numpy()
    header = "\n".join(str(name) for name in source.columns).encode("utf-8")
    return hashlib.sha256(header + rows.tobytes()).hexdigest()


@dataclass(frozen=True)
class Manifest:
    """What this artefact is, what produced it, and what it must be loaded against."""

    model_name: str
    encoding: Encoding
    feature_hash: str
    dataset_hash: str
    rows_trained: int
    threshold: float
    scores: dict[str, float] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    libraries: dict[str, str] = field(default_factory=library_versions)
    created: str = ""

    def __post_init__(self) -> None:
        if not self.created:
            # `frozen=True` means the timestamp cannot be assigned normally, and a default
            # factory would fix the value at import rather than at save.
            object.__setattr__(self, "created", datetime.now(UTC).isoformat(timespec="seconds"))

    def verify(self, space: FeatureSpace) -> None:
        """Raise unless this artefact can be served here, naming what disagrees.

        Both checks answer the same question — is the thing being reconstructed the thing
        that was fitted — and both are errors rather than warnings, because the symptom of
        ignoring either is a plausible-looking prediction.
        """
        rebuilt = feature_hash(space)
        if rebuilt != self.feature_hash:
            raise ManifestMismatchError(
                f"the artefact's feature space hashes to {rebuilt[:12]} but its manifest "
                f"records {self.feature_hash[:12]}. The model would read the wrong column "
                "in the wrong slot. Retrain rather than loading this."
            )

        drifted = {
            name: (recorded, installed)
            for name, recorded in self.libraries.items()
            if (installed := library_versions().get(name, "absent")) != recorded
        }
        if drifted:
            detail = ", ".join(
                f"{name} was {was} and is {now}" for name, (was, now) in sorted(drifted.items())
            )
            raise ManifestMismatchError(
                f"this artefact was fitted under different libraries: {detail}. "
                "Unpickling an estimator across versions is the failure that looks like a "
                "working system. Retrain with `chainsight train`."
            )

    def as_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    def summary(self) -> str:
        scored = "  ".join(f"{key} {value:.4f}" for key, value in sorted(self.scores.items()))
        return "\n".join(
            [
                f"{self.model_name}  ({self.encoding} features, trained on "
                f"{self.rows_trained:,} rows)",
                f"created {self.created}",
                f"features {self.feature_hash[:12]}  dataset {self.dataset_hash[:12]}",
                f"threshold {self.threshold:.4f}",
                f"scores   {scored}" if scored else "scores   none recorded",
            ]
        )


@dataclass(frozen=True)
class Artefact:
    """A fitted feature space, the estimator fitted on it, and the manifest for both.

    The two travel together because they are only meaningful together. A `FeatureSpace`
    carries the category mappings, and an estimator handed a matrix built from a different
    mapping reads every category as a different one.
    """

    space: FeatureSpace
    estimator: Any
    manifest: Manifest

    def predict_proba(self, frame: pd.DataFrame) -> pd.Series:
        """The late-class probability for an ingested or operator-supplied frame."""
        probabilities = self.estimator.predict_proba(self.space.transform(frame))
        return pd.Series(probabilities[:, 1], index=frame.index, name="probability")


def resolve(name: str, *, directory: Path | None = None) -> Path:
    """The path this name refers to, or `UnsafePathError` if it refers anywhere else.

    Resolution happens before any comparison. `artifacts/../../etc/passwd` and a symlink
    both look like ordinary names until the filesystem has had its say, which is why the
    check is `Path.resolve()` and `is_relative_to` rather than a scan for `..`.
    """
    root = (directory or ARTEFACTS_DIR).resolve()
    candidate = (root / f"{name}{_SUFFIX}" if not name.endswith(_SUFFIX) else root / name).resolve()

    if not candidate.is_relative_to(root):
        raise UnsafePathError(
            f"{name!r} resolves to {candidate}, which is outside {root}. "
            "Artefacts are loaded by name from the artefacts directory only."
        )
    return candidate


def save(artefact: Artefact, name: str, *, directory: Path | None = None) -> Path:
    """Write the artefact and a readable manifest beside it, and refuse to overwrite.

    The manifest is written twice on purpose: inside the pickle, where `load` checks it,
    and as JSON next to it, where a person can read what an artefact is without unpickling
    it. Reading a `.joblib` to find out whether it is safe to read is not a workable order
    of operations.
    """
    path = resolve(name, directory=directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ArtefactError(f"{path.name} already exists; artefacts are never overwritten")

    joblib.dump(artefact, path)
    path.with_suffix(".json").write_text(artefact.manifest.as_json(), encoding="utf-8")
    return path


def load(name: str, *, directory: Path | None = None) -> Artefact:
    """Read an artefact by name, verified. Never takes a path from a caller."""
    path = resolve(name, directory=directory)
    if not path.is_file():
        raise ArtefactError(f"no artefact called {name!r} in {path.parent}")

    artefact = joblib.load(path)
    if not isinstance(artefact, Artefact):
        raise ArtefactError(
            f"{path.name} unpickled to {type(artefact).__name__}, not an Artefact. "
            "It was not written by this project."
        )

    artefact.manifest.verify(artefact.space)
    return artefact


def stored(directory: Path | None = None) -> list[str]:
    """The names of every artefact present, newest first."""
    root = (directory or ARTEFACTS_DIR).resolve()
    if not root.is_dir():
        return []
    found = sorted(root.glob(f"*{_SUFFIX}"), key=lambda path: path.stat().st_mtime, reverse=True)
    return [path.stem for path in found]
