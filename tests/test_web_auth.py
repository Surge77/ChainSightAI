"""Signing in, and the things a sign-in must not tell an attacker or grant a visitor.

Three of these tests are the reason the file exists rather than checks for completeness:
a failed login says the same sentence whichever half was wrong, the registration form
cannot grant the admin role however it is posted, and a tampered cookie is anonymous rather
than partially trusted.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chainsight_web.routes_auth import REJECTED
from chainsight_web.security import COOKIE_NAME, sign_session
from chainsight_web.tables import User
from conftest import ADMIN, OPERATOR, make_user, sign_in, user_count


class TestRegistration:
    def test_a_new_account_is_created_and_signed_in(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        response = client.post(
            "/register", data={"email": "New@Example.com", "password": "a long enough one"}
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/orders"
        assert user_count(sessions) == 1

    def test_the_email_is_stored_folded_to_lower_case(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        """Otherwise `New@example.com` and `new@example.com` are two accounts."""
        client.post("/register", data={"email": "New@Example.com", "password": "a long enough one"})

        with sessions() as session:
            stored = session.scalars(select(User)).one()
        assert stored.email == "new@example.com"

    def test_a_registered_account_is_never_an_administrator(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        """The role is not a field on the form, so posting one cannot set it."""
        client.post(
            "/register",
            data={
                "email": "sneaky@example.com",
                "password": "a long enough one",
                "is_admin": "true",
            },
        )

        with sessions() as session:
            stored = session.scalars(select(User)).one()
        assert stored.is_admin is False

    def test_a_short_password_is_refused_at_the_boundary(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        response = client.post("/register", data={"email": "a@b.co", "password": "short"})

        assert response.status_code == 422
        assert user_count(sessions) == 0

    def test_something_that_is_not_an_address_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/register", data={"email": "not-an-address", "password": "long enough"}
        )

        assert response.status_code == 422

    def test_an_email_that_already_exists_is_refused_without_creating_a_second(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *OPERATOR)

        response = client.post(
            "/register", data={"email": OPERATOR[0], "password": "a long enough one"}
        )

        assert response.status_code == 400
        assert "already has an account" in response.text
        assert user_count(sessions) == 1

    def test_the_form_renders_for_a_visitor(self, client: TestClient) -> None:
        assert client.get("/register").status_code == 200

    def test_a_signed_in_user_is_sent_on_rather_than_shown_the_form(
        self, client: TestClient, operator: User
    ) -> None:
        assert client.get("/register").headers["location"] == "/orders"


class TestSignIn:
    def test_correct_credentials_set_a_session_cookie(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *OPERATOR)

        response = client.post("/login", data={"email": OPERATOR[0], "password": OPERATOR[1]})

        assert response.status_code == 303
        assert COOKIE_NAME in response.cookies

    def test_a_wrong_password_and_an_unknown_account_say_the_same_thing(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        """The difference between the two sentences is a way to enumerate accounts."""
        make_user(sessions, *OPERATOR)

        wrong = client.post("/login", data={"email": OPERATOR[0], "password": "not the password"})
        unknown = client.post("/login", data={"email": "nobody@example.com", "password": "x"})

        assert wrong.status_code == unknown.status_code == 400
        assert REJECTED in wrong.text
        assert REJECTED in unknown.text

    def test_a_failed_login_sets_no_cookie(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *OPERATOR)

        response = client.post("/login", data={"email": OPERATOR[0], "password": "wrong"})

        assert COOKIE_NAME not in response.cookies

    def test_the_email_is_matched_case_insensitively(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *OPERATOR)

        response = client.post(
            "/login", data={"email": OPERATOR[0].upper(), "password": OPERATOR[1]}
        )

        assert response.status_code == 303

    def test_the_form_renders_for_a_visitor(self, client: TestClient) -> None:
        assert client.get("/login").status_code == 200

    def test_a_signed_in_user_is_sent_on(self, client: TestClient, operator: User) -> None:
        assert client.get("/login").headers["location"] == "/orders"


class TestSignOut:
    def test_signing_out_ends_the_session(self, client: TestClient, operator: User) -> None:
        client.post("/logout")

        assert client.get("/orders").headers["location"] == "/login"


class TestCookies:
    def test_the_session_cookie_is_not_readable_by_script(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *OPERATOR)

        response = client.post("/login", data={"email": OPERATOR[0], "password": OPERATOR[1]})

        assert "httponly" in response.headers["set-cookie"].lower()

    def test_a_tampered_cookie_is_anonymous_rather_than_partly_trusted(
        self, client: TestClient, operator: User
    ) -> None:
        client.cookies.set(COOKIE_NAME, "not-a-signed-value")

        assert client.get("/orders").headers["location"] == "/login"

    def test_a_cookie_signed_with_another_secret_is_refused(
        self, client: TestClient, operator: User
    ) -> None:
        """The signature is what makes the id in it trustworthy, and nothing else is."""
        client.cookies.set(COOKIE_NAME, sign_session(operator.id, secret="a different secret"))

        assert client.get("/orders").headers["location"] == "/login"

    def test_a_cookie_for_a_deleted_account_stops_working_immediately(
        self, client: TestClient, operator: User, sessions: sessionmaker[Session]
    ) -> None:
        """The role and the account are looked up per request, not cached in the cookie."""
        with sessions() as session:
            session.delete(session.get(User, operator.id))
            session.commit()

        assert client.get("/orders").headers["location"] == "/login"


class TestRoles:
    @pytest.mark.parametrize("path", ["/admin", "/admin/models", "/admin/costs"])
    def test_an_operator_may_not_reach_an_admin_page(
        self, client: TestClient, operator: User, path: str
    ) -> None:
        assert client.get(path).status_code == 403

    @pytest.mark.parametrize("path", ["/admin", "/admin/models", "/admin/costs"])
    def test_a_visitor_is_sent_to_the_login_form(self, client: TestClient, path: str) -> None:
        response = client.get(path)

        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_the_role_comes_from_the_database_and_not_from_the_session(
        self, client: TestClient, operator: User, sessions: sessionmaker[Session]
    ) -> None:
        """Granting the role mid-session takes effect at once, because it is read per request."""
        assert client.get("/admin").status_code == 403

        with sessions() as session:
            promoted = session.get(User, operator.id)
            assert promoted is not None
            promoted.is_admin = True
            session.commit()

        assert client.get("/admin").status_code == 200

    def test_revoking_the_role_takes_effect_without_a_new_login(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        assert client.get("/admin").status_code == 200

        with sessions() as session:
            demoted = session.get(User, admin.id)
            assert demoted is not None
            demoted.is_admin = False
            session.commit()

        assert client.get("/admin").status_code == 403


def test_two_accounts_can_hold_sessions_at_once(
    client: TestClient, sessions: sessionmaker[Session]
) -> None:
    """A regression guard: the session is a cookie, so it must not be process-wide state."""
    make_user(sessions, *OPERATOR)
    make_user(sessions, *ADMIN, admin=True)

    sign_in(client, OPERATOR)
    assert client.get("/admin").status_code == 403

    sign_in(client, ADMIN)
    assert client.get("/admin").status_code == 200
