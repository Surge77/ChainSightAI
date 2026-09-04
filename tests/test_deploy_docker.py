"""The generic-host deployment, checked against the application it deploys.

`test_deploy_hf.py` is the same idea for the Space, and its opening paragraph argues why any
of this is worth a test file: none of it builds an image, and what it catches is the class of
mistake that survives review and then costs an afternoon in a container log.

This file exists separately rather than as a parametrised version of that one because the two
deployments disagree about the thing most likely to break them. The Space is told its port at
build time and must bake it in; a generic host chooses a port at run time and the image must
not. A test that accepted either would notice neither going wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEPLOY = REPO / "deploy" / "docker"
DOCKERFILE = DEPLOY / "Dockerfile"
ENTRYPOINT = DEPLOY / "entrypoint.sh"
BLUEPRINT = REPO / "render.yaml"

#: Names the deployment invents for itself. Everything else it sets has to be a name the
#: application actually reads.
NOT_APPLICATION_SETTINGS = {
    "CHAINSIGHT_ADMIN_EMAIL",
    "CHAINSIGHT_ADMIN_PASSWORD",
}

SETTING = re.compile(r"CHAINSIGHT_[A-Z_]+")


def settings_the_application_reads() -> set[str]:
    return {
        found
        for source in (REPO / "src").rglob("*.py")
        for found in SETTING.findall(source.read_text(encoding="utf-8"))
    }


def blueprint_lines() -> list[str]:
    """`render.yaml` without its comments, parsed by hand rather than with PyYAML.

    A test-only YAML dependency to read nine keys would be the largest thing this repository
    installs in order to check one file, and `test_deploy_hf.py` already reads a Space's front
    matter the same way.
    """
    return [
        stripped
        for line in BLUEPRINT.read_text(encoding="utf-8").splitlines()
        if (stripped := line.split("#", 1)[0].strip())
    ]


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

    def test_it_does_not_bake_in_a_port(self) -> None:
        """The one difference from the Space that a wrong answer hides completely.

        Render, Koyeb and Fly inject `PORT` and route to it. An image that sets its own binds
        a number nobody is talking to: it builds, it starts, it logs a clean startup line, and
        the health check times out against a port that is not open.
        """
        assert "CHAINSIGHT_PORT" not in DOCKERFILE.read_text(encoding="utf-8")

    def test_it_binds_every_interface(self) -> None:
        """`config.py` defaults to 127.0.0.1, which inside a container answers only itself."""
        assert "CHAINSIGHT_HOST=0.0.0.0" in DOCKERFILE.read_text(encoding="utf-8")

    def test_it_builds_from_the_repository_it_lives_in(self) -> None:
        """The context is the repository root, so these are repository paths."""
        body = DOCKERFILE.read_text(encoding="utf-8")

        assert "COPY --chown=user:user src ./src" in body
        assert 'pip install --no-cache-dir --user ".[web,postgres]"' in body
        assert "https://github.com" not in body

    def test_the_sample_it_trains_on_is_copied_in(self) -> None:
        """`train --sample` reads a path relative to the working directory."""
        assert "data/sample_orders.csv ./data/sample_orders.csv" in DOCKERFILE.read_text(
            encoding="utf-8"
        )

    def test_it_ships_no_trained_model(self) -> None:
        """SECURITY.md refuses to commit a joblib; an image is not a loophole in that."""
        body = DOCKERFILE.read_text(encoding="utf-8")

        assert ".joblib" not in body
        assert "chainsight train --sample --promote" in body

    def test_it_serves_from_the_directory_the_build_trained_into(self) -> None:
        """The coupling with no error message on either end of it.

        `chainsight train` writes to `persistence.ARTEFACTS_DIR`, which is a *relative*
        `Path("artifacts")` resolved against the working directory. The application reads
        `CHAINSIGHT_ARTEFACTS`. Nothing connects the two but this Dockerfile agreeing with
        itself, and disagreeing is silent twice over: the build succeeds, having trained a
        model, and the container starts, serving from a directory nobody put one in.
        """
        body = DOCKERFILE.read_text(encoding="utf-8")
        workdir = next(
            line.removeprefix("WORKDIR ").strip()
            for line in body.splitlines()
            if line.startswith("WORKDIR ")
        )

        assert f"ENV CHAINSIGHT_ARTEFACTS={workdir}/artifacts" in body

    def test_the_dataset_it_points_the_retrain_button_at_is_the_one_it_copied(self) -> None:
        """A path that does not exist here is an admin page whose retrain button always fails."""
        body = DOCKERFILE.read_text(encoding="utf-8")
        workdir = next(
            line.removeprefix("WORKDIR ").strip()
            for line in body.splitlines()
            if line.startswith("WORKDIR ")
        )

        assert f"ENV CHAINSIGHT_DATASET={workdir}/data/sample_orders.csv" in body

    def test_the_entrypoint_it_names_is_there_at_the_path_it_copies(self) -> None:
        body = DOCKERFILE.read_text(encoding="utf-8")

        assert "deploy/docker/entrypoint.sh /home/user/entrypoint.sh" in body
        assert 'CMD ["sh", "/home/user/entrypoint.sh"]' in body
        assert ENTRYPOINT.exists()


class TestTheEntrypoint:
    def test_it_has_unix_line_endings(self) -> None:
        """CRLF here fails in the container with `\\r: not found`, naming neither file nor cause."""
        assert b"\r" not in ENTRYPOINT.read_bytes()

    def test_it_hands_the_injected_port_to_the_application(self) -> None:
        """`PORT` is the platforms' name for it and `CHAINSIGHT_PORT` is the application's."""
        assert 'export CHAINSIGHT_PORT="${PORT:-8000}"' in ENTRYPOINT.read_text(encoding="utf-8")

    def test_it_refuses_to_start_without_the_administrator_secrets(self) -> None:
        """Missing secrets should stop the container, not start one nobody can sign in to."""
        body = ENTRYPOINT.read_text(encoding="utf-8")

        assert "CHAINSIGHT_ADMIN_EMAIL:?" in body
        assert "CHAINSIGHT_ADMIN_PASSWORD:?" in body

    def test_it_does_not_reset_an_existing_administrators_password(self) -> None:
        """It runs on every start, and a free instance is restarted often."""
        commands = "\n".join(
            line
            for line in ENTRYPOINT.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )

        assert "--reset-password" not in commands


class TestTheBlueprint:
    def test_it_points_at_a_dockerfile_that_exists(self) -> None:
        lines = blueprint_lines()

        assert "dockerfilePath: ./deploy/docker/Dockerfile" in lines
        assert DOCKERFILE.exists()

    def test_it_builds_from_the_repository_root(self) -> None:
        """The image copies `src/` and the sample, neither of which is beside the Dockerfile."""
        assert "dockerContext: ." in blueprint_lines()

    def test_every_secret_it_names_is_unsynced(self) -> None:
        """A value here would be a credential in git history.

        `sync: false` is what makes that unexpressible rather than merely absent: Render
        prompts for the value and stores it, and no edit to this file can supply one.
        """
        lines = blueprint_lines()
        keys = [line.removeprefix("- key: ") for line in lines if line.startswith("- key: ")]

        assert keys, "the blueprint names no environment variables at all"
        for key in keys:
            assert lines[lines.index(f"- key: {key}") + 1] == "sync: false", key

    def test_the_secrets_it_names_are_ones_the_deployment_reads(self) -> None:
        known = settings_the_application_reads() | NOT_APPLICATION_SETTINGS
        named = {
            found
            for line in blueprint_lines()
            if line.startswith("- key: ")
            for found in SETTING.findall(line)
        }

        assert named <= known, f"nothing reads: {sorted(named - known)}"

    def test_it_names_the_four_the_container_cannot_start_without(self) -> None:
        """The session secret and the database are refusals; the admin pair stops the entrypoint."""
        named = set(SETTING.findall(BLUEPRINT.read_text(encoding="utf-8")))

        assert {
            "CHAINSIGHT_SESSION_SECRET",
            "CHAINSIGHT_DATABASE",
            "CHAINSIGHT_ADMIN_EMAIL",
            "CHAINSIGHT_ADMIN_PASSWORD",
        } <= named

    def test_its_health_check_needs_no_session_and_no_database(self) -> None:
        """`/` is a 303 to the sign-in page, so it passes whenever the router works.

        A check that needs a row also fails the deploy whenever the Postgres is asleep, which
        on a free tier is most of the time.
        """
        assert "healthCheckPath: /login" in blueprint_lines()
        assert '"/login"' in (REPO / "src" / "chainsight_web" / "routes_auth.py").read_text(
            encoding="utf-8"
        )
