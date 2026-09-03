"""How the engine is configured, and why the pool settings are not left at their defaults.

These are unit tests on `engine_options` rather than assertions about a live connection, on
purpose. The behaviour they stand for — a managed Postgres dropping an idle connection, the
pool handing the next request the dead socket — needs a database that suspends to reproduce,
and a test that cannot run without one is a test nobody runs. What can be pinned here is that
the option which prevents it is actually set, and that the SQLite-only argument stays
SQLite-only.
"""

from __future__ import annotations

from typing import Any

import pytest

from chainsight_web.database import POOL_RECYCLE_SECONDS, build_engine, engine_options

SQLITE = "sqlite:///a-file.db"
POSTGRES = "postgresql+psycopg://user:secret@example.invalid/chainsight"


class TestEngineOptions:
    def test_sqlite_gets_the_thread_check_turned_off(self) -> None:
        """The session is opened on one thread and closed on another under uvicorn."""
        assert engine_options(SQLITE)["connect_args"] == {"check_same_thread": False}

    def test_no_other_driver_is_handed_a_pysqlite_argument(self) -> None:
        """`check_same_thread` is not a psycopg keyword; passing it fails at connect time."""
        assert engine_options(POSTGRES)["connect_args"] == {}

    def test_every_connection_is_checked_before_it_is_handed_out(self) -> None:
        """A suspended Postgres drops its connections and the pool is not told.

        Without this the first request after an idle period gets a closed socket and dies
        with `OperationalError: server closed the connection unexpectedly`, then works on a
        retry — which reads as flakiness rather than as configuration.
        """
        assert engine_options(POSTGRES)["pool_pre_ping"] is True
        assert engine_options(SQLITE)["pool_pre_ping"] is True

    def test_connections_are_recycled_before_anything_upstream_times_them_out(self) -> None:
        assert engine_options(POSTGRES)["pool_recycle"] == POOL_RECYCLE_SECONDS

    def test_the_engine_is_built_with_them(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The options are worth nothing if `build_engine` stops passing them on.

        Asserted against what `create_engine` was handed rather than against the pool it
        produced. `Pool` keeps these as `_recycle` and `_pre_ping`, and a test reading a
        private attribute breaks on a SQLAlchemy release that renames it while the code it
        was guarding is still perfectly correct.
        """
        handed: dict[str, Any] = {}

        def capture(url: str, **options: Any) -> object:
            handed.update(options, url=url)
            return object()

        monkeypatch.setattr("chainsight_web.database.create_engine", capture)
        build_engine(SQLITE)

        assert handed == {**engine_options(SQLITE), "url": SQLITE}
