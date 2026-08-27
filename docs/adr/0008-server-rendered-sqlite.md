# 0008 — Server-rendered pages over SQLite, not an SPA

**Status:** accepted

## Context

The application has perhaps a dozen pages, one user at a time, and no offline or mobile
requirement. The default modern answer is a JSON API with a JavaScript front end.

## Decision

Server-rendered Jinja2 templates, one stylesheet, one CDN script for the charts. SQLAlchemy
over SQLite.

## Consequences

**What it buys.** No build step, no bundler, no second language, no client-side state to keep
in step with the server's. Authorisation is a `WHERE` clause in the query that renders the
page rather than a rule enforced in two places. There is no cross-origin case to permit, so
CORS is simply not enabled rather than configured permissively "just in case".

**What it costs.** No optimistic UI, and a full page load per action. For this application
that is invisible.

**SQLite specifically** is sufficient for a single-node portfolio deployment, and saying so is
more honest than adding a database server to a diagram. The schema uses nothing SQLite-only
and every timestamp is a real `DateTime` rather than a string that sorts correctly by luck, so
the swap to Postgres stays possible.

There is no migration tool. One deployment, and a schema change means a new database file —
stated here rather than discovered.

A retrain runs to completion inside the request. Every handler is `def` rather than
`async def`, so FastAPI runs it in a threadpool and minutes of CPU-bound scikit-learn do not
block the event loop and stall every other request in the process. The page says how long it
will take.

One property falls out of this design rather than being enforced: **retraining reads a file on
the server, so nothing entered through the UI can reach the training set.** `SECURITY.md`
previously listed operator poisoning of the retraining set among the undefended items; it is
closed by construction.
