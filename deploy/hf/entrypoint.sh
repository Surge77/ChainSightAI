#!/bin/sh
# Make the administrator, then serve. Runs on every container start.
#
# `python -m chainsight_web init` is normally a thing you type on a server, because there is
# nobody to authorise the first administrator and a "first user to register becomes admin"
# rule is a race with whoever reaches the port first. A Space has no shell, so the container
# start *is* the server-side moment, and this is it.
#
# Running it every start is safe by construction rather than by a check here: `init` on an
# account that already exists leaves its password alone and returns 0 unless
# --reset-password was passed, which it is not. On the first start against an empty database
# it creates the account; on every start after that it is a no-op that prints a line.
#
# The password reaches `init` as an argument, so it is visible in this container's own
# process list. That is a real thing to know and a small one: the container is single-tenant
# and the same value is already in its environment, which is no harder to read. The
# alternative, `init`'s interactive prompt, needs a terminal that a Space does not have.

set -eu

: "${CHAINSIGHT_ADMIN_EMAIL:?set CHAINSIGHT_ADMIN_EMAIL as a Space secret}"
: "${CHAINSIGHT_ADMIN_PASSWORD:?set CHAINSIGHT_ADMIN_PASSWORD as a Space secret}"

python -m chainsight_web init \
  --email "$CHAINSIGHT_ADMIN_EMAIL" \
  --password "$CHAINSIGHT_ADMIN_PASSWORD"

exec python -m chainsight_web serve
