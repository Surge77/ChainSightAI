"""Fit the model that gets served, and record what it was fitted on.

`compare.py` answers "which of these is best" by fitting fourteen candidates and printing a
table. This module answers the different and narrower question a deployment asks: build the
one artefact the application will load, and attach enough provenance that a later reader can
tell what it is.

The production default is **one-hot random forest**, and the reason is in `docs/results.md`
rather than here: it is the best measured *ranking*, 0.7518 ROC-AUC against the rule
baseline's 0.7341, and ranking is the product. On accuracy it is within a point of a
four-line `if` statement, which is a fact the model card has to carry rather than one the
choice of default should hide.

The training path deliberately reuses `split.by_date`, `features.FeatureSpace.fit` and
`tuning.tune` rather than reimplementing any of them. A serving model fitted by a second
code path is the same class of bug as a second feature builder: the two agree until they
quietly do not.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from chainsight import compare, decision, evaluate, features, ingest, models, schema, split, tuning
from chainsight.persistence import Artefact, Manifest, dataset_hash, feature_hash

#: The model the application serves unless told otherwise. Chosen on ranking, not accuracy.
PRODUCTION_MODEL = "one-hot random forest"


@dataclass(frozen=True)
class TrainingRun:
    """One fit, its held-out scores, and the artefact it produced."""

    artefact: Artefact
    scores: dict[str, float]
    rows_trained: int
    rows_tested: int
    fold_score: float

    @property
    def manifest(self) -> Manifest:
        return self.artefact.manifest

    def summary(self) -> str:
        scored = "  ".join(f"{key} {value:.4f}" for key, value in self.scores.items())
        return "\n".join(
            [
                f"{self.manifest.model_name}: fitted on {self.rows_trained:,} orders, "
                f"scored on {self.rows_tested:,}",
                f"fold score (f1) {self.fold_score:.4f}",
                f"held out        {scored}",
                f"threshold       {self.manifest.threshold:.4f} "
                f"(derived from the cost model, not assumed)",
            ]
        )


def train(
    source: pd.DataFrame | Path | str,
    *,
    model_name: str = PRODUCTION_MODEL,
    costs: decision.CostModel | None = None,
) -> TrainingRun:
    """Fit one candidate on the training slice and score it once on the held-out slice.

    The validation slice is not used here. It exists for choosing between models, and that
    choice was made in `compare.py`; spending it again on the model already chosen would be
    tuning against a slice that had already been read.
    """
    candidate = models.by_name(model_name)
    frame = source if isinstance(source, pd.DataFrame) else ingest.ingest(source)
    parts = split.by_date(frame)

    space = features.FeatureSpace.fit(parts.train, encoding=candidate.encoding)
    X_train, X_test = space.transform(parts.train), space.transform(parts.test)
    Y_train, Y_test = parts.train[schema.LATE_TARGET], parts.test[schema.LATE_TARGET]

    tuned = tuning.tune(candidate, X_train, Y_train)
    scores = evaluate.classification_scores(Y_test, tuned.estimator.predict(X_test))
    probabilities = compare.probabilities_of(tuned.estimator, X_test)
    if probabilities is not None:
        scores |= evaluate.ranking_scores(Y_test, probabilities)

    manifest = Manifest(
        model_name=candidate.name,
        encoding=candidate.encoding,
        feature_hash=feature_hash(space),
        # The hash is of the whole ingested table rather than the training slice, because
        # the question a reader asks of an artefact is "which dataset is this", and the
        # split is reproducible from the dataset and `split.py`.
        dataset_hash=dataset_hash(source),
        rows_trained=tuned.rows_used,
        threshold=(costs or decision.CostModel()).threshold,
        scores=scores,
        parameters=dict(tuned.parameters),
    )
    return TrainingRun(
        artefact=Artefact(space=space, estimator=tuned.estimator, manifest=manifest),
        scores=scores,
        rows_trained=tuned.rows_used,
        rows_tested=len(parts.test),
        fold_score=tuned.fold_score,
    )


def artefact_name(run: TrainingRun) -> str:
    """A filename that says what the artefact is without opening it.

    The model name is slugified and the manifest's timestamp is folded in, so two runs of
    the same model in the same second collide — which `persistence.save` refuses rather
    than silently overwriting — and two runs a minute apart do not.
    """
    slug = run.manifest.model_name.replace(" ", "-")
    stamp = run.manifest.created.replace(":", "").replace("-", "").replace("+0000", "")
    return f"{slug}-{stamp}"
