"""Every file the application loads at runtime has to survive being packaged.

This is the one class of bug an editable install cannot show you. `pip install -e .` points
at the source tree, so `Path(__file__).parent / "templates"` resolves to the templates you
are looking at, whatever the build backend was told to include. Build a wheel from the same
tree and the templates can simply be absent — and the first sign of it is `create_app`
raising on the `StaticFiles` mount, in a container, in a deployment, with a stack trace that
says nothing about packaging.

So this reads the declared patterns out of `pyproject.toml` and checks them against what is
actually on disk, which costs a file walk rather than a build.
"""

from __future__ import annotations

import tomllib
from fnmatch import fnmatch
from pathlib import Path

PACKAGES = Path(__file__).resolve().parent.parent / "src"
PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

#: Extensions that are Python, and are therefore included by the packages-find machinery
#: rather than by `package-data`.
CODE = {".py"}

#: Directories the build backend never sees.
IGNORED = {"__pycache__", ".mypy_cache"}


def declared() -> dict[str, list[str]]:
    with PYPROJECT.open("rb") as handle:
        config = tomllib.load(handle)
    data: dict[str, list[str]] = config["tool"]["setuptools"]["package-data"]
    return data


def shipped_files(package: str) -> list[str]:
    """Every non-Python file under a package, as a path relative to it."""
    root = PACKAGES / package
    return [
        found.relative_to(root).as_posix()
        for found in sorted(root.rglob("*"))
        if found.is_file()
        and found.suffix not in CODE
        and not any(part in IGNORED for part in found.relative_to(root).parts)
    ]


def test_every_runtime_asset_is_declared_as_package_data() -> None:
    """A template or a stylesheet nobody declared is a template that is not in the wheel."""
    patterns = declared()

    undeclared = [
        f"{package}/{found}"
        for package in patterns
        for found in shipped_files(package)
        if not any(fnmatch(found, pattern) for pattern in patterns[package])
    ]

    assert undeclared == [], (
        "these files are loaded at runtime but are not in [tool.setuptools.package-data], "
        f"so a built wheel would not contain them: {undeclared}"
    )


def test_the_web_package_declares_its_templates_and_static_files() -> None:
    """The specific regression: a wheel that installed a web app with no pages in it."""
    patterns = declared()

    assert "chainsight_web" in patterns
    assert any(found.startswith("templates/") for found in shipped_files("chainsight_web"))
    assert any(found.startswith("static/") for found in shipped_files("chainsight_web"))
