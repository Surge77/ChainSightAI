"""Fail the build if `src/` reaches for machine learning this project never studied.

ChainSight is deliberately built from one curriculum: the notebooks under
`ML/Resource Files` and `ML/Personal Files`, and the revision notes under `ML/Test Prep`.
The point is not asceticism. A portfolio project whose headline number comes from a
library the author cannot explain is worth less than a smaller number the author can
derive. This script is the mechanism that keeps that promise honest, because good
intentions do not survive a late-night debugging session.

Three tiers are allowed, and the gate's job is to keep them **labelled** rather than to
keep the third one empty:

* ``TAUGHT_NOTEBOOK`` -- names actually executed in a notebook's code cells.
* ``TAUGHT_CHEATSHEET`` -- names written out in ``01_CHEATSHEET.md`` or the MCQ answers but
  never run. A small stretch, so ``--strict`` rejects them.
* ``DECLARED`` -- names from outside the curriculum, each carrying a written reason and a
  measurement that justified reaching for it. Adding one means editing this file, which
  puts the justification in the diff where a reviewer sees it.

Anything not in one of the three fails, and so does importing a banned library at all. The
curriculum is still the backbone of the project -- ``--report`` prints how much of ``src/``
rests on each tier, so "we used the taught material" stays a checkable claim rather than a
sentence in a README.

    python scripts/check_taught.py            # all three tiers
    python scripts/check_taught.py --strict   # notebook tier only
    python scripts/check_taught.py --report   # how much of src/ sits in each tier
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

#: Outside the curriculum, used anyway, each with the measurement that justified it.
#: A name may not be added here without a reason, and a test enforces that.
DECLARED: dict[str, str] = {
    "OneHotEncoder": (
        "LabelEncoder gives Category Name an arbitrary code 0-49 that linear models read as "
        "a quantity. Measured: one-hot cuts the worst calibration gap from 0.334 to 0.074."
    ),
    "ColumnTransformer": "Required to one-hot the categorical block and pass the rest through.",
    "roc_auc_score": (
        "Ranking orders by risk is the product, and accuracy and F1 both hid that the models "
        "beat the rule baseline at it: 0.7518 against 0.7341."
    ),
    "average_precision_score": (
        "The positive class is 55% of rows and the cost of a miss is asymmetric, so the "
        "precision-recall summary is the more honest of the two ranking numbers."
    ),
    "CalibratedClassifierCV": (
        "The probability ordering was inverted between 0.6 and 0.9, and the decision engine "
        "multiplies that probability by money."
    ),
    "HistGradientBoostingClassifier": (
        "Tested as the strongest available learner, to check the oracle ceiling was real. "
        "It scores below one-hot random forest, which is the evidence the ceiling is honest."
    ),
    "RandomForestRegressor": (
        "Tested against the margin ceiling for the same reason. Kept only if it earns a row."
    ),
}

#: Libraries that would quietly do the project's thinking for it. Kept out so that the
#: comparison stays between things the author can explain. Notebooks and docs may discuss them.
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
    if name in DECLARED and name not in allowed:
        return "DECLARED, REJECTED BY --strict"
    return "NOT TAUGHT"


def tier_of(name: str) -> str:
    if name in TAUGHT_NOTEBOOK:
        return "notebook"
    if name in TAUGHT_CHEATSHEET:
        return "cheatsheet"
    if name in DECLARED:
        return "declared"
    return "unknown"


def run(strict: bool) -> list[Finding]:
    allowed = (
        TAUGHT_NOTEBOOK if strict else TAUGHT_NOTEBOOK | TAUGHT_CHEATSHEET | frozenset(DECLARED)
    )
    findings: list[Finding] = []
    for path in sorted(SRC.rglob("*.py")):
        findings.extend(inspect_file(path, allowed))
    return findings


def census() -> dict[str, list[str]]:
    """Every sklearn name `src/` actually imports, grouped by which tier it belongs to."""
    found: dict[str, set[str]] = {"notebook": set(), "cheatsheet": set(), "declared": set()}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sklearn"):
                for alias in node.names:
                    tier = tier_of(alias.name)
                    if tier in found:
                        found[tier].add(alias.name)
    return {tier: sorted(names) for tier, names in found.items()}


def report() -> int:
    """Print how much of `src/` rests on each tier, so the claim stays checkable."""
    counted = census()
    total = sum(len(names) for names in counted.values())
    if not total:
        print("src/ imports nothing from scikit-learn.")
        return 0

    for tier, names in counted.items():
        share = len(names) / total
        print(f"{tier:11s} {len(names):3d} names  {share:5.1%}")
        for name in names:
            suffix = f"  - {DECLARED[name]}" if tier == "declared" else ""
            print(f"              {name}{suffix}")
    taught = len(counted["notebook"]) + len(counted["cheatsheet"])
    print()
    print(f"{taught} of {total} scikit-learn names in src/ come from the course material.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce the taught-set import policy.")
    parser.add_argument(
        "--report",
        action="store_true",
        help="print how much of src/ sits in each tier, then exit",
    )
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

    if args.report:
        return report()

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

    if args.strict:
        print("clean: every import in src/ is within the notebook tier.")
        return 0

    counted = census()
    taught = len(counted["notebook"]) + len(counted["cheatsheet"])
    declared = len(counted["declared"])
    print(
        f"clean: {taught} scikit-learn names from the course material, "
        f"{declared} declared with a reason. Run --report for the breakdown."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
