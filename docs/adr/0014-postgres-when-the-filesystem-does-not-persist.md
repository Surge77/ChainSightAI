# 0014 — Postgres when the filesystem does not persist

**Status:** accepted, supersedes the storage half of [0008](0008-server-rendered-sqlite.md)

## Context

ADR 0008 chose SQLite and wrote down the escape clause in the same breath:

> **SQLite specifically** is sufficient for a single-node portfolio deployment, and saying so
> is more honest than adding a database server to a diagram. The schema uses nothing
> SQLite-only and every timestamp is a real `DateTime` rather than a string that sorts
> correctly by luck, so the swap to Postgres stays possible.

Deploying this somewhere public is what asks for the swap. A container platform's filesystem
is rebuilt on every restart, every redeploy, and every wake from sleep. `chainsight.db` on
that filesystem means every account anybody registers is gone by the next morning, and the
`attempts` table that [0013](0013-count-attempts-per-address.md) counts a brute force in is
reset by anything that restarts the process — which makes the cheapest way past the rate
limit "cause a restart".

The alternative was the platform's own attached storage. It is a paid add-on on the platform
in question, and it is attached to the *deployment*: delete or recreate the space and the
data goes with it, which is exactly what you do several times while getting a container
right.

## Decision

Support Postgres through `CHAINSIGHT_DATABASE`, keep SQLite as the default, and configure the
pool for a database that is allowed to disappear between requests.

`psycopg[binary]` is its own extra rather than part of `[web]`, for the same reason `[web]`
is separate from the base package: nothing in `chainsight_web` imports it — SQLAlchemy loads
the driver named in the URL — so somebody running this against a file should not have to
acquire a database driver to do it.

Two settings, both in `engine_options`:

- **`pool_pre_ping`.** A serverless Postgres suspends an idle branch and drops its
  connections. The pool is not told, hands the next request a closed socket, and the request
  dies with `OperationalError: server closed the connection unexpectedly` — then succeeds on
  a retry, which reads as flakiness rather than as configuration. One round trip per checkout
  turns the whole class of failure into a reconnect nobody sees.
- **`pool_recycle`, at 300 seconds.** Shorter than any upstream idle timeout worth having, so
  the pool decides a connection is stale rather than discovering it.

## Consequences

**A second CI job.** The web suite runs again against a real `postgres:17` service. Without
it the dialect a deployment serves on is the one dialect nothing tests, and the differences
are not cosmetic: SQLite has no timestamp type and hands back a **naive** datetime from a
`DateTime(timezone=True)` column where Postgres hands back an aware one. Subtracting one from
the other is a `TypeError`, not a wrong answer — so `throttle.as_utc` exists, and the job is
what proves it is needed rather than superstition.

**The URL needs its driver named.** A managed Postgres hands you `postgresql://…`. Pasted
verbatim, SQLAlchemy resolves the default DBAPI, psycopg2, which is not installed, and
startup fails with `ModuleNotFoundError: No module named 'psycopg2'` — measured, not
predicted. The scheme has to be rewritten to `postgresql+psycopg://`, and `README.md` says so
where the setting is documented.

**A third secret.** `SECURITY.md` could previously say the only secrets were a session secret
and an optional Kaggle credential. A Postgres URL carries its password in the string, so it
joins them, and it is a secret rather than a variable wherever a platform distinguishes them.

**No migration tool, still.** `create_all` adds tables and cannot add columns, and
`verify_schema` turns a database that predates a column into a startup message naming it.
That was already the deal in 0008; moving to Postgres does not change it, and it is more
visible now that dropping the database file is no longer a local `rm`.

**Concurrent startups race, harmlessly.** Two processes calling `create_all` against one
Postgres can collide. One deployment, one process, and the loser of that race is a startup
that fails loudly and restarts — which is why this is recorded rather than defended against.
