"""An administrator creating an account, and the password that makes it acceptable.

The objection to an administrator setting somebody's password is not that it is
inconvenient. It is that the administrator knows it afterwards, so every action by that
account is deniable — "that could have been the admin". A one-use password answers that, and
only if two things hold: the account can reach nothing until it is replaced, and the old one
stops working once it is. Both are tested here, and
`test_the_administrator_cannot_sign_in_as_them_afterwards` is the one that is really the
point.
"""

from __future__ import annotations

import re

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chainsight_web.tables import User
from conftest import OPERATOR, BrowserClient, make_user

#: The generated password is rendered in one place, and read back out of it here.
ISSUED = re.compile(r'class="issued-password">([^<]+)<')


def issue(client: BrowserClient, email: str) -> str:
    """Create an account through the page and return the password it showed once."""
    body = client.post("/admin/users/new", data={"email": email}).text
    found = ISSUED.search(body)
    assert found is not None, "the page did not show a temporary password"
    return found.group(1).strip()


def holder_of(app: FastAPI, email: str, password: str) -> BrowserClient:
    """A second browser, signed in as the account that was just created."""
    theirs = BrowserClient(app, follow_redirects=False)
    theirs.post("/login", data={"email": email, "password": password})
    return theirs


class TestCreating:
    def test_an_administrator_can_create_an_operator(
        self, client: BrowserClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        response = client.post("/admin/users/new", data={"email": "New@Example.com"})

        assert response.status_code == 200
        with sessions() as session:
            created = session.scalars(select(User).where(User.email == "new@example.com")).one()
        assert created.is_admin is False
        assert created.must_change_password is True

    def test_the_new_account_is_never_an_administrator(
        self, client: BrowserClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        """The role is granted separately, by the control that writes an audit row."""
        client.post("/admin/users/new", data={"email": "plain@example.com", "is_admin": "true"})

        with sessions() as session:
            created = session.scalars(select(User).where(User.email == "plain@example.com")).one()
        assert created.is_admin is False

    def test_the_password_is_shown_once(self, client: BrowserClient, admin: User) -> None:
        client.post("/admin/users/new", data={"email": "one@example.com"})

        assert "Temporary password for" not in client.get("/admin/users").text

    def test_an_email_that_already_exists_is_refused(
        self, client: BrowserClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *OPERATOR)

        assert (
            "already has an account"
            in client.post("/admin/users/new", data={"email": OPERATOR[0]}).text
        )

    def test_something_that_is_not_an_address_is_refused(
        self, client: BrowserClient, admin: User
    ) -> None:
        assert client.post("/admin/users/new", data={"email": "nope"}).status_code == 422

    def test_an_operator_cannot_create_accounts(
        self, client: BrowserClient, operator: User
    ) -> None:
        assert (
            client.post("/admin/users/new", data={"email": "sneak@example.com"}).status_code == 403
        )


class TestTheTemporaryPassword:
    def test_it_signs_the_account_in(
        self, client: BrowserClient, admin: User, app: FastAPI
    ) -> None:
        password = issue(client, "two@example.com")

        theirs = BrowserClient(app, follow_redirects=False)
        response = theirs.post("/login", data={"email": "two@example.com", "password": password})

        assert response.status_code == 303

    def test_the_account_reaches_nothing_else_until_it_is_replaced(
        self, client: BrowserClient, admin: User, app: FastAPI
    ) -> None:
        """The whole reason an administrator-set password is acceptable at all."""
        theirs = holder_of(app, "fresh@example.com", issue(client, "fresh@example.com"))

        for path in ("/orders", "/orders/new", "/"):
            response = theirs.get(path)
            assert response.status_code == 303, path
            assert response.headers["location"] == "/password", path

    def test_an_administrator_holding_one_is_held_as_well(
        self, client: BrowserClient, admin: User, app: FastAPI, sessions: sessionmaker[Session]
    ) -> None:
        """Or the hold would have an administrator-shaped hole in it."""
        theirs = holder_of(app, "boss@example.com", issue(client, "boss@example.com"))
        with sessions() as session:
            row = session.scalars(select(User).where(User.email == "boss@example.com")).one()
            row.is_admin = True
            session.commit()

        assert theirs.get("/admin").headers["location"] == "/password"

    def test_replacing_it_releases_the_account(
        self, client: BrowserClient, admin: User, app: FastAPI, sessions: sessionmaker[Session]
    ) -> None:
        theirs = holder_of(app, "free@example.com", issue(client, "free@example.com"))

        theirs.post(
            "/password",
            data={"password": "a password of my own", "confirm": "a password of my own"},
        )

        assert theirs.get("/orders").status_code == 200
        with sessions() as session:
            row = session.scalars(select(User).where(User.email == "free@example.com")).one()
        assert row.must_change_password is False

    def test_the_administrator_cannot_sign_in_as_them_afterwards(
        self, client: BrowserClient, admin: User, app: FastAPI
    ) -> None:
        """The point of the exercise. The issued password stops opening the account."""
        issued = issue(client, "mine@example.com")
        theirs = holder_of(app, "mine@example.com", issued)
        theirs.post("/password", data={"password": "chosen by me", "confirm": "chosen by me"})

        stale = BrowserClient(app, follow_redirects=False)
        response = stale.post("/login", data={"email": "mine@example.com", "password": issued})

        assert response.status_code == 400


class TestChoosingAPassword:
    def test_the_two_entries_have_to_match(
        self, client: BrowserClient, admin: User, app: FastAPI
    ) -> None:
        theirs = holder_of(app, "typo@example.com", issue(client, "typo@example.com"))

        response = theirs.post(
            "/password", data={"password": "a long enough one", "confirm": "a different one"}
        )

        assert response.status_code == 422

    def test_a_short_password_is_refused(
        self, client: BrowserClient, admin: User, app: FastAPI
    ) -> None:
        theirs = holder_of(app, "brief@example.com", issue(client, "brief@example.com"))

        response = theirs.post("/password", data={"password": "short", "confirm": "short"})

        assert response.status_code == 422

    def test_a_visitor_is_sent_to_sign_in(self, client: BrowserClient) -> None:
        assert client.get("/password").headers["location"] == "/login"

    def test_a_visitor_cannot_post_a_new_password(self, client: BrowserClient) -> None:
        response = client.post(
            "/password", data={"password": "a long enough one", "confirm": "a long enough one"}
        )

        assert response.headers["location"] == "/login"

    def test_somebody_without_a_temporary_password_may_still_change_it(
        self, client: BrowserClient, operator: User
    ) -> None:
        """The page is not only for the forced case. It simply is not compulsory."""
        body = client.get("/password").text

        assert "Choose a password" in body
        assert "One more step" not in body
