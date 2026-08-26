"""The taught-set gate is only worth having if it actually catches things.

Every test here writes a small module to a temp file and asks the checker about it, so
the assertions are about the checker's judgement and not about whatever `src/` happens
to contain today.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from check_taught import (
    DECLARED,
    TAUGHT_CHEATSHEET,
    TAUGHT_NOTEBOOK,
    census,
    inspect_file,
    main,
    run,
)

DEFAULT = TAUGHT_NOTEBOOK | TAUGHT_CHEATSHEET | frozenset(DECLARED)


def write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "module.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_accepts_a_name_executed_in_the_notebooks(tmp_path: Path) -> None:
    path = write(tmp_path, "from sklearn.linear_model import LogisticRegression\n")

    assert inspect_file(path, DEFAULT) == []


def test_rejects_a_name_that_is_neither_taught_nor_declared(tmp_path: Path) -> None:
    path = write(tmp_path, "from sklearn.ensemble import StackingClassifier\n")

    findings = inspect_file(path, DEFAULT)

    assert len(findings) == 1
    assert findings[0].name == "StackingClassifier"
    assert findings[0].reason == "NOT TAUGHT"


def test_a_declared_name_passes_and_carries_its_reason(tmp_path: Path) -> None:
    """Reaching outside the curriculum is allowed; doing it silently is not."""
    path = write(tmp_path, "from sklearn.preprocessing import OneHotEncoder\n")

    assert inspect_file(path, DEFAULT) == []
    assert DECLARED["OneHotEncoder"].strip()


def test_every_declared_name_says_why_it_was_reached_for() -> None:
    """The whole mechanism: adding a name means putting the justification in the diff."""
    for name, reason in DECLARED.items():
        assert len(reason.strip()) > 40, f"{name} is declared without a real reason"


def test_sees_every_name_inside_a_parenthesised_import(tmp_path: Path) -> None:
    """The regression a grep-based check would fail: the tail after `import (` is empty."""
    path = write(
        tmp_path,
        "from sklearn.ensemble import (\n"
        "    RandomForestClassifier,\n"
        "    ExtraTreesClassifier,\n"
        "    StackingClassifier,\n"
        ")\n",
    )

    findings = inspect_file(path, DEFAULT)

    assert sorted(f.name for f in findings) == ["ExtraTreesClassifier", "StackingClassifier"]


def test_cheatsheet_tier_passes_by_default_and_fails_under_strict(tmp_path: Path) -> None:
    path = write(tmp_path, "from sklearn.model_selection import GridSearchCV\n")

    assert inspect_file(path, DEFAULT) == []

    strict = inspect_file(path, TAUGHT_NOTEBOOK)
    assert len(strict) == 1
    assert strict[0].reason == "CHEATSHEET TIER, REJECTED BY --strict"


@pytest.mark.parametrize("library", ["xgboost", "lightgbm", "shap", "optuna", "mlflow"])
def test_rejects_a_banned_library_however_it_is_imported(tmp_path: Path, library: str) -> None:
    path = write(tmp_path, f"import {library}\nfrom {library}.sub import thing\n")

    findings = inspect_file(path, DEFAULT)

    assert len(findings) == 2
    assert {f.reason for f in findings} == {"BANNED LIBRARY"}


def test_rejects_importing_the_sklearn_package_itself(tmp_path: Path) -> None:
    """`import sklearn` would hide every later attribute access from this check."""
    path = write(tmp_path, "import sklearn\n")

    findings = inspect_file(path, DEFAULT)

    assert len(findings) == 1
    assert findings[0].reason == "IMPORT THE NAME, NOT THE PACKAGE"


def test_ignores_imports_that_have_nothing_to_do_with_modelling(tmp_path: Path) -> None:
    path = write(tmp_path, "import json\nfrom pathlib import Path\nimport pandas as pd\n")

    assert inspect_file(path, DEFAULT) == []


def test_the_repository_itself_is_clean() -> None:
    """The gate runs against `src/` in CI; keep it green here too."""
    assert main([]) == 0


def test_whatever_strict_mode_rejects_is_a_named_tier_and_never_a_surprise() -> None:
    """`--strict` is a record, not a pass/fail, and this is the line it must not cross.

    It may reject a cheatsheet name or a declared one, because both are departures from the
    notebooks and the strict run exists to count them. It may never reject something that
    is simply unaccounted for: that would mean a name reached `src/` without anybody
    writing down why, which is the one thing this file exists to prevent.
    """
    reasons = {finding.reason for finding in run(strict=True)}

    assert reasons <= {
        "CHEATSHEET TIER, REJECTED BY --strict",
        "DECLARED, REJECTED BY --strict",
    }


def test_the_course_material_is_still_the_backbone() -> None:
    """The original promise, kept checkable: most of what `src/` imports is taught."""
    counted = census()
    taught = len(counted["notebook"]) + len(counted["cheatsheet"])
    total = taught + len(counted["declared"])

    assert taught / total > 0.7


def test_finding_renders_a_clickable_location(tmp_path: Path) -> None:
    path = write(tmp_path, "from sklearn.svm import LinearSVC\n")

    rendered = str(inspect_file(path, DEFAULT)[0])

    assert "module.py:1: LinearSVC" in rendered
