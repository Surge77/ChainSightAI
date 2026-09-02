"""The control tower, and the two places it is allowed to change what production does.

The promotion guard is tested through the HTTP route as well as through `registry.promote`,
because a guard that exists in the library and is bypassed by the request handler is not a
guard. The dashboard is tested for the thing it must never do: imply a spread the data does
not have.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chainsight import persistence, registry
from chainsight_web.tables import DecisionConfig, ModelVersion, Prediction, TrainingRun, User

DEFAULT_COSTS = {
    "intervention": "15.0",
    "intervention_effectiveness": "1.0",
    "margin_lost_when_late": "0.5",
    "fixed_penalty_when_late": "25.0",
    "mean_margin": "0.1196",
    "typical_order_value": "176.88",
    "critical_above": "25.0",
    "high_above": "10.0",
    "monitor_above": "0.0",
}


def register_a_rival(artefacts: Path, roc: float) -> int:
    """Add a second registered version scoring whatever this test needs it to score."""
    known = registry.Registry(path=artefacts / registry.REGISTRY_NAME)
    manifest = persistence.Manifest(
        model_name="a rival",
        encoding="one-hot",
        feature_hash="a" * 64,
        dataset_hash="b" * 64,
        rows_trained=1,
        threshold=0.2966,
        scores={"roc auc": roc, "f1": 0.5},
    )
    return known.register(manifest, "a-rival-artefact").version


class TestDashboard:
    def test_it_names_the_model_that_is_serving(self, client: TestClient, admin: User) -> None:
        body = client.get("/admin").text

        assert "version 1" in body
        assert "one-hot random forest" in body

    def test_an_empty_installation_renders_without_dividing_by_zero(
        self, client: TestClient, admin: User
    ) -> None:
        response = client.get("/admin")

        assert response.status_code == 200
        assert "No scored orders yet" in response.text

    def test_the_risk_charts_are_pinned_to_a_zero_to_one_axis(
        self, client: TestClient, admin: User
    ) -> None:
        """A cropped axis would turn a five-point regional spread into a cliff."""
        body = client.get("/admin").text

        assert "min: 0, max: 1" in body

    def test_the_charts_do_not_animate(self, client: TestClient, admin: User) -> None:
        """Chart.js restarts its animation on resize, and a screenshot forces one.

        An animated chart therefore photographs as an empty grid with correct axes, which
        is how a working dashboard gets reported as broken. Found by taking a screenshot of
        the real thing, so it is pinned here.
        """
        assert "animation: false" in client.get("/admin").text

    def test_the_charts_say_they_are_predicted_risk_and_not_an_observed_rate(
        self, client: TestClient, admin: User
    ) -> None:
        body = client.get("/admin").text

        assert "not an observed late rate" in body

    def test_a_scored_order_reaches_the_summary(
        self, client: TestClient, admin: User, an_order: dict[str, str]
    ) -> None:
        client.post("/orders/new", data=an_order)

        body = client.get("/admin").text

        assert "Standard Class" in body
        assert "No scored orders yet" not in body

    def test_a_small_group_is_marked_noisy_rather_than_read_as_a_measurement(
        self, client: TestClient, admin: User, an_order: dict[str, str]
    ) -> None:
        client.post("/orders/new", data=an_order)

        assert "noisy" in client.get("/admin").text


class TestModelRegistryPage:
    def test_it_lists_what_the_json_registry_holds(self, client: TestClient, admin: User) -> None:
        body = client.get("/admin/models").text

        assert "one-hot random forest" in body
        assert "in use" in body

    def test_reading_the_page_refreshes_the_table_from_the_registry(
        self, client: TestClient, admin: User, artefacts: Path, sessions: sessionmaker[Session]
    ) -> None:
        """A model promoted from a terminal shows up here on the next page load."""
        register_a_rival(artefacts, roc=0.99)

        client.get("/admin/models")

        with sessions() as session:
            versions = list(session.scalars(select(ModelVersion)))
        assert {row.version for row in versions} == {1, 2}
        assert [row.is_live for row in versions if row.version == 1] == [True]

    def test_an_operator_cannot_reach_it(self, client: TestClient, operator: User) -> None:
        assert client.get("/admin/models").status_code == 403


class TestPromotion:
    def test_a_better_model_can_be_promoted(
        self, client: TestClient, admin: User, artefacts: Path
    ) -> None:
        version = register_a_rival(artefacts, roc=0.99)

        response = client.post("/admin/models/promote", data={"version": str(version)})

        assert response.status_code == 303
        assert "now+scoring+your+orders" in response.headers["location"]

    def test_a_worse_model_is_refused_through_the_route_too(
        self, client: TestClient, admin: User, artefacts: Path
    ) -> None:
        """The guard lives in `registry.promote`, and the route calls it rather than copying it."""
        version = register_a_rival(artefacts, roc=0.01)

        response = client.post("/admin/models/promote", data={"version": str(version)})

        assert "Being+newer+does+not+make+it+better" in response.headers["location"]
        live = registry.Registry(path=artefacts / registry.REGISTRY_NAME).current()
        assert live is not None and live.version == 1

    def test_force_pushes_a_worse_model_through(
        self, client: TestClient, admin: User, artefacts: Path
    ) -> None:
        version = register_a_rival(artefacts, roc=0.01)

        client.post("/admin/models/promote", data={"version": str(version), "force": "true"})

        live = registry.Registry(path=artefacts / registry.REGISTRY_NAME).current()
        assert live is not None and live.version == version

    def test_a_version_that_does_not_exist_is_reported_rather_than_crashing(
        self, client: TestClient, admin: User
    ) -> None:
        response = client.post("/admin/models/promote", data={"version": "99"})

        assert "no+version+99" in response.headers["location"]

    def test_an_operator_cannot_promote(
        self, client: TestClient, operator: User, artefacts: Path
    ) -> None:
        version = register_a_rival(artefacts, roc=0.99)

        assert (
            client.post("/admin/models/promote", data={"version": str(version)}).status_code == 403
        )

    def test_promoting_swaps_the_model_that_serves_the_next_order(
        self,
        client: TestClient,
        admin: User,
        an_order: dict[str, str],
        sessions: sessionmaker[Session],
    ) -> None:
        """The cache is keyed on the promoted version, so a promotion needs no restart."""
        client.post("/orders/new", data=an_order)
        client.post(
            "/admin/models/retrain",
            data={"model_name": "decision tree", "promote": "true"},
        )
        client.post("/orders/new", data=an_order)

        with sessions() as session:
            served = [row.model_name for row in session.scalars(select(Prediction))]

        assert served == ["one-hot random forest", "decision tree"]


class TestRetrain:
    def test_a_retrain_registers_a_version_and_records_the_run(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        response = client.post(
            "/admin/models/retrain", data={"model_name": "decision tree", "note": "a test"}
        )

        assert response.status_code == 303
        with sessions() as session:
            run = session.scalars(select(TrainingRun)).one()
        assert run.model_name == "decision tree"
        assert run.registered_version == 2
        assert run.promoted is False

    def test_a_retrain_that_is_not_asked_to_promote_does_not(
        self, client: TestClient, admin: User, artefacts: Path
    ) -> None:
        client.post("/admin/models/retrain", data={"model_name": "decision tree"})

        live = registry.Registry(path=artefacts / registry.REGISTRY_NAME).current()
        assert live is not None and live.version == 1

    def test_a_refused_promotion_is_recorded_with_its_reason(
        self, client: TestClient, admin: User, artefacts: Path, sessions: sessionmaker[Session]
    ) -> None:
        """Why the serving model is three weeks old is exactly what this row answers."""
        known = registry.Registry(path=artefacts / registry.REGISTRY_NAME)
        known.register(
            persistence.Manifest(
                model_name="an unbeatable model",
                encoding="one-hot",
                feature_hash="a" * 64,
                dataset_hash="b" * 64,
                rows_trained=1,
                threshold=0.2966,
                scores={"roc auc": 0.999},
            ),
            "unbeatable",
        )
        known.promote(2, force=True)

        client.post(
            "/admin/models/retrain",
            data={"model_name": "decision tree", "promote": "true"},
        )

        with sessions() as session:
            run = session.scalars(select(TrainingRun)).one()
        assert run.promoted is False
        assert "not switched on" in run.outcome

    def test_a_retrain_that_wins_is_promoted_and_serves(
        self, client: TestClient, admin: User, artefacts: Path, sessions: sessionmaker[Session]
    ) -> None:
        known = registry.Registry(path=artefacts / registry.REGISTRY_NAME)
        known.register(
            persistence.Manifest(
                model_name="a hopeless model",
                encoding="one-hot",
                feature_hash="a" * 64,
                dataset_hash="b" * 64,
                rows_trained=1,
                threshold=0.2966,
                scores={"roc auc": 0.01},
            ),
            "hopeless",
        )
        known.promote(2, force=True)

        client.post(
            "/admin/models/retrain",
            data={"model_name": "decision tree", "promote": "true"},
        )

        with sessions() as session:
            run = session.scalars(select(TrainingRun)).one()
        assert run.promoted is True
        live = known.current()
        assert live is not None and live.version == 3

    def test_a_candidate_that_does_not_exist_is_reported(
        self, client: TestClient, admin: User
    ) -> None:
        response = client.post("/admin/models/retrain", data={"model_name": "xgboost"})

        assert "no+classifier+called" in response.headers["location"]

    def test_a_missing_dataset_is_reported_rather_than_raised(
        self, client: TestClient, admin: User, app: FastAPI, tmp_path: Path
    ) -> None:
        app.state.settings = replace(app.state.settings, dataset=tmp_path / "absent.csv")

        response = client.post("/admin/models/retrain", data={"model_name": "decision tree"})

        assert "is+not+on+this+machine" in response.headers["location"]

    def test_an_operator_cannot_retrain(self, client: TestClient, operator: User) -> None:
        assert (
            client.post("/admin/models/retrain", data={"model_name": "decision tree"}).status_code
            == 403
        )


class TestCostModel:
    def test_the_page_shows_the_threshold_the_current_costs_imply(
        self, client: TestClient, admin: User
    ) -> None:
        body = client.get("/admin/costs").text

        assert "0.4216" in body
        assert "Not 50%" in body

    def test_saving_a_cost_model_stores_it_with_its_author(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        client.post("/admin/costs", data={**DEFAULT_COSTS, "intervention": "5.0"})

        with sessions() as session:
            stored = session.scalars(select(DecisionConfig)).one()
        assert stored.intervention == 5.0
        assert stored.updated_by == admin.id

    def test_a_cheaper_intervention_lowers_the_threshold_the_next_order_is_judged_against(
        self,
        client: TestClient,
        admin: User,
        an_order: dict[str, str],
        sessions: sessionmaker[Session],
    ) -> None:
        client.post("/admin/costs", data={**DEFAULT_COSTS, "intervention": "1.0"})
        client.post("/orders/new", data=an_order)

        with sessions() as session:
            stored = session.scalars(select(Prediction)).one()
        assert stored.threshold < 0.2966

    def test_bands_that_do_not_descend_are_refused_with_a_field_error(
        self, client: TestClient, admin: User
    ) -> None:
        """`CostModel` would raise on this, and a 500 is a worse answer than a field error."""
        response = client.post(
            "/admin/costs", data={**DEFAULT_COSTS, "critical_above": "1.0", "high_above": "50.0"}
        )

        assert response.status_code == 422

    def test_a_free_intervention_is_refused(self, client: TestClient, admin: User) -> None:
        response = client.post("/admin/costs", data={**DEFAULT_COSTS, "intervention": "0"})

        assert response.status_code == 422

    def test_saving_says_that_past_predictions_keep_their_own_costs(
        self, client: TestClient, admin: User
    ) -> None:
        response = client.post("/admin/costs", data=DEFAULT_COSTS)

        assert "keep the" in response.text

    def test_an_operator_cannot_change_the_cost_model(
        self, client: TestClient, operator: User
    ) -> None:
        assert client.post("/admin/costs", data=DEFAULT_COSTS).status_code == 403
