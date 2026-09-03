# ChainSight as a Hugging Face Docker Space.
#
# The image installs a *tag* of this repository rather than copying a working tree, so what
# runs in the Space is a commit you can name. Set CHAINSIGHT_REF to that tag; if it does not
# exist the build fails at pip, which is the loud failure rather than the quiet one where a
# Space serves whatever `main` happened to be that afternoon.
#
# Installed from the release tarball rather than `git+https://`, so the image needs no git.

FROM python:3.12-slim

ARG CHAINSIGHT_SLUG=Surge77/ChainSightAI
ARG CHAINSIGHT_REF=v1.2.0

# HF runs Spaces as uid 1000. The working directory is created and handed over *before* the
# USER switch: WORKDIR creates a missing directory as root whatever USER is in effect, and a
# root-owned working directory is a build that dies later, in the training step, with a
# permission error that says nothing about this line.
RUN useradd --create-home --uid 1000 user \
 && mkdir -p /home/user/app/data \
 && chown -R user:user /home/user/app

USER user
WORKDIR /home/user/app

ENV PATH=/home/user/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# `[web,postgres]` — the application and a Postgres driver. Both are extras on purpose;
# `pyproject.toml` argues why neither belongs in the base package.
RUN python -m pip install --no-cache-dir --user \
    "chainsight[web,postgres] @ https://github.com/${CHAINSIGHT_SLUG}/archive/refs/tags/${CHAINSIGHT_REF}.tar.gz"

# The 500-order committed slice, from the same tag as the code. The full DataCo table is
# ~92 MB and is not ours to redistribute, so it is not here and will not be — see
# `SECURITY.md`. Everything this Space does runs on the sample.
ADD --chown=user:user \
    https://raw.githubusercontent.com/${CHAINSIGHT_SLUG}/${CHAINSIGHT_REF}/data/sample_orders.csv \
    /home/user/app/data/sample_orders.csv

# Train at build rather than shipping a joblib. `SECURITY.md` says loading an artefact
# somebody sent you is equivalent to running a script they sent you, and a repository that
# refuses to commit a pickled model should not smuggle one into an image either. Fitting the
# 500-row sample takes seconds, and the manifest hashes are checked on load exactly as they
# would be locally.
RUN python -m chainsight train --sample --promote

# The bind address and port the platform expects.
ENV CHAINSIGHT_HOST=0.0.0.0
ENV CHAINSIGHT_PORT=7860
ENV CHAINSIGHT_ARTEFACTS=/home/user/app/artifacts

# A retrain reads a file on the server and never anything entered through the UI, which is
# what stops an operator poisoning the training set through a form. On this Space that file
# is the sample: the real table is not in the image, and leaving this at its default would
# point the admin page's retrain button at a path that does not exist.
ENV CHAINSIGHT_DATASET=/home/user/app/data/sample_orders.csv

# Trust the forwarding header from anybody, which is right *here* and nowhere else: the only
# route into this container is the platform's ingress, and it sets X-Forwarded-For itself.
# Without this every visitor arrives wearing the proxy's address, shares one rate-limit
# budget, and the tenth wrong password anybody types locks out the whole Space.
# `config.py` argues both ways of getting this wrong.
ENV CHAINSIGHT_FORWARDED_ALLOW_IPS=*

# Short, because this is a public demo and a stolen cookie should not outlive by a working
# day the session that leaked it.
ENV CHAINSIGHT_SESSION_HOURS=2

# CHAINSIGHT_SESSION_SECRET, CHAINSIGHT_DATABASE, CHAINSIGHT_ADMIN_EMAIL and
# CHAINSIGHT_ADMIN_PASSWORD are deliberately absent. They are Space *secrets*, injected at
# run time. The application refuses to start without a session secret rather than inventing
# one, so a secret that fails to arrive is a container that exits saying exactly that.

COPY --chown=user:user entrypoint.sh /home/user/entrypoint.sh

EXPOSE 7860
CMD ["sh", "/home/user/entrypoint.sh"]
