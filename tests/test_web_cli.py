"""`python -m chainsight_web`: the only way an administrator gets made.

There is no first-user-becomes-admin rule and no checkbox on the registration form, so this
command is the whole of the path to the admin role. That makes it worth testing as carefully
as a route: it must not create an account with a weak password, and it must not be reachable
without a session secret.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select

from chainsight_web import __main__ as web_cli
from chainsight_web.config import SECRET_VAR
from chainsight_web.database import build_engine, build_sessions
from chainsight_web.tables import User
from conftest import TEST_SECRET


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A configured environment pointing at a database this test owns."""
    database = tmp_path / "cli.db"
    monkeypatch.setenv(SECRET_VAR, TEST_SECRET)
    monkeypatch.setenv("CHAINSIGHT_DATABASE", f"sqlite:///{database}")
    monkeypatch.setenv("CHAINSIGHT_ARTEFACTS", str(tmp_path / "artifacts"))
    yield database


def accounts(database: Path) -> list[User]:
    sessions = build_sessions(build_engine(f"sqlite:///{database}"))
    with sessions() as session:
        return list(session.scalars(select(User)))


class TestInit:
    def test_it_creates_an_administrator(self, environment: Path) -> None:
        code = web_cli.main(
            ["init", "--email", "Admin@Example.com", "--password", "a long enough password"]
        )

        assert code == 0
        created = accounts(environment)
        assert [(row.email, row.is_admin) for row in created] == [("admin@example.com", True)]

    def test_it_can_create_an_ordinary_operator_instead(self, environment: Path) -> None:
        web_cli.main(
            [
                "init",
                "--email",
                "op@example.com",
                "--password",
                "a long enough password",
                "--operator",
            ]
        )

        assert accounts(environment)[0].is_admin is False

    def test_a_weak_password_is_refused_and_nothing_is_created(self, environment: Path) -> None:
        code = web_cli.main(["init", "--email", "a@b.co", "--password", "short"])

        assert code == 1
        assert accounts(environment) == []

    def test_running_it_again_promotes_the_existing_account_rather_than_failing(
        self, environment: Path
    ) -> None:
        """The realistic second use: an operator who now needs the admin role."""
        web_cli.main(
            ["init", "--email", "a@b.co", "--password", "a long enough password", "--operator"]
        )

        code = web_cli.main(["init", "--email", "a@b.co", "--password", "a long enough password"])

        assert code == 0
        assert len(accounts(environment)) == 1
        assert accounts(environment)[0].is_admin is True

    def test_the_password_is_prompted_for_when_it_is_not_given(
        self, environment: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A password on the command line lands in the shell history. Prompting is the default."""
        monkeypatch.setattr(web_cli.getpass, "getpass", lambda _="": "a prompted password")

        assert web_cli.main(["init", "--email", "a@b.co"]) == 0
        assert len(accounts(environment)) == 1

    def test_a_rerun_leaves_the_password_alone_and_says_so(
        self, environment: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The bug this replaced: the second password was hashed into nothing and never said so."""
        web_cli.main(["init", "--email", "a@b.co", "--password", "the original password"])
        before = accounts(environment)[0].password_hash

        code = web_cli.main(["init", "--email", "a@b.co", "--password", "a different password"])

        assert code == 0
        assert accounts(environment)[0].password_hash == before
        assert "password is unchanged" in capsys.readouterr().out

    def test_a_rerun_does_not_even_ask_for_a_password(
        self, environment: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Looking the account up first is what stops a prompt whose answer is discarded."""
        web_cli.main(["init", "--email", "a@b.co", "--password", "a long enough password"])

        def refuse(_: str = "") -> str:
            raise AssertionError("an existing account must not be prompted for a password")

        monkeypatch.setattr(web_cli.getpass, "getpass", refuse)

        assert web_cli.main(["init", "--email", "a@b.co"]) == 0

    def test_reset_password_is_how_a_locked_out_account_gets_a_new_one(
        self, environment: Path
    ) -> None:
        web_cli.main(["init", "--email", "a@b.co", "--password", "the forgotten password"])
        before = accounts(environment)[0].password_hash

        code = web_cli.main(
            [
                "init",
                "--email",
                "a@b.co",
                "--password",
                "the replacement password",
                "--reset-password",
            ]
        )

        assert code == 0
        assert accounts(environment)[0].password_hash != before
        assert len(accounts(environment)) == 1

    def test_a_reset_still_refuses_a_weak_password(self, environment: Path) -> None:
        web_cli.main(["init", "--email", "a@b.co", "--password", "the original password"])
        before = accounts(environment)[0].password_hash

        code = web_cli.main(
            ["init", "--email", "a@b.co", "--password", "short", "--reset-password"]
        )

        assert code == 1
        assert accounts(environment)[0].password_hash == before

    def test_the_stored_password_is_a_hash_and_not_the_password(self, environment: Path) -> None:
        web_cli.main(["init", "--email", "a@b.co", "--password", "a long enough password"])

        assert "a long enough password" not in accounts(environment)[0].password_hash


class TestServe:
    def test_it_runs_uvicorn_against_the_configured_host_and_port(
        self, environment: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: dict[str, object] = {}

        def fake_run(app: object, **kwargs: object) -> None:
            called.update(kwargs)

        import uvicorn

        monkeypatch.setattr(uvicorn, "run", fake_run)

        assert web_cli.main(["serve"]) == 0
        assert called["host"] == "127.0.0.1"
        assert called["port"] == 8000

    def test_the_command_line_overrides_the_environment(
        self, environment: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: dict[str, object] = {}
        import uvicorn

        monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: called.update(kwargs))

        web_cli.main(["serve", "--host", "0.0.0.0", "--port", "9999"])

        assert (called["host"], called["port"]) == ("0.0.0.0", 9999)


class TestConfiguration:
    def test_it_refuses_to_run_without_a_session_secret(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv(SECRET_VAR, raising=False)

        code = web_cli.main(["init", "--email", "a@b.co", "--password", "a long enough password"])

        assert code == 2
        assert "will not fall back" in capsys.readouterr().err


def test_the_parser_refuses_a_command_it_does_not_have() -> None:
    with pytest.raises(SystemExit):
        web_cli.main(["deploy"])
