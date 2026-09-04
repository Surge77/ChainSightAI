#!/bin/sh
# Bind the port the platform chose, make the administrator, then serve.
#
# The Space's entrypoint does not have this first job. Hugging Face fixes the port at 7860
# and the Dockerfile can bake it in; Render, Koyeb and Fly each pick a port, inject it as
# `PORT`, and route to that. A container that ignores it starts cleanly, listens on a number
# nobody is talking to, and fails its health check with an empty log — which is the whole
# reason this line is not a default in `config.py`. `PORT` is the platforms' name and
# `CHAINSIGHT_PORT` is the application's; this is the one place they are allowed to meet.
#
# The fallback is for running the image on your own machine, where nothing injects anything.
export CHAINSIGHT_PORT="${PORT:-8000}"

# `python -m chainsight_web init` is normally a thing you type on a server, because there is
# nobody to authorise the first administrator and a "first user to register becomes admin"
# rule is a race with whoever reaches the port first. These platforms have no shell before
# the first deploy, so the container start *is* the server-side moment, and this is it.
#
# Running it every start is safe by construction rather than by a check here: `init` on an
# account that already exists leaves its password alone and returns 0 unless
# --reset-password was passed, which it is not. On the first start against an empty database
# it creates the account; on every start after that it is a no-op that prints a line. That
# matters more here than on a Space, because a free instance sleeps and is restarted often.
#
# The password reaches `init` as an argument, so it is visible in this container's own
# process list. That is a real thing to know and a small one: the container is single-tenant
# and the same value is already in its environment, which is no harder to read. The
# alternative, `init`'s interactive prompt, needs a terminal that a deploy does not have.

set -eu

: "${CHAINSIGHT_ADMIN_EMAIL:?set CHAINSIGHT_ADMIN_EMAIL in the service environment}"
: "${CHAINSIGHT_ADMIN_PASSWORD:?set CHAINSIGHT_ADMIN_PASSWORD in the service environment}"

python -m chainsight_web init \
  --email "$CHAINSIGHT_ADMIN_EMAIL" \
  --password "$CHAINSIGHT_ADMIN_PASSWORD"

exec python -m chainsight_web serve
