"""Granting and revoking the administrator role from the browser.

The role is the most consequential thing this application can change about an account, and
this is the file that has to be paranoid about it. Three tests carry the weight: an operator
cannot reach the page at all, the last administrator cannot be demoted by anybody, and a
granted role takes effect on the very next request rather than at the next restart.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chainsight_web.tables import RoleChange, User
from conftest import ADMIN, OPERATOR, make_user, sign_in

SECOND_ADMIN = ("second@example.com", "another admin password")


def role_of(sessions: sessionmaker[Session], email: str) -> bool:
    with sessions() as session:
        return session.scalars(select(User).where(User.email == email)).one().is_admin


def changes(sessions: sessionmaker[Session]) -> list[RoleChange]:
    with sessions() as session:
        return list(session.scalars(select(RoleChange).order_by(RoleChange.id)))


class TestAccess:
    def test_an_administrator_sees_every_account(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *OPERATOR)

        body = client.get("/admin/users").text

        assert ADMIN[0] in body
        assert OPERATOR[0] in body

    def test_an_operator_cannot_reach_it(self, client: TestClient, operator: User) -> None:
        assert client.get("/admin/users").status_code == 403

    def test_an_operator_cannot_post_to_it(self, client: TestClient, operator: User) -> None:
        """The page being hidden from the nav is not the control. This is."""
        response = client.post(
            "/admin/users/role", data={"user_id": str(operator.id), "make_admin": "true"}
        )

        assert response.status_code == 403

    def test_a_visitor_is_sent_to_the_administrator_door(self, client: TestClient) -> None:
        assert client.get("/admin/users").headers["location"] == "/admin/login"

    def test_it_says_how_the_first_administrator_is_made(
        self, client: TestClient, admin: User
    ) -> None:
        """That case cannot go through this page, and the page should not pretend it can."""
        assert "chainsight_web init" in client.get("/admin/users").text


class TestGranting:
    def test_an_operator_can_be_made_an_administrator(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        subject = make_user(sessions, *OPERATOR)

        response = client.post(
            "/admin/users/role", data={"user_id": str(subject.id), "make_admin": "true"}
        )

        assert response.status_code == 303
        assert role_of(sessions, OPERATOR[0]) is True

    def test_the_new_administrator_can_act_immediately(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        """No restart, because the role is read from the row on every request."""
        subject = make_user(sessions, *OPERATOR)
        client.post("/admin/users/role", data={"user_id": str(subject.id), "make_admin": "true"})

        sign_in(client, OPERATOR)

        assert client.get("/admin").status_code == 200

    def test_granting_is_recorded_with_both_parties(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        subject = make_user(sessions, *OPERATOR)

        client.post("/admin/users/role", data={"user_id": str(subject.id), "make_admin": "true"})

        entry = changes(sessions)[-1]
        assert (entry.actor_email, entry.subject_email) == (ADMIN[0], OPERATOR[0])
        assert entry.granted is True

    def test_granting_a_role_somebody_already_has_changes_nothing(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        response = client.post(
            "/admin/users/role", data={"user_id": str(admin.id), "make_admin": "true"}
        )

        assert "already" in response.headers["location"]
        assert changes(sessions) == []

    def test_an_account_that_does_not_exist_is_reported(
        self, client: TestClient, admin: User
    ) -> None:
        response = client.post("/admin/users/role", data={"user_id": "9999", "make_admin": "true"})

        assert "no+account+9999" in response.headers["location"]


class TestRevoking:
    def test_the_last_administrator_cannot_be_demoted(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        """An application with no administrator has no way back in short of a shell."""
        response = client.post(
            "/admin/users/role", data={"user_id": str(admin.id), "make_admin": "false"}
        )

        assert "only+administrator" in response.headers["location"]
        assert role_of(sessions, ADMIN[0]) is True

    def test_a_refused_demotion_is_not_recorded(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        client.post("/admin/users/role", data={"user_id": str(admin.id), "make_admin": "false"})

        assert changes(sessions) == []

    def test_an_administrator_may_step_down_once_somebody_else_holds_it(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        """The rule is about what the change does, not about who is asking."""
        make_user(sessions, *SECOND_ADMIN, admin=True)

        response = client.post(
            "/admin/users/role", data={"user_id": str(admin.id), "make_admin": "false"}
        )

        assert response.status_code == 303
        assert role_of(sessions, ADMIN[0]) is False

    def test_stepping_down_takes_effect_at_once(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *SECOND_ADMIN, admin=True)

        client.post("/admin/users/role", data={"user_id": str(admin.id), "make_admin": "false"})

        assert client.get("/admin").status_code == 403

    def test_revoking_another_administrator_is_recorded(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        other = make_user(sessions, *SECOND_ADMIN, admin=True)

        client.post("/admin/users/role", data={"user_id": str(other.id), "make_admin": "false"})

        entry = changes(sessions)[-1]
        assert entry.granted is False
        assert entry.subject_email == SECOND_ADMIN[0]


class TestAuditView:
    def test_an_untouched_installation_says_so(self, client: TestClient, admin: User) -> None:
        assert "No role has been granted or revoked" in client.get("/admin/users").text

    def test_a_change_appears_on_the_page(
        self, client: TestClient, admin: User, sessions: sessionmaker[Session]
    ) -> None:
        subject = make_user(sessions, *OPERATOR)
        client.post("/admin/users/role", data={"user_id": str(subject.id), "make_admin": "true"})

        body = client.get("/admin/users").text

        assert "granted" in body
        assert "No role has been granted or revoked" not in body


@pytest.mark.parametrize("make_admin", ["true", "false"])
def test_a_role_change_needs_an_administrator_whichever_direction(
    client: TestClient, operator: User, make_admin: str
) -> None:
    response = client.post(
        "/admin/users/role", data={"user_id": str(operator.id), "make_admin": make_admin}
    )

    assert response.status_code == 403
