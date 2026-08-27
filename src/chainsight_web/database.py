"""The engine, the session, and the declarative base. SQLite, and deliberately so.

A single-node portfolio deployment serving one operator does not need Postgres, and saying
so is more honest than adding a database server to a diagram. What the schema does need is
to survive the swap if it ever happens, so nothing here uses a SQLite-only type and every
timestamp is stored as a real `DateTime` rather than a string that sorts correctly by luck.

`check_same_thread=False` is required because the request that opens a session and the
thread that closes it are not guaranteed to be the same under `TestClient` or under
uvicorn's threadpool. It is the standard SQLite-with-a-web-framework setting, and it is safe
here because each request gets its own session and sessions are not shared between threads.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """The declarative base every table in `tables.py` inherits from."""


def build_engine(url: str) -> Engine:
    """One engine for one database URL, configured for SQLite when that is what it is."""
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


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


def session_scope(sessions: sessionmaker[Session]) -> Iterator[Session]:
    """One session per request, closed whatever happens to the request."""
    session = sessions()
    try:
        yield session
    finally:
        session.close()
