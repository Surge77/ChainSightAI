"""The engine, the session, and the declarative base. SQLite by default, Postgres if asked.

A single-node deployment serving one operator does not need Postgres, and saying so is more
honest than adding a database server to a diagram. So the default is still a file. What the
schema always needed was to survive the swap if it ever happened, so nothing here uses a
SQLite-only type and every timestamp is stored as a real `DateTime` rather than a string that
sorts correctly by luck — and a deployment on a filesystem that does not persist is what
eventually asked for it.

`check_same_thread=False` is required because the request that opens a session and the
thread that closes it are not guaranteed to be the same under `TestClient` or under
uvicorn's threadpool. It is the standard SQLite-with-a-web-framework setting, and it is safe
here because each request gets its own session and sessions are not shared between threads.

Postgres is supported rather than assumed. `CHAINSIGHT_DATABASE` takes any URL SQLAlchemy
understands, nothing in `tables.py` uses a SQLite-only type, and the pool is configured for
a database that can disappear between requests — see `engine_options`. ADR 0014 records why
a deployment would want that and what it costs; the default is still a file.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from chainsight_web.config import ConfigurationError


class Base(DeclarativeBase):
    """The declarative base every table in `tables.py` inherits from."""


#: How long a pooled connection may sit before it is thrown away and remade. Shorter than
#: the idle timeout of any managed Postgres worth using, which is the point: the pool should
#: be the one deciding a connection is stale, not the far end.
POOL_RECYCLE_SECONDS = 300


def engine_options(url: str) -> dict[str, Any]:
    """The keyword arguments one database URL needs. Separated out so they can be tested.

    `pool_pre_ping` is the one that earns its place, and it earns it on a managed Postgres
    rather than on SQLite. A serverless Postgres suspends an idle branch and drops the
    connections with it; the pool does not find out, hands a request a socket that is already
    closed, and the request dies with `OperationalError: server closed the connection
    unexpectedly` — then succeeds on a retry, which is what makes it look intermittent and
    unreproducible rather than like a configuration mistake. A pre-ping is one round trip
    that turns the whole class of failure into a reconnect nobody sees.

    It costs a `SELECT 1` per checkout against a local SQLite file, which is not a cost.

    `check_same_thread` stays SQLite-only because it is a pysqlite argument and any other
    driver refuses it outright at connection time.
    """
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return {
        "connect_args": connect_args,
        "pool_pre_ping": True,
        "pool_recycle": POOL_RECYCLE_SECONDS,
        "future": True,
    }


def build_engine(url: str) -> Engine:
    """One engine for one database URL, configured for SQLite when that is what it is."""
    return create_engine(url, **engine_options(url))


def build_sessions(engine: Engine) -> sessionmaker[Session]:
    """A session factory. `expire_on_commit=False` so a committed row is still readable.

    Without it, reading an attribute after `commit()` re-queries, and a route that commits
    and then renders a template would issue a fresh SELECT per field — or raise, if the
    session has already been closed by the dependency that opened it.
    """
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def create_tables(engine: Engine) -> None:
    """Create anything missing. There is no migration tool here, and the schema says so.

    A portfolio application with one deployment does not need Alembic, and pretending
    otherwise would add a migration history nobody has ever run backwards. A schema change
    means a new database file, which is stated here rather than discovered.
    """
    Base.metadata.create_all(engine)


def verify_schema(engine: Engine) -> None:
    """Refuse to start against a database that predates a column, and say which one.

    `create_all` adds missing tables and cannot add a missing column, so a database created
    before a schema change keeps working until the first request that touches the new field
    and then fails as a 500 somewhere inside a template. This is not a migration tool and
    does not want to be one -- it turns that into a startup message naming the column and
    both ways out, which is the same fail-closed reasoning that keeps `Settings.from_env`
    from inventing a session secret.
    """
    tables = inspect(engine)
    for name, table in Base.metadata.tables.items():
        if not tables.has_table(name):
            continue
        present = {column["name"] for column in tables.get_columns(name)}
        missing = sorted(column.name for column in table.columns if column.name not in present)
        if missing:
            raise ConfigurationError(
                f"the {name} table in this database is missing {', '.join(missing)}. It was "
                "created before that column existed. Delete the database file to start "
                "again, or add the column with ALTER TABLE if the rows in it matter."
            )


def session_scope(sessions: sessionmaker[Session]) -> Iterator[Session]:
    """One session per request, closed whatever happens to the request."""
    session = sessions()
    try:
        yield session
    finally:
        session.close()
