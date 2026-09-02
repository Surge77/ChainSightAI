"""Signing in, and the things a sign-in must not tell an attacker or grant a visitor.

Three of these tests are the reason the file exists rather than checks for completeness:
a failed login says the same sentence whichever half was wrong, the registration form
cannot grant the admin role however it is posted, and a tampered cookie is anonymous rather
than partially trusted.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree

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


class TestBranding:
    def test_every_page_declares_the_tab_icon(self, client: TestClient) -> None:
        """A 404 for /favicon.ico on every page load is noise in the console of a tool
        whose whole argument is that a warning nobody acts on trains people to ignore
        warnings."""
        assert 'rel="icon"' in client.get("/login").text

    def test_the_icon_is_served(self, client: TestClient) -> None:
        response = client.get("/static/favicon.svg")

        assert response.status_code == 200
        assert "svg" in response.headers["content-type"]

    def test_the_icon_is_well_formed_xml(self, client: TestClient) -> None:
        """An SVG that does not parse does not appear, and does not complain either.

        The first version of this file had correct geometry and an em dash typed as two
        hyphens inside an XML comment, which is illegal. The browser rendered a parse error
        instead of an icon, and nothing in the application noticed.
        """
        root = ElementTree.fromstring(client.get("/static/favicon.svg").text)

        assert root.tag.endswith("svg")
        assert root.get("viewBox") == "0 0 32 32"

    def test_the_mark_is_inline_so_it_follows_the_theme(self, client: TestClient) -> None:
        """Linked as an <img> it would keep its own colours and look pasted on in dark mode."""
        body = client.get("/login").text

        assert 'class="mark"' in body
        assert "currentColor" in body


class TestThemeSwitch:
    def test_a_visitor_can_reach_the_switch(self, client: TestClient) -> None:
        """The sign-in page is themed for the same person the orders page is, so a control
        you have to sign in to reach is a control that arrives after it was needed."""
        assert 'id="theme-toggle"' in client.get("/login").text

    def test_a_signed_in_operator_keeps_it(self, client: TestClient, operator: User) -> None:
        assert 'id="theme-toggle"' in client.get("/orders").text

    def test_the_switch_is_hidden_until_its_script_reveals_it(self, client: TestClient) -> None:
        """Scripting off means no control at all, rather than one that does nothing."""
        body = client.get("/login").text

        assert body.index('id="theme-toggle"') < body.index("hidden>")

    def test_the_script_runs_before_the_page_is_painted(self, client: TestClient) -> None:
        """It writes the attribute the palette reads. Moved below the content it would paint
        the system theme first and the chosen one second, which is a flash of the wrong
        theme on every page load."""
        body = client.get("/login").text

        assert body.index("/static/theme.js") < body.index("<body>")
        assert "defer" not in body[: body.index("<body>")]

    def test_all_three_marks_ship_with_the_page(self, client: TestClient) -> None:
        """theme.js shows one of them and hides the other two. Drawn by the script instead,
        a broken mark would be invisible to a template and to this test alike."""
        body = client.get("/login").text

        for mode in ("system", "light", "dark"):
            assert f'data-mode="{mode}"' in body

    def test_the_marks_follow_the_theme(self, client: TestClient) -> None:
        """An icon carrying its own colours is the one thing on the page a theme switch
        cannot theme -- the same reason the wordmark is inlined rather than linked."""
        body = client.get("/login").text
        opened = body.index('id="theme-toggle"')
        button = body[opened : body.index("</button>", opened)]

        assert button.count("currentColor") >= 3

    def test_the_script_is_served(self, client: TestClient) -> None:
        response = client.get("/static/theme.js")

        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

    def test_the_stylesheet_answers_both_explicit_choices(self, client: TestClient) -> None:
        """Without both, one direction of the switch silently does nothing: a visitor whose
        system is dark could never get to light, which is the case that prompted this."""
        stylesheet = client.get("/static/chainsight.css").text

        assert ':root[data-theme="light"]' in stylesheet
        assert ':root[data-theme="dark"]' in stylesheet

    def test_no_choice_still_follows_the_system(self, client: TestClient) -> None:
        """`color-scheme: light dark` is what leaves an unset preference to the operating
        system, and what makes `light-dark()` in every token resolve at all."""
        stylesheet = client.get("/static/chainsight.css").text

        assert "color-scheme: light dark;" in stylesheet
        assert "data-theme" not in stylesheet.split("color-scheme: light dark;")[0]


class TestAdministratorSignIn:
    def test_an_administrator_lands_on_the_control_tower(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *ADMIN, admin=True)

        response = client.post("/admin/login", data={"email": ADMIN[0], "password": ADMIN[1]})

        assert response.status_code == 303
        assert response.headers["location"] == "/admin"
        assert COOKIE_NAME in response.cookies

    def test_an_operator_with_the_right_password_is_refused(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        """The form reads the role off the row. It has never been able to grant one."""
        make_user(sessions, *OPERATOR)

        response = client.post("/admin/login", data={"email": OPERATOR[0], "password": OPERATOR[1]})

        assert response.status_code == 400
        assert COOKIE_NAME not in response.cookies

    def test_a_refused_operator_is_told_the_same_thing_as_a_wrong_password(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        """Otherwise this page is an oracle for which accounts are administrators.

        Post a valid operator's credentials, read a different message from the one a bad
        password gets, and you have learned both that the account exists and that it is not
        an administrator.
        """
        make_user(sessions, *OPERATOR)

        refused = client.post("/admin/login", data={"email": OPERATOR[0], "password": OPERATOR[1]})
        wrong = client.post(
            "/admin/login", data={"email": OPERATOR[0], "password": "not the password"}
        )
        unknown = client.post("/admin/login", data={"email": "nobody@example.com", "password": "x"})

        assert refused.status_code == wrong.status_code == unknown.status_code == 400
        assert REJECTED in refused.text
        assert REJECTED in wrong.text
        assert REJECTED in unknown.text

    def test_signing_in_there_does_not_make_anybody_an_administrator(
        self, client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *OPERATOR)
        client.post("/admin/login", data={"email": OPERATOR[0], "password": OPERATOR[1]})

        with sessions() as session:
            stored = session.scalars(select(User).where(User.email == OPERATOR[0])).one()

        assert stored.is_admin is False

    def test_the_form_renders_for_a_visitor(self, client: TestClient) -> None:
        body = client.get("/admin/login").text

        assert "Administrator sign in" in body
        assert 'action="/admin/login"' in body

    def test_a_signed_in_operator_is_sent_to_their_own_pages(
        self, client: TestClient, operator: User
    ) -> None:
        """Not to a form. They are not missing a login."""
        assert client.get("/admin/login").headers["location"] == "/orders"

    def test_a_signed_in_administrator_is_sent_to_the_control_tower(
        self, client: TestClient, admin: User
    ) -> None:
        assert client.get("/admin/login").headers["location"] == "/admin"

    def test_the_two_doors_link_to_each_other(self, client: TestClient) -> None:
        assert "/admin/login" in client.get("/login").text
        assert '"/login"' in client.get("/admin/login").text


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
    def test_a_visitor_is_sent_to_the_administrator_form(
        self, client: TestClient, path: str
    ) -> None:
        """The door they wanted is the admin door, so that is the one they are shown."""
        response = client.get(path)

        assert response.status_code == 303
        assert response.headers["location"] == "/admin/login"

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
