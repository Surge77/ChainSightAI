"""Loading the live model, and the three ways that goes wrong without crashing.

The interesting case is an artefact the loader refuses. `persistence.load` raises when the
feature-set hash or a library version disagrees, and the point of that refusal is lost if
the web layer turns it into a bare 500 — so the sentence is carried through, and a test
reads it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chainsight import persistence, registry, training
from chainsight.features import ORDER_FIELDS
from chainsight_web.security import hash_password
from chainsight_web.service import (
    ModelService,
    ServiceError,
    categories_of,
    costs_in,
    sync_versions,
)
from chainsight_web.tables import ORDER_COLUMNS, DecisionConfig, ModelVersion, Order, User
from conftest import SAMPLE


@pytest.fixture
def service(artefacts: Path) -> ModelService:
    return ModelService(artefacts=artefacts)


def test_the_orders_table_covers_exactly_the_fields_serving_needs() -> None:
    """The schema spells the fields out so that a change to the feature space fails here.

    A JSON blob would have been shorter and would have drifted silently: the serving path's
    whole promise is that it supplies the fields training used, and this is what checks it.
    """
    assert set(ORDER_COLUMNS) == set(ORDER_FIELDS)


def test_an_order_row_round_trips_into_the_dataset_vocabulary() -> None:
    """`as_fields` is what `features.single_order` is handed, so the names must be its names."""
    row = Order(**dict.fromkeys(ORDER_COLUMNS.values(), "a value"))

    assert set(row.as_fields()) == set(ORDER_FIELDS)


class TestLive:
    def test_it_returns_the_promoted_version_and_its_artefact(self, service: ModelService) -> None:
        entry, artefact = service.live()

        assert entry.version == 1
        assert artefact.manifest.model_name == "one-hot random forest"

    def test_the_artefact_is_loaded_once_and_then_cached(self, service: ModelService) -> None:
        """Loading a random forest per request would be visible to whoever is waiting."""
        _, first = service.live()
        _, second = service.live()

        assert first is second

    def test_forgetting_makes_the_next_call_load_again(self, service: ModelService) -> None:
        _, first = service.live()
        service.forget()
        _, second = service.live()

        assert first is not second

    def test_promoting_another_version_reloads_without_a_restart(
        self, service: ModelService, artefacts: Path
    ) -> None:
        """The cache is keyed on the promoted version, not on a clock."""
        _, first = service.live()

        run = training.train(SAMPLE, model_name="decision tree")
        name = training.artefact_name(run)
        persistence.save(run.artefact, name, directory=artefacts)
        service.known.register(run.manifest, name)
        service.known.promote(2, force=True)

        entry, second = service.live()

        assert entry.version == 2
        assert second is not first
        assert second.manifest.model_name == "decision tree"

    def test_nothing_promoted_is_a_sentence_rather_than_an_exception_nobody_can_read(
        self, empty_artefacts: Path
    ) -> None:
        with pytest.raises(ServiceError, match="No model is switched on yet"):
            ModelService(artefacts=empty_artefacts).live()

    def test_an_artefact_the_loader_refuses_carries_the_refusal_through(
        self, artefacts: Path
    ) -> None:
        """A feature-set mismatch is the interesting failure, and it must stay readable."""
        known = registry.Registry(path=artefacts / registry.REGISTRY_NAME)
        known.register(
            persistence.Manifest(
                model_name="a model nobody saved",
                encoding="one-hot",
                feature_hash="a" * 64,
                dataset_hash="b" * 64,
                rows_trained=1,
                threshold=0.2966,
                scores={"roc auc": 0.99},
            ),
            "never-written-to-disk",
        )
        known.promote(2)

        with pytest.raises(ServiceError, match="cannot be loaded"):
            ModelService(artefacts=artefacts).live()


class TestCategories:
    def test_a_one_hot_model_reports_the_levels_it_was_fitted_on(
        self, service: ModelService
    ) -> None:
        _, artefact = service.live()

        fitted = categories_of(artefact)

        assert "Standard Class" in fitted["Shipping Mode"]

    def test_an_integer_coded_model_reports_the_same_shape(self, service: ModelService) -> None:
        """Both encoders are in use in this project, and the form must work with either."""
        coded = training.train(SAMPLE, model_name="decision tree")

        fitted = categories_of(coded.artefact)

        assert "Standard Class" in fitted["Shipping Mode"]
        assert set(fitted) == set(categories_of(service.live()[1]))


class TestCosts:
    def test_an_untouched_installation_uses_the_documented_defaults(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions() as session:
            assert costs_in(session).intervention == 15.0

    def test_a_stored_configuration_replaces_them(
        self, sessions: sessionmaker[Session], admin_id: int
    ) -> None:
        with sessions() as session:
            session.add(_config(intervention=3.0, updated_by=admin_id))
            session.commit()

            assert costs_in(session).intervention == 3.0

    def test_the_most_recent_edit_wins(
        self, sessions: sessionmaker[Session], admin_id: int
    ) -> None:
        with sessions() as session:
            session.add(_config(intervention=3.0, updated_by=admin_id))
            session.commit()
            session.add(_config(intervention=7.0, updated_by=admin_id))
            session.commit()

            assert costs_in(session).intervention == 7.0


class TestSyncVersions:
    def test_it_copies_the_registry_into_the_table(
        self, sessions: sessionmaker[Session], service: ModelService
    ) -> None:
        with sessions() as session:
            assert sync_versions(session, service.known) == 1

            stored = session.scalars(select(ModelVersion)).one()
        assert stored.version == 1
        assert stored.is_live is True

    def test_running_it_twice_updates_rather_than_duplicates(
        self, sessions: sessionmaker[Session], service: ModelService
    ) -> None:
        with sessions() as session:
            sync_versions(session, service.known)
            sync_versions(session, service.known)

            assert len(list(session.scalars(select(ModelVersion)))) == 1

    def test_an_unpromoted_registry_marks_nothing_live(
        self, sessions: sessionmaker[Session], artefacts: Path
    ) -> None:
        known = registry.Registry(path=artefacts / "another-registry.json")
        known.register(
            persistence.Manifest(
                model_name="unpromoted",
                encoding="codes",
                feature_hash="a" * 64,
                dataset_hash="b" * 64,
                rows_trained=1,
                threshold=0.3,
            ),
            "unpromoted-artefact",
        )

        with sessions() as session:
            sync_versions(session, known)

            assert [row.is_live for row in session.scalars(select(ModelVersion))] == [False]


def _config(*, intervention: float, updated_by: int) -> DecisionConfig:
    return DecisionConfig(
        intervention=intervention,
        intervention_effectiveness=1.0,
        margin_lost_when_late=0.5,
        fixed_penalty_when_late=25.0,
        mean_margin=0.1196,
        typical_order_value=176.88,
        critical_above=25.0,
        high_above=10.0,
        monitor_above=0.0,
        updated_by=updated_by,
    )


@pytest.fixture
def admin_id(sessions: sessionmaker[Session]) -> int:
    with sessions() as session:
        account = User(email="a@b.co", password_hash=hash_password("a long password"))
        session.add(account)
        session.commit()
        return account.id
