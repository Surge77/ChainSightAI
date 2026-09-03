# Deploying ChainSight as a Hugging Face Space

`push-space.sh` does the assembly: a `git archive` of the commit you are on, plus the
`Dockerfile` and `entrypoint.sh` here, plus `README-space.md` as the Space's `README.md`. A
Space is configured by the YAML front matter at the top of its README, and this repository's
own README should not carry a platform's config table above its first paragraph — which is
why the two are separate files rather than one.

The image builds from that source rather than installing a tag from GitHub. The tidier
version did the latter and does not work: **this repository is private**, so an
unauthenticated build gets a 404 from the release tarball and the raw file alike, and fixing
that with a token would put a credential in a deployment to avoid copying files it is already
being handed. If you make the repository public, installing a pinned tag becomes possible
again and this script becomes optional.

## Before anything else

**Create a Postgres.** Any managed Postgres; the free tier of a serverless one is the point
of [ADR 0014](../../docs/adr/0014-postgres-when-the-filesystem-does-not-persist.md). A Space's
filesystem is rebuilt on every restart, so a database file would take every registered
account with it, and would reset the `attempts` table — which would make "cause a restart"
the cheapest way past the rate limit.

Take the **pooled** connection string and **rewrite the scheme**:

```
postgresql+psycopg://user:password@host-pooler.region.provider.tech/chainsight?sslmode=require
```

Pasted as `postgresql://` it fails at startup with
`ModuleNotFoundError: No module named 'psycopg2'`, because SQLAlchemy resolves the default
driver from the scheme and psycopg2 is not installed.

## The Space

Create a **Docker** Space (not Gradio — this is a server-rendered FastAPI application with
sessions, CSRF and an admin surface; no SDK template hosts it). Then, from a clean tree:

```sh
deploy/hf/push-space.sh https://huggingface.co/spaces/<you>/chainsight
```

It refuses to run against a dirty working tree, so what the Space builds is always a commit
that exists in your history. Set the secrets below **before** the first push, or the container
will build and then exit on the missing session secret.

## Settings

Everything the container needs that is not in the `Dockerfile` is a **secret**, not a
variable. Variables are readable by anyone who can view the Space, and all four of these
either are a credential or contain one.

| secret | what it is |
|---|---|
| `CHAINSIGHT_SESSION_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `CHAINSIGHT_DATABASE` | the `postgresql+psycopg://…` URL above |
| `CHAINSIGHT_ADMIN_EMAIL` | your administrator account |
| `CHAINSIGHT_ADMIN_PASSWORD` | at least 10 characters |

The last two are read by `entrypoint.sh`, which runs `python -m chainsight_web init` on every
container start. That is safe to repeat: `init` against an account that already exists leaves
its password alone and exits 0, because `--reset-password` is not passed.

## What it will and will not do

**It has a public registration form,** and a rate limiter in front of it — five accounts per
source address per hour, ten sign-in attempts per fifteen minutes. See
[ADR 0013](../../docs/adr/0013-count-attempts-per-address.md) for what that catches and, more
usefully, what it does not: a brute force spread across many addresses is not slowed down at
all.

**It trains on 500 rows.** The full DataCo table is ~92 MB and is not ours to redistribute.
`CHAINSIGHT_DATASET` points the retrain button at the committed sample, so retraining from
`/admin` works and produces a model fitted on 500 orders. Do not quote its scores.

**The first request after idle is slow.** A free Space sleeps after ~48 hours without
traffic, and a serverless Postgres suspends after minutes. Both wake on demand. A keep-alive
pinger is the obvious fix and mostly the wrong one: hitting a page every few minutes keeps
the *database* awake too, which spends the metered resource to protect the unmetered one. If
you ping anyway, ping `/static/favicon.svg` — no session, no database, and no interaction
with the rate limiter.

## If it does not come up

Read the container log. This application fails closed and says why:

- `CHAINSIGHT_SESSION_SECRET is not set` — the secret is not reaching the container.
- `ModuleNotFoundError: No module named 'psycopg2'` — the URL scheme still says `postgresql://`.
- `the <table> table in this database is missing <column>` — the Postgres was created by an
  older tag. There is no migration tool; drop the tables and let it build them again.
- A build that fails at `pip install` — the tag in `CHAINSIGHT_REF` does not exist yet.
