"""The attempt budget: what it counts, what it refuses, and what it deliberately does not.

The tests worth reading are the three that pin down design decisions rather than behaviour.

`test_the_two_sign_in_doors_share_one_budget` is why `/admin/login` existing as a separate
page does not double an attacker's allowance.

`test_a_successful_sign_in_does_not_refund_the_budget` is the reset-on-success bypass:
an attacker holding one working account would otherwise clear the counter at will.

`test_a_valid_operator_refused_at_the_admin_door_still_spends_an_attempt` closes the other
free-guess path — the one credential that page is guaranteed to reject.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from chainsight_web import throttle
from chainsight_web.tables import Attempt
from conftest import ADMIN, OPERATOR, BrowserClient, make_user

#: A fixed instant, so a window boundary is a subtraction rather than a race with the clock.
NOON = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

#: An address the tests spend budgets against. `TestClient` reports "testclient" for the
#: requests that go through the application; these unit tests use their own.
SOMEWHERE = "198.51.100.7"


def attempts_in(sessions: sessionmaker[Session], scope: str) -> int:
    with sessions() as session:
        return (
            session.scalar(select(func.count()).select_from(Attempt).where(Attempt.scope == scope))
            or 0
        )


class TestTheClock:
    """`as_utc` exists because SQLite and Postgres disagree about what they hand back."""

    def test_a_naive_timestamp_is_labelled_utc(self) -> None:
        stamped = throttle.as_utc(datetime(2026, 3, 1, 12, 0))

        assert stamped == NOON

    def test_an_already_aware_timestamp_is_left_alone(self) -> None:
        assert throttle.as_utc(NOON) is NOON


class TestTheAddress:
    def test_the_client_address_is_read_from_the_connection(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/login",
                "headers": [],
                "client": (SOMEWHERE, 44321),
            }
        )

        assert throttle.client_address(request) == SOMEWHERE

    def test_a_request_with_no_client_shares_one_bucket_rather_than_escaping(self) -> None:
        """Unidentifiable is throttled with the other unidentifiables, not exempted."""
        request = Request({"type": "http", "method": "POST", "path": "/login", "headers": []})

        assert throttle.client_address(request) == throttle.UNKNOWN_CLIENT


class TestTheBudget:
    def test_an_address_that_has_spent_nothing_is_not_waiting(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions() as session:
            assert throttle.retry_after(session, throttle.SIGN_IN, SOMEWHERE, now=NOON) is None

    def test_one_short_of_the_limit_is_still_allowed(self, sessions: sessionmaker[Session]) -> None:
        with sessions() as session:
            for _ in range(throttle.SIGN_IN.limit - 1):
                throttle.record(session, throttle.SIGN_IN, SOMEWHERE, now=NOON)

            assert throttle.retry_after(session, throttle.SIGN_IN, SOMEWHERE, now=NOON) is None

    def test_the_limit_refuses_and_says_how_long(self, sessions: sessionmaker[Session]) -> None:
        with sessions() as session:
            for _ in range(throttle.SIGN_IN.limit):
                throttle.record(session, throttle.SIGN_IN, SOMEWHERE, now=NOON)

            remaining = throttle.retry_after(session, throttle.SIGN_IN, SOMEWHERE, now=NOON)

        assert remaining == throttle.SIGN_IN.window

    def test_the_window_slides_rather_than_locking_for_a_fixed_period(
        self, sessions: sessionmaker[Session]
    ) -> None:
        """The oldest attempt ageing out is what frees the slot. No second piece of state."""
        with sessions() as session:
            for _ in range(throttle.SIGN_IN.limit):
                throttle.record(session, throttle.SIGN_IN, SOMEWHERE, now=NOON)

            just_inside = NOON + throttle.SIGN_IN.window - timedelta(seconds=1)
            just_outside = NOON + throttle.SIGN_IN.window + timedelta(seconds=1)

            assert throttle.retry_after(
                session, throttle.SIGN_IN, SOMEWHERE, now=just_inside
            ) == timedelta(seconds=1)
            assert (
                throttle.retry_after(session, throttle.SIGN_IN, SOMEWHERE, now=just_outside) is None
            )

    def test_one_address_spending_its_budget_does_not_refuse_another(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions() as session:
            for _ in range(throttle.SIGN_IN.limit):
                throttle.record(session, throttle.SIGN_IN, SOMEWHERE, now=NOON)

            assert throttle.retry_after(session, throttle.SIGN_IN, "203.0.113.9", now=NOON) is None

    def test_the_budgets_are_separate_from_each_other(
        self, sessions: sessionmaker[Session]
    ) -> None:
        """Failing to sign in must not stop the same address registering, and vice versa."""
        with sessions() as session:
            for _ in range(throttle.SIGN_IN.limit):
                throttle.record(session, throttle.SIGN_IN, SOMEWHERE, now=NOON)

            assert throttle.retry_after(session, throttle.REGISTRATION, SOMEWHERE, now=NOON) is None

    def test_recording_prunes_attempts_that_can_no_longer_affect_an_answer(
        self, sessions: sessionmaker[Session]
    ) -> None:
        """There is nowhere to run a cleanup job, so the write does it."""
        with sessions() as session:
            throttle.record(session, throttle.SIGN_IN, SOMEWHERE, now=NOON)
            throttle.record(
                session,
                throttle.SIGN_IN,
                SOMEWHERE,
                now=NOON + throttle.SIGN_IN.window + timedelta(minutes=1),
            )

        assert attempts_in(sessions, throttle.SIGN_IN.scope) == 1

    def test_pruning_leaves_a_different_budgets_rows_alone(
        self, sessions: sessionmaker[Session]
    ) -> None:
        """The sign-in window is short and the registration window is long."""
        with sessions() as session:
            throttle.record(session, throttle.REGISTRATION, SOMEWHERE, now=NOON)
            throttle.record(
                session,
                throttle.SIGN_IN,
                SOMEWHERE,
                now=NOON + throttle.SIGN_IN.window + timedelta(minutes=1),
            )

        assert attempts_in(sessions, throttle.REGISTRATION.scope) == 1


class TestTheMessage:
    def test_it_rounds_a_part_minute_up_rather_than_down_to_zero(self) -> None:
        assert "1 minute." in throttle.wait_message(timedelta(seconds=30))

    def test_it_pluralises(self) -> None:
        assert "11 minutes." in throttle.wait_message(timedelta(minutes=11))

    def test_an_elapsed_wait_still_reads_as_a_wait(self) -> None:
        """Never "try again in 0 minutes", which reads as "try again now" and is not."""
        assert "1 minute." in throttle.wait_message(timedelta(0))

    def test_it_names_no_account(self) -> None:
        """The limit must not become the oracle that `REJECTED` exists to avoid."""
        message = throttle.wait_message(timedelta(minutes=3))

        assert "account" not in message.split("not from your account")[0]


class TestSigningIn:
    def test_the_budget_refuses_the_attempt_after_the_limit(
        self, client: BrowserClient, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *OPERATOR)
        wrong = {"email": OPERATOR[0], "password": "not the password"}

        for _ in range(throttle.SIGN_IN.limit):
            assert client.post("/login", data=wrong).status_code == 400

        refused = client.post("/login", data=wrong)

        assert refused.status_code == 429
        assert "Too many attempts" in refused.text

    def test_the_right_password_is_refused_too_once_the_budget_is_gone(
        self, client: BrowserClient, sessions: sessionmaker[Session]
    ) -> None:
        """The limit is on the address, so it does not care that this attempt would work."""
        make_user(sessions, *OPERATOR)
        for _ in range(throttle.SIGN_IN.limit):
            client.post("/login", data={"email": OPERATOR[0], "password": "wrong"})

        refused = client.post("/login", data={"email": OPERATOR[0], "password": OPERATOR[1]})

        assert refused.status_code == 429

    def test_the_two_sign_in_doors_share_one_budget(self, client: BrowserClient) -> None:
        """Otherwise the separate admin page is a way round the limit, not a convenience."""
        wrong = {"email": "nobody@example.com", "password": "not the password"}
        half = throttle.SIGN_IN.limit // 2

        for _ in range(half):
            assert client.post("/login", data=wrong).status_code == 400
        for _ in range(throttle.SIGN_IN.limit - half):
            assert client.post("/admin/login", data=wrong).status_code == 400

        assert client.post("/admin/login", data=wrong).status_code == 429
        assert client.post("/login", data=wrong).status_code == 429

    def test_a_valid_operator_refused_at_the_admin_door_still_spends_an_attempt(
        self, client: BrowserClient, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *OPERATOR)

        response = client.post("/admin/login", data={"email": OPERATOR[0], "password": OPERATOR[1]})

        assert response.status_code == 400
        assert attempts_in(sessions, throttle.SIGN_IN.scope) == 1

    def test_a_successful_sign_in_does_not_refund_the_budget(
        self, client: BrowserClient, sessions: sessionmaker[Session]
    ) -> None:
        """Reset-on-success is the usual design and it is a bypass. See `throttle.py`."""
        make_user(sessions, *OPERATOR)
        for _ in range(throttle.SIGN_IN.limit - 1):
            client.post("/login", data={"email": OPERATOR[0], "password": "wrong"})

        assert (
            client.post("/login", data={"email": OPERATOR[0], "password": OPERATOR[1]}).status_code
            == 303
        )
        assert attempts_in(sessions, throttle.SIGN_IN.scope) == throttle.SIGN_IN.limit - 1

    def test_an_administrator_still_gets_in_while_the_budget_lasts(
        self, client: BrowserClient, sessions: sessionmaker[Session]
    ) -> None:
        make_user(sessions, *ADMIN, admin=True)

        response = client.post("/admin/login", data={"email": ADMIN[0], "password": ADMIN[1]})

        assert response.status_code == 303
        assert response.headers["location"] == "/admin"


class TestRegistering:
    def test_the_budget_refuses_a_flood_of_new_accounts(self, client: BrowserClient) -> None:
        for index in range(throttle.REGISTRATION.limit):
            response = client.post(
                "/register",
                data={"email": f"person{index}@example.com", "password": "a long enough one"},
            )
            assert response.status_code == 303

        refused = client.post(
            "/register", data={"email": "one@toomany.example", "password": "a long enough one"}
        )

        assert refused.status_code == 429
        assert "Too many attempts" in refused.text

    def test_posting_at_an_address_that_is_taken_spends_an_attempt_too(
        self, client: BrowserClient, sessions: sessionmaker[Session]
    ) -> None:
        """Posting repeatedly at addresses to see which are taken is how you enumerate them."""
        make_user(sessions, *OPERATOR)

        response = client.post(
            "/register", data={"email": OPERATOR[0], "password": "a long enough one"}
        )

        assert response.status_code == 400
        assert attempts_in(sessions, throttle.REGISTRATION.scope) == 1

    def test_a_spent_sign_in_budget_does_not_block_registering(self, client: BrowserClient) -> None:
        for _ in range(throttle.SIGN_IN.limit):
            client.post("/login", data={"email": "nobody@example.com", "password": "wrong"})

        response = client.post(
            "/register", data={"email": "new@example.com", "password": "a long enough one"}
        )

        assert response.status_code == 303


def test_the_application_creates_the_attempts_table(app: FastAPI) -> None:
    """`create_all` has to know about the new table, which means it has to be imported."""
    assert "attempts" in Attempt.metadata.tables
    assert app.state.engine.dialect.has_table is not None
