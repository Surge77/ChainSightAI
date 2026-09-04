# ChainSight as a container on a generic Docker host.
#
# `deploy/hf/` is the same application shaped for one platform: Hugging Face fixes the port
# at 7860, configures the Space from YAML at the top of its README, and is fed an assembled
# tree by `push-space.sh` rather than this repository. None of those three things is true
# anywhere else, so this is a second Dockerfile rather than a flag on the first. Trying to
# make one file serve both would mean a build that reads its own platform out of the
# environment, which is more machinery than a forty-line file duplicated once.
#
# The differences, in full:
#
#   * The build context is the repository root, not an assembled tree. So `COPY` paths here
#     are repository paths, and the project's own `README.md` is the one that ships — there
#     is no README to swap because there is no front matter to carry.
#   * The port is not known at build time. Render, Koyeb and Fly each inject `PORT` and
#     expect the process to bind whatever they chose; `entrypoint.sh` reads it. Baking a
#     port in the way the Space does would produce a container that starts, listens on the
#     wrong number, and fails a health check with nothing in its log.
#
# Everything else — training at build rather than shipping a joblib, the non-root user, the
# refusal to hold a session secret — is the same decision for the same reason, and the
# comments beside each of those in `deploy/hf/Dockerfile` are the long version.

FROM python:3.12-slim

# Non-root, and the working directory handed over before the USER switch: WORKDIR creates a
# missing directory as root whatever USER is in effect, and a root-owned working directory is
# a build that dies later, in the training step, with a permission error that says nothing
# about this line. The uid is 1000 for the same reason it is on the Space — it is what every
# platform's rootless runtime expects to find.
RUN useradd --create-home --uid 1000 user \
 && mkdir -p /home/user/app/data \
 && chown -R user:user /home/user/app

USER user
WORKDIR /home/user/app

ENV PATH=/home/user/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# `pyproject.toml` names README.md as the package readme; the build fails without it.
COPY --chown=user:user pyproject.toml README.md ./
COPY --chown=user:user src ./src

# The 500-order committed slice. The full DataCo table is ~92 MB and is not ours to
# redistribute, so it is not here and will not be — see `SECURITY.md`.
COPY --chown=user:user data/sample_orders.csv ./data/sample_orders.csv

# `[web,postgres]`. Postgres is not optional on a host like this one for the reason ADR 0014
# gives: the filesystem is rebuilt on every deploy, restart and wake from sleep.
RUN python -m pip install --no-cache-dir --user ".[web,postgres]"

# Train at build rather than shipping a joblib. `SECURITY.md` says loading an artefact
# somebody sent you is equivalent to running a script they sent you, and a repository that
# refuses to commit a pickled model should not smuggle one into an image.
RUN python -m chainsight train --sample --promote

ENV CHAINSIGHT_HOST=0.0.0.0
ENV CHAINSIGHT_ARTEFACTS=/home/user/app/artifacts

# A retrain reads a file on the server and never anything entered through the UI, which is
# what stops an operator poisoning the training set through a form. Here that file is the
# sample: the real table is not in the image, and leaving this at its default would point the
# admin page's retrain button at a path that does not exist.
ENV CHAINSIGHT_DATASET=/home/user/app/data/sample_orders.csv

# Trust the forwarding header from anybody, which is right *here* and nowhere else: the only
# route into this container is the platform's ingress, and it sets X-Forwarded-For itself.
# Without this every visitor arrives wearing the load balancer's address, shares one
# rate-limit budget, and the tenth wrong password anybody types locks out the whole
# deployment. `config.py` argues both ways of getting this wrong.
ENV CHAINSIGHT_FORWARDED_ALLOW_IPS=*

# Short, because this is a public demo and a stolen cookie should not outlive by a working
# day the session that leaked it.
ENV CHAINSIGHT_SESSION_HOURS=2

# CHAINSIGHT_SESSION_SECRET, CHAINSIGHT_DATABASE, CHAINSIGHT_ADMIN_EMAIL and
# CHAINSIGHT_ADMIN_PASSWORD are deliberately absent. They are set on the platform at run
# time, and `render.yaml` marks all four `sync: false` so none of them can arrive from a
# file in this repository. The application refuses to start without a session secret rather
# than inventing one, so a secret that fails to arrive is a container that exits saying so.

COPY --chown=user:user deploy/docker/entrypoint.sh /home/user/entrypoint.sh

# Informational only — every platform this targets routes to the port it injected, not to
# this number. It is the default `entrypoint.sh` falls back to when nothing injects one,
# which is what happens when you run the image on your own machine.
EXPOSE 8000

CMD ["sh", "/home/user/entrypoint.sh"]
