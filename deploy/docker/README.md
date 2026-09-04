# Deploying ChainSight to a generic Docker host

`deploy/hf/` deploys the same application to a Hugging Face Space. This directory is for
everywhere else — Render, Koyeb, Fly — and exists because a Space is not a generic host: it
fixes the port at 7860, reads its configuration from the front matter of its own README, and
is fed an assembled tree by `push-space.sh` rather than this repository.

Nothing here needs an assembly step. The repository is public, so the platform clones it and
builds `deploy/docker/Dockerfile` against the repository root. There is no script to run.

The one difference that will bite you if you write your own image: **the port is not known at
build time.** These platforms inject `PORT` and route to it, so `entrypoint.sh` maps it onto
`CHAINSIGHT_PORT`. An image that bakes a port in builds, starts, logs a clean startup line,
and fails its health check against a port nothing is listening on.

## Before anything else

**Create a Postgres.** Any managed one; the free tier of a serverless Postgres is the point
of [ADR 0014](../../docs/adr/0014-postgres-when-the-filesystem-does-not-persist.md). A free
instance's filesystem is rebuilt on every deploy, restart and wake from sleep, so a database
file would take every registered account with it, and would reset the `attempts` table —
which would make "cause a restart" the cheapest way past the rate limit.

Take the **pooled** connection string and **rewrite the scheme**:

```
postgresql+psycopg://user:password@host-pooler.region.provider.tech/dbname?sslmode=require
```

Pasted as `postgresql://` it fails at startup with
`ModuleNotFoundError: No module named 'psycopg2'`, because SQLAlchemy resolves the default
driver from the scheme and psycopg2 is not installed. `channel_binding=require` is understood
and can stay.

## Render

`render.yaml` at the repository root is a Blueprint: point Render at the repository, and the
service, its Dockerfile, its health check and the *names* of its four secrets all come from
that file. The values do not, and cannot — every one is `sync: false`, so Render prompts for
them and stores them itself. A blueprint that could carry a secret would be a secret in git
history.

1. **New → Blueprint**, select this repository, apply.
2. Render prompts for the four below. Set all four; the container will not start without them.
3. First build takes several minutes — it installs pandas, scikit-learn and friends, then
   fits the sample.

## Any other host

Build `deploy/docker/Dockerfile` with the **repository root** as the context, and set the same
four variables. The image already sets everything else it needs.

```sh
docker build -f deploy/docker/Dockerfile -t chainsight .
docker run --rm -p 8000:8000 \
  -e PORT=8000 \
  -e CHAINSIGHT_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  -e CHAINSIGHT_DATABASE="postgresql+psycopg://…" \
  -e CHAINSIGHT_ADMIN_EMAIL="you@example.com" \
  -e CHAINSIGHT_ADMIN_PASSWORD="at least ten characters" \
  chainsight
```

## The four secrets

| variable | what it is |
|---|---|
| `CHAINSIGHT_SESSION_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `CHAINSIGHT_DATABASE` | the `postgresql+psycopg://…` URL above |
| `CHAINSIGHT_ADMIN_EMAIL` | your administrator account |
| `CHAINSIGHT_ADMIN_PASSWORD` | at least 10 characters |

The last two are read by `entrypoint.sh`, which runs `python -m chainsight_web init` on every
container start. That is safe to repeat: `init` against an account that already exists leaves
its password alone and exits 0, because `--reset-password` is not passed. It matters more here
than on a Space, because a free instance sleeps and is restarted often.

## What it will and will not do

**It has a public registration form,** and a rate limiter in front of it — five accounts per
source address per hour, ten sign-in attempts per fifteen minutes. See
[ADR 0013](../../docs/adr/0013-count-attempts-per-address.md) for what that catches and, more
usefully, what it does not: a brute force spread across many addresses is not slowed down at
all.

**It trains on 500 rows.** The full DataCo table is ~92 MB and is not ours to redistribute.
`CHAINSIGHT_DATASET` points the retrain button at the committed sample, so retraining from
`/admin` works and produces a model fitted on 500 orders. Do not quote its scores.

**The first request after idle is slow, and this deployment pings itself about it.** A free
instance sleeps after minutes without traffic and a serverless Postgres suspends on its own
schedule. Both wake on demand, and the first request pays for both — about fifty seconds of
it is the container.

A keep-alive pinger is the obvious fix and is half wrong, which is why *what* it pings is the
whole decision. Point it at a page and it wakes the database too, spending the metered
resource to protect the unmetered one. Point it at `/static/favicon.svg` and it wakes only the
container: that path is served by `StaticFiles`, so it touches no session, no database and no
rate-limit budget. The fifty seconds go and Postgres stays asleep, leaving the first real
sign-in to pay a wake measured in seconds instead.

The live deployment runs exactly that — UptimeRobot, five-minute interval, against the favicon
— because Render sleeps a free instance after fifteen minutes and five is a comfortable margin.

What that costs is worth writing down, because it is not obvious and it is shared. Render's
free allowance is **750 instance-hours per month across the whole workspace**, not per service.
A service kept awake around the clock spends roughly 730 of them, so one pinger very nearly
exhausts the account. It fits here only because the other free service in this workspace is
genuinely idle — measured at half an hour across four days — and it would stop fitting the
moment a second service were kept warm the same way. Scheduling the pinger to sleep overnight
would be the fix; UptimeRobot puts maintenance windows behind a paid plan, so the alternative
on the free tier is the Pause button and remembering to use it.

## If it does not come up

Read the deploy log. This application fails closed and says why:

- `CHAINSIGHT_SESSION_SECRET is not set` — the variable is not reaching the container.
- `set CHAINSIGHT_ADMIN_EMAIL in the service environment` — the entrypoint's own refusal;
  the admin pair is missing.
- `ModuleNotFoundError: No module named 'psycopg2'` — the URL scheme still says
  `postgresql://`.
- `the <table> table in this database is missing <column>` — the Postgres was created by an
  older tag. There is no migration tool; drop the tables and let it build them again.
- A health check that times out on a container whose log looks fine — something set a port.
  `PORT` is the platform's, `CHAINSIGHT_PORT` is the application's, and `entrypoint.sh` is
  the only place they are meant to meet.
