"""The one place the application touches a model, and the one place it writes a prediction.

Loading a random forest takes long enough that doing it per request would be visible, so the
live artefact is cached. The cache is keyed on the registry's promoted version rather than
on time, which means a promotion made from the admin page — or from `chainsight registry`
in another terminal — takes effect on the next request without a restart, and nothing has to
guess how long a cached model is still correct for.

Predictions are written, not recomputed. Every field of `decision.Decision` goes into the
row, because the cost model is editable: recomputing a report on read would show last week's
order with this week's costs and imply those costs were the reason for last week's priority.
A stored decision is a record of what the system actually said.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from chainsight import decision, persistence, registry
from chainsight.encoding import CategoryCodes
from chainsight.features import single_order
from chainsight_web.tables import DecisionConfig, ModelVersion, Order, Prediction


class ServiceError(RuntimeError):
    """The application cannot serve a prediction, and the message says why."""


@dataclass
class ModelService:
    """The live artefact, loaded once and reloaded when the registry promotes another."""

    artefacts: Path
    _cached: tuple[int, persistence.Artefact] | None = field(default=None, repr=False)

    @property
    def known(self) -> registry.Registry:
        return registry.Registry(path=self.artefacts / registry.REGISTRY_NAME)

    def live(self) -> tuple[registry.Version, persistence.Artefact]:
        """The promoted model, loading it only when the promoted version has changed."""
        entry = self.known.current()
        if entry is None:
            raise ServiceError(
                "no model has been promoted, so there is nothing to predict with. "
                "Train one from the admin pages, or run `chainsight train --promote`."
            )

        if self._cached is None or self._cached[0] != entry.version:
            self._cached = (entry.version, self._load(entry))
        return entry, self._cached[1]

    def _load(self, entry: registry.Version) -> persistence.Artefact:
        try:
            return persistence.load(entry.artefact, directory=self.artefacts)
        except persistence.ArtefactError as refusal:
            # The loader's refusals are the interesting ones -- a feature-set mismatch, a
            # library that has moved -- and passing the sentence through keeps the reason
            # visible instead of turning it into a bare 500.
            raise ServiceError(f"the promoted model cannot be loaded: {refusal}") from refusal

    def probability_for(self, order: Order) -> tuple[registry.Version, float]:
        """The late-delivery probability for one stored order, through the live model."""
        entry, artefact = self.live()
        frame = single_order(**order.as_fields())
        return entry, float(artefact.predict_proba(frame).iloc[0])

    def forget(self) -> None:
        """Drop the cached artefact. Used after a retrain, and by the tests."""
        self._cached = None


def categories_of(artefact: persistence.Artefact) -> dict[str, list[str]]:
    """The category values the live model was actually fitted on, per column.

    The order form's dropdowns come from here rather than from a hand-written list. Both
    encoders tolerate a value they have never seen -- `CategoryCodes` maps it to `UNSEEN`
    and the one-hot encoder produces an all-zero block -- so a free-text field would not
    crash. It would do something worse: accept a plausible-looking product name and predict
    from a feature that is uniformly zero, which is a confident answer about nothing.
    """
    codes = artefact.space.codes
    if isinstance(codes, CategoryCodes):
        return {name: sorted(mapping) for name, mapping in codes.mappings.items()}

    return {
        name: sorted(str(value) for value in values)
        for name, values in zip(codes.sources, codes.encoder.categories_, strict=True)
    }


def costs_in(session: Session) -> decision.CostModel:
    """The admin's cost model, or the documented defaults when nobody has edited them.

    The defaults are not a fallback for an error case; they are the numbers
    `docs/decision_engine.md` argues for, and an untouched installation should behave the
    way the document describes.
    """
    stored = session.scalars(
        select(DecisionConfig).order_by(DecisionConfig.updated_at.desc())
    ).first()
    if stored is None:
        return decision.CostModel()

    return decision.CostModel(
        intervention=stored.intervention,
        margin_lost_when_late=stored.margin_lost_when_late,
        fixed_penalty_when_late=stored.fixed_penalty_when_late,
        mean_margin=stored.mean_margin,
        typical_order_value=stored.typical_order_value,
        critical_above=stored.critical_above,
        high_above=stored.high_above,
        monitor_above=stored.monitor_above,
    )


def predict_for(session: Session, service: ModelService, order: Order) -> Prediction:
    """Predict, decide, store, and hand back the row that was written."""
    entry, probability = service.probability_for(order)
    verdict = decision.decide(probability, order.order_total, costs_in(session))

    row = Prediction(
        order_id=order.id,
        model_version=entry.version,
        model_name=entry.model_name,
        probability=verdict.probability,
        threshold=verdict.threshold,
        expected_profit=verdict.expected_profit,
        value_at_risk=verdict.value_at_risk,
        net_benefit=verdict.net_benefit,
        priority=verdict.priority.value,
        recommendation=verdict.recommendation,
    )
    session.add(row)
    session.commit()
    return row


def sync_versions(session: Session, known: registry.Registry) -> int:
    """Refresh the `model_versions` read model from the JSON registry.

    The registry is the authority: it is what the promotion guard runs against and what
    `chainsight train` writes. This copies it into a table so predictions can join to it,
    and rewrites `is_live` from scratch each time rather than trying to keep two ideas of
    which model is serving in step.
    """
    live = known.current()
    existing = {row.version: row for row in session.scalars(select(ModelVersion))}

    for entry in known.versions():
        row = existing.get(entry.version)
        if row is None:
            row = ModelVersion(version=entry.version)
            session.add(row)
        row.artefact = entry.artefact
        row.model_name = entry.model_name
        row.trained_at = entry.created
        row.dataset_hash = entry.dataset_hash
        row.feature_hash = entry.feature_hash
        row.scores = dict(entry.scores)
        row.note = entry.note
        row.is_live = live is not None and live.version == entry.version

    session.commit()
    return len(known.versions())
