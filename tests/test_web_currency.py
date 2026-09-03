"""Every amount on a page carries a currency, and it is the one this app was configured with.

The figures used to render bare. `499.95` on its own is a number, not a price, and the
prose around it drifted far enough to call it rupees while the catalogue was priced in
dollars. These tests assert the symbol is present on the money and absent from the things
that only look like money — a probability, a discount rate, a share.

The GBP application exists to catch the shortcut. Threading the currency through `render`
rather than registering one Jinja filter on the module-level environment is what keeps two
applications in one process from answering for each other, and only a test that builds the
second one would notice if that were undone.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from chainsight_web.app import create_app
from chainsight_web.config import Settings
from chainsight_web.tables import User
from conftest import ADMIN, OPERATOR, BrowserClient, make_user, sign_in


def create(client: TestClient, order: dict[str, str]) -> int:
    response = client.post("/orders/new", data=order)
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rsplit("/", 1)[1])


class TestTheDefault:
    def test_the_report_prices_every_figure_in_dollars(
        self, client: BrowserClient, operator: User, an_order: dict[str, str]
    ) -> None:
        order_id = create(client, an_order)

        body = client.get(f"/orders/{order_id}").text

        # Expected profit, money at risk and net saving, plus the two entered amounts in
        # the table underneath. Four is the count that would drop if `money()` were missed
        # on one card.
        assert body.count("$") >= 5
        assert "$191.99" in body

    def test_the_order_list_prices_the_total_column(
        self, client: BrowserClient, operator: User, an_order: dict[str, str]
    ) -> None:
        create(client, an_order)

        assert "$191.99" in client.get("/orders").text

    def test_the_dashboard_prices_its_money_cards(
        self, client: BrowserClient, admin: User, an_order: dict[str, str]
    ) -> None:
        create(client, an_order)

        assert "$" in client.get("/admin").text

    def test_a_rate_is_not_given_a_currency(
        self, client: BrowserClient, operator: User, an_order: dict[str, str]
    ) -> None:
        """The discount rate is a share. A symbol on it would be a category error."""
        order_id = create(client, an_order)

        body = client.get(f"/orders/{order_id}").text

        assert "$0.04" not in body
        assert "0.04" in body


@pytest.fixture
def sterling_app(tmp_path: Path, artefacts: Path) -> FastAPI:
    """A second application, configured in pounds, in the same process as the first."""
    return create_app(
        Settings(
            session_secret="a-test-secret-that-is-not-used-anywhere-real",
            database_url=f"sqlite:///{tmp_path / 'sterling.db'}",
            artefacts=artefacts,
            currency="GBP",
        )
    )


@pytest.fixture
def sterling_client(sterling_app: FastAPI) -> Iterator[BrowserClient]:
    with BrowserClient(sterling_app, follow_redirects=False) as running:
        yield running


class TestAnotherCurrency:
    def test_the_configured_symbol_replaces_the_dollar_everywhere(
        self,
        sterling_app: FastAPI,
        sterling_client: BrowserClient,
        an_order: dict[str, str],
    ) -> None:
        sessions: sessionmaker[Session] = sterling_app.state.sessions
        make_user(sessions, *OPERATOR)
        sign_in(sterling_client, OPERATOR)
        order_id = create(sterling_client, an_order)

        body = sterling_client.get(f"/orders/{order_id}").text

        assert "£191.99" in body
        assert "$191.99" not in body
        # The one dollar sign that survives is the training catalogue's own price range,
        # which is a fact about the dataset rather than about this operator's money. The
        # page says so in the sentence it appears in.
        assert body.count("$") == 1
        assert "$499.95" in body

    def test_the_cost_form_asks_for_the_configured_currency(
        self, sterling_app: FastAPI, sterling_client: BrowserClient
    ) -> None:
        """Those fields are the operator's own money, which is the reason this is a setting."""
        sessions: sessionmaker[Session] = sterling_app.state.sessions
        make_user(sessions, *ADMIN, admin=True)
        sign_in(sterling_client, ADMIN)

        body = sterling_client.get("/admin/costs").text

        assert "What it costs to step in on one order (£)" in body
        assert "GBP" in body

    def test_the_two_applications_do_not_answer_for_each_other(
        self,
        client: BrowserClient,
        operator: User,
        an_order: dict[str, str],
        sterling_app: FastAPI,
        sterling_client: BrowserClient,
    ) -> None:
        """Built in this order on purpose: the sterling app is the more recent one."""
        order_id = create(client, an_order)

        assert "$191.99" in client.get(f"/orders/{order_id}").text
