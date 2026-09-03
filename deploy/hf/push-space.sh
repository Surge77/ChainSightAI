#!/bin/sh
# Assemble the Space's tree from the current commit and push it.
#
#     deploy/hf/push-space.sh https://huggingface.co/spaces/<you>/chainsight
#
# The tree is `git archive HEAD` — tracked files at the commit you are on, so an uncommitted
# edit cannot reach a deployment — plus the Dockerfile and entrypoint from this directory,
# plus `README-space.md` as the Space's `README.md`. A Space is configured by the YAML front
# matter at the top of its README, and this project's own README should not carry a
# platform's config table above its first paragraph; that is the whole reason the two files
# are separate rather than one.
#
# The push is `--force` to a scratch history. The Space repository is a deployment target,
# not somewhere work happens, and a fast-forward-only push would need this script to carry
# the Space's previous commits around for no reason anybody benefits from.

set -eu

SPACE="${1:?usage: deploy/hf/push-space.sh <space git url>}"
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"

# Refuse to deploy something that is not committed. The image would still build; it would
# just be built from a commit that does not exist anywhere, which is the state you cannot
# reason about later when the Space is behaving oddly.
if ! git -C "$REPO" diff-index --quiet HEAD --; then
    echo "working tree is dirty — commit or stash before deploying" >&2
    exit 1
fi

DESCRIBED="$(git -C "$REPO" describe --always --dirty)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git -C "$REPO" archive HEAD | tar -x -C "$WORK"
cp "$HERE/Dockerfile" "$HERE/entrypoint.sh" "$WORK/"
cp "$HERE/README-space.md" "$WORK/README.md"

cd "$WORK"
git init -q
git add -A
git -c user.name="chainsight-deploy" -c user.email="deploy@localhost" \
    commit -q -m "ChainSight $DESCRIBED"
git push -q --force "$SPACE" HEAD:main

echo "pushed $DESCRIBED to $SPACE"
