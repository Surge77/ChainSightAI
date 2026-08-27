"""Which artefact is live, which ones came before, and what promoting costs.

MLflow does this and a great deal more. It is not used here for the reason the rest of the
project gives for everything it does not use: what is actually needed is a list of trained
models, their held-out scores, and a note of which one is serving traffic. That is a JSON
file, and a JSON file can be read in a text editor two years from now by somebody with no
tooling installed.

The one piece of judgement in this module is `promote`. Retraining produces a model that
is *newer*, and newer is not better — a retrain on a bad slice, or on a catalogue that has
turned over, can score below the model already serving. So promotion compares the candidate
against the incumbent on a named metric and refuses when it loses, and `force` exists so
that overriding the guard is a deliberate act that appears in the argument list rather than
something that happens by default.

The default metric is ranking rather than accuracy, matching the choice `docs/results.md`
argues for: on this dataset accuracy separates the models by less than a point while
ranking separates them by seven.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from chainsight.evaluate import as_markdown
from chainsight.persistence import ARTEFACTS_DIR, Manifest

#: The registry file, inside the artefacts directory it describes.
REGISTRY_NAME = "registry.json"

#: What `promote` compares on. Ranking, because that is what the control tower consumes.
DEFAULT_METRIC = "roc auc"


class RegistryError(Exception):
    """The registry refuses the change, and says which one and why."""


@dataclass(frozen=True)
class Version:
    """One trained model, as the registry records it."""

    version: int
    artefact: str
    model_name: str
    created: str
    dataset_hash: str
    feature_hash: str
    scores: dict[str, float] = field(default_factory=dict)
    note: str = ""

    def score(self, metric: str) -> float | None:
        return self.scores.get(metric)


@dataclass(frozen=True)
class Registry:
    """A JSON file listing trained models, and which one is live."""

    path: Path = ARTEFACTS_DIR / REGISTRY_NAME

    def _read(self) -> dict[str, object]:
        if not self.path.is_file():
            return {"current": None, "versions": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, state: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    def versions(self) -> list[Version]:
        """Every registered model, oldest first."""
        raw = self._read()["versions"]
        entries = raw if isinstance(raw, list) else []
        return [Version(**entry) for entry in entries]

    def get(self, version: int) -> Version:
        for entry in self.versions():
            if entry.version == version:
                return entry
        raise RegistryError(f"no version {version} in {self.path}")

    def current(self) -> Version | None:
        """The promoted model, or `None` when nothing has been promoted yet.

        `None` rather than "the newest" on purpose. A freshly trained model that nobody
        promoted is a candidate, and serving it because it happens to be last in the list
        is exactly the accident `promote` exists to prevent.
        """
        marker = self._read()["current"]
        return self.get(int(marker)) if isinstance(marker, int) else None

    def register(self, manifest: Manifest, artefact: str, *, note: str = "") -> Version:
        """Add a trained model to the list. Registering never promotes."""
        state = self._read()
        existing = self.versions()
        entry = Version(
            version=max((v.version for v in existing), default=0) + 1,
            artefact=artefact,
            model_name=manifest.model_name,
            created=manifest.created,
            dataset_hash=manifest.dataset_hash,
            feature_hash=manifest.feature_hash,
            scores=dict(manifest.scores),
            note=note,
        )
        state["versions"] = [asdict(v) for v in [*existing, entry]]
        self._write(state)
        return entry

    def promote(
        self,
        version: int,
        *,
        metric: str = DEFAULT_METRIC,
        force: bool = False,
    ) -> Version:
        """Make one version live, unless it scores below the one already live.

        A candidate that does not record the metric cannot be compared, and is refused
        rather than promoted on the assumption it would have won. That case is real: `SVC`
        has no `predict_proba`, so a model trained from it carries no ranking score at all.
        """
        candidate = self.get(version)
        incumbent = self.current()

        if incumbent is not None and incumbent.version != version and not force:
            self._refuse_regression(candidate, incumbent, metric)

        state = self._read()
        state["current"] = version
        self._write(state)
        return candidate

    def _refuse_regression(self, candidate: Version, incumbent: Version, metric: str) -> None:
        challenger, standing = candidate.score(metric), incumbent.score(metric)
        if challenger is None or standing is None:
            raise RegistryError(
                f"version {candidate.version} cannot be compared with version "
                f"{incumbent.version} on {metric!r}: one of them does not record it. "
                "Score both on the same metric, or promote with force."
            )
        if challenger < standing:
            raise RegistryError(
                f"version {candidate.version} scores {challenger:.4f} on {metric!r} against "
                f"version {incumbent.version}'s {standing:.4f}. Newer is not better. "
                "Promote with force if this is deliberate."
            )

    def table(self) -> str:
        """The registry as a markdown table, for the CLI and the admin page."""
        entries = self.versions()
        if not entries:
            return "no models registered."

        live = self.current()
        rows = {
            f"{entry.version}{' *' if live and entry.version == live.version else ''}": {
                "model": entry.model_name,
                "created": entry.created,
                **{key: round(value, 4) for key, value in sorted(entry.scores.items())},
            }
            for entry in entries
        }
        return as_markdown(pd.DataFrame(rows).T, corner="version")
