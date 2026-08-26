"""Fail the build if `src/` reaches for machine learning this project never studied.

ChainSight is deliberately built from one curriculum: the notebooks under
`ML/Resource Files` and `ML/Personal Files`, and the revision notes under `ML/Test Prep`.
The point is not asceticism. A portfolio project whose headline number comes from a
library the author cannot explain is worth less than a smaller number the author can
derive. This script is the mechanism that keeps that promise honest, because good
intentions do not survive a late-night debugging session.

Two tiers are allowed:

* ``TAUGHT_NOTEBOOK`` -- names actually executed in a notebook's code cells.
* ``TAUGHT_CHEATSHEET`` -- names written out in ``01_CHEATSHEET.md`` or the MCQ answers
  but never run. Using one of these is a small stretch, so ``--strict`` rejects them and
  CI records both results.

Anything else fails, and so does importing a banned library at all.

    python scripts/check_taught.py            # notebook tier + cheatsheet tier
    python scripts/check_taught.py --strict   # notebook tier only
    python scripts/check_taught.py --list     # print the allowed names and exit

The check parses the AST rather than grepping. A parenthesised import spanning several
lines defeats a regex -- ``from sklearn.ensemble import (`` matches an empty tail, the
grep passes, and every name inside the brackets goes unexamined. `ast` cannot be fooled
by formatting.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

#: Executed in the code cells of the course notebooks. Source of truth for this project.
TAUGHT_NOTEBOOK: frozenset[str] = frozenset(
    {
        # model_selection
        "train_test_split",
        # pipeline and preprocessing
        "Pipeline",
        "StandardScaler",
        "PolynomialFeatures",
        "LabelEncoder",
        # regression
        "LinearRegression",
        "Ridge",
        "Lasso",
        # classification
        "LogisticRegression",
        "KNeighborsClassifier",
        "SVC",
        "DecisionTreeClassifier",
        "RandomForestClassifier",
        "BaggingClassifier",
        "VotingClassifier",
        # unsupervised
        "KMeans",
        # text
        "TfidfVectorizer",
        # metrics
        "r2_score",
        "mean_squared_error",
        "accuracy_score",
        "classification_report",
    }
)

#: Named in `ML/Test Prep/01_CHEATSHEET.md` or `02_MCQ_ANSWERS.md`, never executed.
#: Allowed by default, rejected under `--strict`.
TAUGHT_CHEATSHEET: frozenset[str] = frozenset(
    {
        "cross_val_score",
        "GridSearchCV",
        "confusion_matrix",
        "precision_score",
        "recall_score",
        "f1_score",
        "mean_absolute_error",
        "GaussianNB",
        "MultinomialNB",
        "GradientBoostingClassifier",
        "AdaBoostClassifier",
    }
)

#: Libraries that would quietly do the project's thinking for it. Absent from the
#: curriculum, so absent from `src/`. Notebooks and docs may still discuss them.
BANNED_MODULES: frozenset[str] = frozenset(
    {
        "xgboost",
        "lightgbm",
        "catboost",
        "shap",
        "optuna",
        "mlflow",
        "hyperopt",
        "torch",
        "tensorflow",
        "keras",
        "statsmodels",
        "imblearn",
    }
)


class Finding:
    """One disallowed import, with enough location to fix it without searching."""

    def __init__(self, path: Path, lineno: int, name: str, reason: str) -> None:
        self.path = path
        self.lineno = lineno
        self.name = name
        self.reason = reason

    def __str__(self) -> str:
        try:
            where = self.path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            # A file outside the repository, which happens only under test.
            where = self.path.as_posix()
        return f"{where}:{self.lineno}: {self.name}  [{self.reason}]"


def _root_module(dotted: str) -> str:
    return dotted.split(".", 1)[0]


def inspect_file(path: Path, allowed: frozenset[str]) -> list[Finding]:
    """Every import in one file that falls outside the allowed set."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[Finding] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _root_module(module) in BANNED_MODULES:
                findings.append(Finding(path, node.lineno, module, "BANNED LIBRARY"))
                continue
            if not module.startswith("sklearn"):
                continue
            for alias in node.names:
                if alias.name not in allowed:
                    reason = _classify(alias.name, allowed)
                    findings.append(Finding(path, alias.lineno, alias.name, reason))

        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = _root_module(alias.name)
                if root in BANNED_MODULES:
                    findings.append(Finding(path, alias.lineno, alias.name, "BANNED LIBRARY"))
                elif root == "sklearn":
                    # `import sklearn` hides every later attribute access from this check.
                    findings.append(
                        Finding(path, alias.lineno, alias.name, "IMPORT THE NAME, NOT THE PACKAGE")
                    )

    return findings


def _classify(name: str, allowed: frozenset[str]) -> str:
    if name in TAUGHT_CHEATSHEET and name not in allowed:
        return "CHEATSHEET TIER, REJECTED BY --strict"
    return "NOT TAUGHT"


def run(strict: bool) -> list[Finding]:
    allowed = TAUGHT_NOTEBOOK if strict else TAUGHT_NOTEBOOK | TAUGHT_CHEATSHEET
    findings: list[Finding] = []
    for path in sorted(SRC.rglob("*.py")):
        findings.extend(inspect_file(path, allowed))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce the taught-set import policy.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="allow only names executed in the notebooks; reject the cheatsheet tier",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the allowed names and the banned libraries, then exit",
    )
    args = parser.parse_args(argv)

    if args.list:
        print("notebook tier:")
        for name in sorted(TAUGHT_NOTEBOOK):
            print(f"  {name}")
        print("\ncheatsheet tier (allowed unless --strict):")
        for name in sorted(TAUGHT_CHEATSHEET):
            print(f"  {name}")
        print("\nbanned libraries:")
        for name in sorted(BANNED_MODULES):
            print(f"  {name}")
        return 0

    if not SRC.is_dir():
        print(f"no source tree at {SRC}", file=sys.stderr)
        return 1

    findings = run(strict=args.strict)
    if findings:
        for finding in findings:
            print(finding)
        plural = "" if len(findings) == 1 else "s"
        print(f"\n{len(findings)} disallowed import{plural}.")
        return 1

    tier = "notebook tier" if args.strict else "notebook tier + cheatsheet tier"
    print(f"clean: every import in src/ is within the {tier}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
