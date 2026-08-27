"""Fixtures for the web tests: a real model, a real database, and a real HTTP client.

Nothing here is mocked. The application is built by its own factory against a temporary
SQLite file and a temporary artefacts directory, and the model it serves is genuinely
fitted on the committed 500-row slice. A test that mocks the model would pass while the
feature space and the estimator disagreed, which is the one failure `persistence.load`
exists to catch.

The model is trained once for the whole session and the artefacts directory is copied per
test, because fitting is the expensive part and a copy is not.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chainsight import persistence, registry, training
from chainsight_web.app import create_app
from chainsight_web.config import Settings
from chainsight_web.security import CSRF_COOKIE, CSRF_FIELD, hash_password
from chainsight_web.tables import User

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "data" / "sample_orders.csv"

#: Long enough to be a real secret, fixed so a signed cookie is reproducible across a test.
TEST_SECRET = "a-test-secret-that-is-not-used-anywhere-real"

OPERATOR = ("operator@example.com", "an operator password")
ADMIN = ("admin@example.com", "an admin password")


@pytest.fixture(scope="session")
def fitted_artefacts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One trained, registered and promoted model, fitted once for the whole session."""
    directory = tmp_path_factory.mktemp("fitted")
    run = training.train(SAMPLE)
    name = training.artefact_name(run)
    persistence.save(run.artefact, name, directory=directory)

    known = registry.Registry(path=directory / registry.REGISTRY_NAME)
    known.register(run.manifest, name, note="the test fixture's model")
    known.promote(1)
    return directory


@pytest.fixture
def artefacts(fitted_artefacts: Path, tmp_path: Path) -> Path:
    """A private copy of the fitted model, so a test may promote or retrain freely."""
    directory = tmp_path / "artifacts"
    shutil.copytree(fitted_artefacts, directory)
    return directory


@pytest.fixture
def empty_artefacts(tmp_path: Path) -> Path:
    """An artefacts directory with nothing in it, for the nothing-is-promoted paths."""
    return tmp_path / "no-artifacts"


@pytest.fixture
def settings(tmp_path: Path, artefacts: Path) -> Settings:
    return Settings(
        session_secret=TEST_SECRET,
        database_url=f"sqlite:///{tmp_path / 'chainsight.db'}",
        artefacts=artefacts,
        dataset=SAMPLE,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def sessions(app: FastAPI) -> sessionmaker[Session]:
    """The application's own session factory, so a test reads the database it wrote."""
    factory: sessionmaker[Session] = app.state.sessions
    return factory


class BrowserClient(TestClient):
    """A client that fills in the hidden CSRF field, the way a browser would.

    Every form the application renders carries the token, so a test posting a form without
    one is testing a submission no browser makes. Rather than repeat the field in sixty
    call sites, this puts it in exactly where the rendered HTML would have.

    A test that supplies its own `csrf_token` keeps it, so a test *about* the token can
    still send a wrong one. `raw_client` skips this entirely.
    """

    #: Body arguments that mean the caller is not posting a form at all.
    _OTHER_BODIES = ("json", "content", "files")

    def post(  # type: ignore[override]
        self, url: str, *, data: dict[str, str] | None = None, **kwargs: Any
    ) -> httpx.Response:
        # `data is None` is the case that matters: `client.post("/logout")` posts a form
        # with no other fields, and an earlier version of this helper skipped it and spent
        # a debugging session looking at the application instead.
        if not any(key in kwargs for key in self._OTHER_BODIES):
            fields: dict[str, str] = dict(data or {})
            fields.setdefault(CSRF_FIELD, self._csrf_token())
            data = fields
        return super().post(url, data=data, **kwargs)

    def _csrf_token(self) -> str:
        if CSRF_COOKIE not in self.cookies:
            self.get("/login")
        return self.cookies[CSRF_COOKIE]


@pytest.fixture
def client(app: FastAPI) -> Iterator[BrowserClient]:
    """A client that does not follow redirects, so a test can assert where it was sent."""
    with BrowserClient(app, follow_redirects=False) as running:
        yield running


@pytest.fixture
def raw_client(app: FastAPI) -> Iterator[TestClient]:
    """A client that adds nothing to a request. For the tests about CSRF itself."""
    with TestClient(app, follow_redirects=False) as running:
        yield running


def make_user(
    sessions: sessionmaker[Session], email: str, password: str, *, admin: bool = False
) -> User:
    """Insert an account directly, the way `python -m chainsight_web init` would.

    Registration through the form is exercised by its own tests. Everywhere else, going
    through it would make each test pay for a bcrypt hash and a redirect it is not about.
    """
    with sessions() as session:
        account = User(email=email, password_hash=hash_password(password), is_admin=admin)
        session.add(account)
        session.commit()
        return account


def sign_in(client: TestClient, credentials: tuple[str, str]) -> None:
    """Log the client in, leaving the session cookie on it for subsequent requests."""
    email, password = credentials
    response = client.post("/login", data={"email": email, "password": password})
    assert response.status_code == 303, response.text


@pytest.fixture
def operator(client: TestClient, sessions: sessionmaker[Session]) -> User:
    account = make_user(sessions, *OPERATOR)
    sign_in(client, OPERATOR)
    return account


@pytest.fixture
def admin(client: TestClient, sessions: sessionmaker[Session]) -> User:
    account = make_user(sessions, *ADMIN, admin=True)
    sign_in(client, ADMIN)
    return account


@pytest.fixture
def an_order() -> dict[str, str]:
    """A form body for one order, using values the fitted model has actually seen."""
    return {
        "shipping_mode": "Standard Class",
        "payment_type": "DEBIT",
        "market": "USCA",
        "order_region": "South of  USA ",
        "order_country": "Estados Unidos",
        "customer_country": "EE. UU.",
        "customer_state": "IL",
        "customer_segment": "Consumer",
        "department_name": "Fan Shop",
        "category_name": "Water Sports",
        "product_name": "Pelican Sunstream 100 Kayak",
        "quantity": "1",
        "product_price": "199.99",
        "order_total": "191.99",
        "discount_rate": "0.04",
        "ordered_at": "2016-07-30T12:30",
    }


def user_count(sessions: sessionmaker[Session]) -> int:
    with sessions() as session:
        return len(list(session.scalars(select(User))))
