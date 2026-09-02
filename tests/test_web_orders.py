"""What an operator can do, and the one row they must never be able to reach.

`test_an_operator_cannot_read_another_operators_order` is the test this file exists for.
Ownership is a `WHERE` clause rather than a check after the fetch, and the difference only
shows up when somebody guesses an id — so somebody guesses an id here, every time the suite
runs.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from chainsight_web.app import create_app
from chainsight_web.config import Settings
from chainsight_web.tables import Order, Prediction, User
from conftest import OPERATOR, BrowserClient, make_user, sign_in


def create(client: TestClient, order: dict[str, str]) -> int:
    """Post an order and return its id, from the redirect it was sent to."""
    response = client.post("/orders/new", data=order)
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rsplit("/", 1)[1])


class TestHome:
    def test_a_visitor_is_sent_to_the_login_form(self, client: TestClient) -> None:
        assert client.get("/").headers["location"] == "/login"

    def test_a_signed_in_operator_is_sent_to_their_orders(
        self, client: TestClient, operator: User
    ) -> None:
        assert client.get("/").headers["location"] == "/orders"


class TestOrderList:
    def test_an_empty_list_says_so_rather_than_showing_an_empty_table(
        self, client: TestClient, operator: User
    ) -> None:
        response = client.get("/orders")

        assert response.status_code == 200
        assert "No orders yet" in response.text

    def test_orders_are_ranked_by_net_benefit_rather_than_by_probability(
        self,
        client: TestClient,
        operator: User,
        an_order: dict[str, str],
        sessions: sessionmaker[Session],
    ) -> None:
        """The whole reason the decision engine exists, asserted through the page."""
        cheap = create(client, {**an_order, "order_total": "20.00", "product_price": "20.00"})
        valuable = create(client, {**an_order, "order_total": "499.95", "product_price": "499.95"})

        with sessions() as session:
            scores = {row.order_id: row for row in session.scalars(select(Prediction))}
        assert scores[valuable].net_benefit > scores[cheap].net_benefit

        body = client.get("/orders").text
        assert body.index(f"/orders/{valuable}") < body.index(f"/orders/{cheap}")

    def test_an_operator_sees_only_their_own_orders(
        self,
        client: TestClient,
        operator: User,
        an_order: dict[str, str],
        sessions: sessionmaker[Session],
    ) -> None:
        mine = create(client, an_order)

        make_user(sessions, "someone@example.com", "another password entirely")
        sign_in(client, ("someone@example.com", "another password entirely"))

        assert f"/orders/{mine}" not in client.get("/orders").text


class TestNewOrder:
    def test_the_form_offers_only_categories_the_model_was_fitted_on(
        self, client: TestClient, operator: User
    ) -> None:
        """A free-text field would accept a plausible name and predict from an all-zero block."""
        body = client.get("/orders/new").text

        assert "Standard Class" in body
        assert "<select" in body

    def test_an_order_is_scored_and_the_operator_is_sent_to_its_report(
        self, client: TestClient, operator: User, an_order: dict[str, str]
    ) -> None:
        order_id = create(client, an_order)

        report = client.get(f"/orders/{order_id}")

        assert report.status_code == 200
        assert "chance of being late" in report.text.lower()
        assert "Net saving if we act" in report.text

    def test_the_prediction_records_which_model_produced_it(
        self,
        client: TestClient,
        operator: User,
        an_order: dict[str, str],
        sessions: sessionmaker[Session],
    ) -> None:
        create(client, an_order)

        with sessions() as session:
            stored = session.scalars(select(Prediction)).one()

        assert stored.model_version == 1
        assert stored.model_name == "one-hot random forest"

    def test_the_stored_decision_carries_every_field_the_report_shows(
        self,
        client: TestClient,
        operator: User,
        an_order: dict[str, str],
        sessions: sessionmaker[Session],
    ) -> None:
        """Recomputing on read would show last week's order under this week's costs."""
        create(client, an_order)

        with sessions() as session:
            stored = session.scalars(select(Prediction)).one()

        assert 0.0 <= stored.probability <= 1.0
        assert stored.threshold != 0.5
        assert stored.priority in {"critical", "high", "monitor", "low"}
        assert stored.recommendation.endswith(".")

    def test_a_quantity_of_zero_is_refused_at_the_boundary(
        self, client: TestClient, operator: User, an_order: dict[str, str]
    ) -> None:
        assert client.post("/orders/new", data={**an_order, "quantity": "0"}).status_code == 422

    def test_a_negative_total_is_refused_rather_than_reaching_the_decision_engine(
        self, client: TestClient, operator: User, an_order: dict[str, str]
    ) -> None:
        """`decide` would raise on it, and a 500 is a worse answer than a field error."""
        assert client.post("/orders/new", data={**an_order, "order_total": "-5"}).status_code == 422

    def test_a_discount_rate_above_one_is_refused(
        self, client: TestClient, operator: User, an_order: dict[str, str]
    ) -> None:
        assert (
            client.post("/orders/new", data={**an_order, "discount_rate": "1.5"}).status_code == 422
        )

    def test_a_visitor_cannot_create_an_order(
        self, client: TestClient, an_order: dict[str, str]
    ) -> None:
        assert client.post("/orders/new", data=an_order).headers["location"] == "/login"


class TestQueryCount:
    def test_listing_orders_does_not_query_once_per_order(
        self, client: TestClient, app: FastAPI, operator: User, an_order: dict[str, str]
    ) -> None:
        """The page whose job is to show every row must not ask the database per row.

        Pinned as a count rather than left to review, because an N+1 is invisible in the
        output — the page renders correctly and simply costs more with every order added.
        """
        for total in ("20.00", "50.00", "99.00", "199.00", "499.95"):
            create(client, {**an_order, "order_total": total})

        statements: list[str] = []
        engine = app.state.engine

        def record(conn: object, cursor: object, statement: str, *rest: object) -> None:
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            assert client.get("/orders").status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", record)

        selects = [query for query in statements if query.lstrip().upper().startswith("SELECT")]
        assert len(selects) <= 4, f"{len(selects)} selects for 5 orders"


class TestOwnership:
    def test_an_operator_cannot_read_another_operators_order(
        self,
        client: TestClient,
        operator: User,
        an_order: dict[str, str],
        sessions: sessionmaker[Session],
    ) -> None:
        mine = create(client, an_order)

        make_user(sessions, "intruder@example.com", "an intruder password")
        sign_in(client, ("intruder@example.com", "an intruder password"))

        assert client.get(f"/orders/{mine}").status_code == 404

    def test_an_order_that_does_not_exist_is_the_same_404(
        self, client: TestClient, operator: User
    ) -> None:
        """Otherwise the difference between the two answers confirms which ids exist."""
        assert client.get("/orders/9999").status_code == 404

    def test_the_404_page_does_not_say_which_of_the_two_it_was(
        self, client: TestClient, operator: User
    ) -> None:
        body = client.get("/orders/9999").text

        assert "belongs to somebody else" in body


class TestWithoutAModel:
    def test_the_form_explains_itself_when_nothing_is_promoted(
        self, tmp_path: Path, empty_artefacts: Path
    ) -> None:
        client, _ = _client_without_a_model(tmp_path, empty_artefacts)

        assert "No model is switched on yet" in client.get("/orders/new").text

    def test_an_order_posted_without_a_model_is_kept_rather_than_lost(
        self, tmp_path: Path, empty_artefacts: Path, an_order: dict[str, str]
    ) -> None:
        """It is a real order a real operator typed. An unavailable model is not its fault."""
        client, factory = _client_without_a_model(tmp_path, empty_artefacts)

        response = client.post("/orders/new", data=an_order)

        assert response.status_code == 503
        with factory() as session:
            assert len(list(session.scalars(select(Order)))) == 1


def _client_without_a_model(
    tmp_path: Path, empty_artefacts: Path
) -> tuple[BrowserClient, sessionmaker[Session]]:
    """An application whose artefacts directory has nothing promoted in it."""
    settings = Settings(
        session_secret="a-test-secret-that-is-not-used-anywhere-real",
        database_url=f"sqlite:///{tmp_path / 'no-model.db'}",
        artefacts=empty_artefacts,
    )
    app = create_app(settings)
    client = BrowserClient(app, follow_redirects=False)
    make_user(app.state.sessions, *OPERATOR)
    sign_in(client, OPERATOR)
    return client, app.state.sessions
