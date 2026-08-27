"""No state changes without a matching CSRF token, and no form without one in it.

The check is registered on the application rather than on each route, so the test that
matters most is not "does /login reject a forged post" but **"is there any state-changing
route that a forged post gets through"**. Those are different questions, and only the second
one stays true when somebody adds a route next month.

`test_every_post_form_carries_a_token` is the other half. The protection fails closed, so a
form missing its token does not become a vulnerability — it becomes a 403 on a page that
used to work. That is a much better failure, and this test makes it a build failure instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from chainsight_web.security import CSRF_COOKIE, CSRF_FIELD
from chainsight_web.templating import TEMPLATES_DIR
from conftest import ADMIN, OPERATOR, make_user

#: Every form this application posts, and a body that would be valid if the token were.
STATE_CHANGING: list[tuple[str, dict[str, str]]] = [
    ("/login", {"email": OPERATOR[0], "password": OPERATOR[1]}),
    ("/register", {"email": "new@example.com", "password": "a long enough one"}),
    ("/admin/login", {"email": ADMIN[0], "password": ADMIN[1]}),
    ("/logout", {}),
    ("/admin/users/role", {"user_id": "1", "make_admin": "true"}),
    ("/admin/models/promote", {"version": "1"}),
    ("/admin/models/retrain", {"model_name": "decision tree"}),
]


def token_of(raw_client: TestClient) -> str:
    """Fetch a page so the browser has a token, and read it back out of the cookie."""
    raw_client.get("/login")
    return raw_client.cookies[CSRF_COOKIE]


class TestRefusal:
    @pytest.mark.parametrize(("path", "body"), STATE_CHANGING)
    def test_a_post_without_a_token_is_refused(
        self, raw_client: TestClient, path: str, body: dict[str, str]
    ) -> None:
        """Every one of them, so a route added without a token cannot slip through."""
        assert raw_client.post(path, data=body).status_code == 403

    @pytest.mark.parametrize(("path", "body"), STATE_CHANGING)
    def test_a_post_with_the_wrong_token_is_refused(
        self, raw_client: TestClient, path: str, body: dict[str, str]
    ) -> None:
        token_of(raw_client)

        response = raw_client.post(path, data={**body, CSRF_FIELD: "not the token"})

        assert response.status_code == 403

    def test_a_token_without_the_cookie_is_refused(self, raw_client: TestClient) -> None:
        """Half of a double submit is not a submit. Both sides have to agree."""
        token = token_of(raw_client)
        raw_client.cookies.delete(CSRF_COOKIE)

        response = raw_client.post("/login", data={"email": "a@b.co", CSRF_FIELD: token})

        assert response.status_code == 403

    def test_the_refusal_says_what_to_do(self, raw_client: TestClient) -> None:
        assert "Reload the page" in raw_client.post("/login", data={}).text


class TestIssuing:
    def test_a_page_issues_a_token_to_a_visitor_who_has_none(self, raw_client: TestClient) -> None:
        response = raw_client.get("/login")

        assert CSRF_COOKIE in response.cookies

    def test_the_form_carries_the_same_value_as_the_cookie(self, raw_client: TestClient) -> None:
        body = raw_client.get("/login").text
        token = raw_client.cookies[CSRF_COOKIE]

        assert f'value="{token}"' in body

    def test_a_second_page_keeps_the_token_rather_than_minting_another(
        self, raw_client: TestClient
    ) -> None:
        """Otherwise the form in whichever tab you did not reload last stops working."""
        first = token_of(raw_client)
        raw_client.get("/register")

        assert raw_client.cookies[CSRF_COOKIE] == first

    def test_the_token_changes_when_a_session_starts(
        self, raw_client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        """The CSRF half of session fixation: a token fixed before login must not survive it."""
        make_user(sessions, *OPERATOR)
        before = token_of(raw_client)

        raw_client.post(
            "/login",
            data={"email": OPERATOR[0], "password": OPERATOR[1], CSRF_FIELD: before},
        )

        assert raw_client.cookies[CSRF_COOKIE] != before

    def test_the_cookie_is_not_readable_by_script(self, raw_client: TestClient) -> None:
        """The form gets the token because the server rendered it, not because JS read it."""
        response = raw_client.get("/login")

        assert "httponly" in response.headers["set-cookie"].lower()


class TestItStillWorks:
    def test_a_post_with_the_matching_token_succeeds(
        self, raw_client: TestClient, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *OPERATOR)
        token = token_of(raw_client)

        response = raw_client.post(
            "/login",
            data={"email": OPERATOR[0], "password": OPERATOR[1], CSRF_FIELD: token},
        )

        assert response.status_code == 303

    def test_reading_a_page_needs_no_token(self, raw_client: TestClient) -> None:
        assert raw_client.get("/login").status_code == 200


def test_every_post_form_carries_a_token() -> None:
    """Scanned rather than trusted, because one missed form is one unprotected route.

    The check fails closed, so a form without a token is a 403 on a page that used to work
    rather than a hole. This turns that into a build failure instead of a bug report.
    """
    missing = []
    for template in sorted(Path(TEMPLATES_DIR).glob("*.html")):
        body = template.read_text(encoding="utf-8")
        forms = len(re.findall(r'<form[^>]*method="post"', body, flags=re.I))
        tokens = body.count(f'name="{CSRF_FIELD}"')
        if forms != tokens:
            missing.append(f"{template.name}: {forms} forms, {tokens} tokens")

    assert not missing, "forms without a CSRF token: " + "; ".join(missing)


def test_the_check_is_registered_on_the_application(app: FastAPI) -> None:
    """Not route by route. A per-route list is a thing somebody forgets on the next route.

    Asserted against the application's own dependency list rather than by probing routes,
    because that is the property being relied on: anything mounted under this app inherits
    the check, including routes that do not exist yet.
    """
    registered = [
        getattr(dependency.dependency, "__name__", "") for dependency in app.router.dependencies
    ]

    assert "verify_csrf" in registered
