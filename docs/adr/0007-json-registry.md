# 0007 — A JSON registry with a compare-then-promote guard, not MLflow

**Status:** accepted

## Context

Trained models need somewhere to live, and the application needs to know which one is
serving. MLflow does this, and a great deal more.

## Decision

What is actually needed is a list of trained models, their held-out scores, and a note of
which one is serving traffic. That is a JSON file — and a JSON file can be read in a text
editor in two years by somebody with no tooling installed.

Two behaviours in it are deliberate:

**Registering never promotes.** A freshly trained model is a candidate. Serving it because it
happens to be last in the list is the accident the registry exists to prevent.

**Promoting compares first.** Retraining produces a model that is *newer*, and newer is not
better — a retrain on a bad slice, or on a catalogue that has turned over, can score below the
model already serving. `registry.promote` compares the candidate against the incumbent on
ranking and refuses a regression. `force` exists so that overriding appears in the argument
list rather than happening by default.

A candidate that does not record the metric is refused rather than promoted on the assumption
it would have won. That case is real: `SVC` has no `predict_proba`, so a model built from it
carries no ranking score at all.

## Consequences

There is **one** implementation of "is the new model better", and both the CLI and the admin
route call it. A second copy living in a request handler is a second copy that will disagree.

The web application's `model_versions` table is a **read model** refreshed from the JSON,
never written to independently — so there is one answer to "which model is live" rather than
two that can drift.

A refused promotion is recorded in `training_runs` with its reason. The guard turning a
retrain down is the interesting event: it is why the serving model is three weeks old, and a
control tower that logs only its successes cannot answer that.

Artefacts themselves are treated as code, because `joblib.load` unpickles and unpickling
executes. The loader takes a **name**, never a path, resolves it inside the artefacts
directory and refuses anything resolving outside; and every artefact carries a manifest with
the feature-set hash, the dataset hash and four library versions, any mismatch being a hard
error rather than a warning.
