"""How the engine is configured, and why the pool settings are not left at their defaults.

These are unit tests on `engine_options` rather than assertions about a live connection, on
purpose. The behaviour they stand for — a managed Postgres dropping an idle connection, the
pool handing the next request the dead socket — needs a database that suspends to reproduce,
and a test that cannot run without one is a test nobody runs. What can be pinned here is that
the option which prevents it is actually set, and that the SQLite-only argument stays
SQLite-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from chainsight_web.config import ConfigurationError
from chainsight_web.database import (
    POOL_RECYCLE_SECONDS,
    Base,
    build_engine,
    create_tables,
    engine_options,
    verify_schema,
)

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


class TestTheSchemaCheck:
    """`create_all` adds tables and cannot add columns, so an old database needs saying so.

    The runbook in `deploy/hf/` tells whoever is reading a container log to act on this
    message by name, which is a poor reason to have never run it.
    """

    def test_a_database_built_by_this_code_starts(self, tmp_path: Path) -> None:
        engine = build_engine(f"sqlite:///{tmp_path / 'current.db'}")
        create_tables(engine)

        verify_schema(engine)

    def test_a_table_that_is_simply_absent_is_not_a_missing_column(self, tmp_path: Path) -> None:
        """`create_all` runs first and will make it. Only an existing table can lack a field.

        Treating an absent table as a schema error would refuse to start against exactly the
        empty database this application is designed to build for itself.
        """
        engine = build_engine(f"sqlite:///{tmp_path / 'partial.db'}")
        Base.metadata.tables["users"].create(engine)

        verify_schema(engine)

    def test_a_database_that_predates_a_column_is_refused_and_the_column_named(
        self, tmp_path: Path
    ) -> None:
        """Otherwise it works until the first request that touches the field, then 500s."""
        engine = build_engine(f"sqlite:///{tmp_path / 'old.db'}")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR)"))

        with pytest.raises(ConfigurationError, match="password_hash"):
            verify_schema(engine)
