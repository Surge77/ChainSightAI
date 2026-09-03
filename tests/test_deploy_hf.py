"""The deployment files, checked against the application they deploy.

None of this builds an image. What it catches is the class of mistake that survives review
and then costs an afternoon in a container log: a port declared in two places that disagree,
a shell script that arrives with Windows line endings, and — the one that motivated the
file — an environment variable spelled `ARTIFACTS` in a Dockerfile against a `Settings` that
reads `ARTEFACTS`. That last failure is silent. The application starts, uses its default, and
serves from a directory nobody put a model in.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / "deploy" / "hf"
DOCKERFILE = DEPLOY / "Dockerfile"
ENTRYPOINT = DEPLOY / "entrypoint.sh"
SPACE_README = DEPLOY / "README-space.md"

#: Names the deployment invents for itself. Everything else it sets has to be a name the
#: application actually reads.
NOT_APPLICATION_SETTINGS = {
    "CHAINSIGHT_ADMIN_EMAIL",
    "CHAINSIGHT_ADMIN_PASSWORD",
    "CHAINSIGHT_REF",
    "CHAINSIGHT_SLUG",
}

SETTING = re.compile(r"CHAINSIGHT_[A-Z_]+")


def settings_the_application_reads() -> set[str]:
    return {
        found
        for source in (REPO / "src").rglob("*.py")
        for found in SETTING.findall(source.read_text(encoding="utf-8"))
    }


def front_matter() -> dict[str, str]:
    """The Space's YAML header, parsed by hand rather than with a test-only dependency."""
    text = SPACE_README.read_text(encoding="utf-8")
    _, header, _ = text.split("---\n", 2)
    pairs = (line.split(":", 1) for line in header.splitlines() if ":" in line)
    return {key.strip(): value.strip() for key, value in pairs}


class TestTheSpaceHeader:
    def test_it_is_a_docker_space(self) -> None:
        """No SDK template hosts a server-rendered app with sessions and an admin surface."""
        assert front_matter()["sdk"] == "docker"

    def test_the_declared_port_is_the_one_the_application_is_told_to_bind(self) -> None:
        """Disagree and the Space builds, starts, and answers nothing."""
        port = front_matter()["app_port"]

        assert f"CHAINSIGHT_PORT={port}" in DOCKERFILE.read_text(encoding="utf-8")
        assert f"EXPOSE {port}" in DOCKERFILE.read_text(encoding="utf-8")


class TestTheImage:
    def test_every_setting_it_exports_is_one_the_application_reads(self) -> None:
        """`ARTIFACTS` for `ARTEFACTS` starts cleanly and serves from the wrong directory."""
        known = settings_the_application_reads() | NOT_APPLICATION_SETTINGS
        exported = {
            found
            for line in DOCKERFILE.read_text(encoding="utf-8").splitlines()
            if line.startswith(("ENV ", "ARG "))
            for found in SETTING.findall(line)
        }

        assert exported <= known, f"not read by anything in src/: {sorted(exported - known)}"

    def test_it_installs_a_named_tag_rather_than_a_moving_branch(self) -> None:
        """A Space rebuilt against whatever `main` was is not a thing you can reason about."""
        declared = re.search(r"ARG CHAINSIGHT_REF=(\S+)", DOCKERFILE.read_text(encoding="utf-8"))

        assert declared is not None
        assert re.fullmatch(r"v\d+\.\d+\.\d+", declared.group(1))

    def test_it_ships_no_trained_model(self) -> None:
        """SECURITY.md refuses to commit a joblib; an image is not a loophole in that."""
        body = DOCKERFILE.read_text(encoding="utf-8")

        assert ".joblib" not in body
        assert "chainsight train --sample --promote" in body

    def test_the_entrypoint_it_names_is_there(self) -> None:
        assert "entrypoint.sh" in DOCKERFILE.read_text(encoding="utf-8")
        assert ENTRYPOINT.exists()


class TestTheEntrypoint:
    def test_it_has_unix_line_endings(self) -> None:
        """CRLF here fails in the container with `\\r: not found`, naming neither file nor cause."""
        assert b"\r" not in ENTRYPOINT.read_bytes()

    def test_it_refuses_to_start_without_the_administrator_secrets(self) -> None:
        """Missing secrets should stop the container, not start one nobody can sign in to."""
        body = ENTRYPOINT.read_text(encoding="utf-8")

        assert "CHAINSIGHT_ADMIN_EMAIL:?" in body
        assert "CHAINSIGHT_ADMIN_PASSWORD:?" in body

    def test_it_does_not_reset_an_existing_administrators_password(self) -> None:
        """It runs on every start. `--reset-password` would rewrite the account each time."""
        commands = "\n".join(
            line
            for line in ENTRYPOINT.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )

        assert "--reset-password" not in commands
