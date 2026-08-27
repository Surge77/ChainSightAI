# 0001 — Build from one curriculum, and enforce it

**Status:** accepted

## Context

A portfolio project can reach for any library. The failure mode is a headline number produced
by a tool the author cannot explain, which is worth less than a smaller number they can
derive.

## Decision

The modelling is built from one body of course material — the scikit-learn in the notebooks
and revision notes this project was written alongside. Anything reached for beyond it must
carry the measurement that justified it.

This is enforced rather than promised. `scripts/check_taught.py` parses the AST of every
module under `src/` and fails the build on a scikit-learn import that is neither taught nor
declared with a written reason. Adding a name means editing that file, which puts the
justification in the diff where a reviewer sees it.

Three tiers, and the gate's job is to keep them **labelled**, not to keep the third empty:

- `TAUGHT_NOTEBOOK` — executed in a notebook's code cells.
- `TAUGHT_CHEATSHEET` — written out in the revision notes but never run. `--strict` rejects these.
- `DECLARED` — from outside the curriculum, each with a reason and a measurement.

`xgboost`, `lightgbm`, `catboost`, `shap`, `optuna`, `mlflow`, `torch` and others are banned
outright.

## Consequences

**What it cost.** No SHAP, so explanations are global importances plus local counterfactual
deltas. No Optuna, so `GridSearchCV` over small grids. The margin model is linear only,
because no tree or ensemble regressor appears in the material.

**What it bought.** Five declared names, each with a number behind it. `OneHotEncoder`
because integer codes inverted the probability ordering and one-hot cut the worst calibration
gap from 0.334 to 0.122. `roc_auc_score` and `average_precision_score` because accuracy and
F1 hid the models' real advantage. `HistGradientBoostingClassifier` to test whether the
ceiling was real — and it ranks *below* the one-hot random forest, which is the evidence that
keeps XGBoost out on measurement rather than principle.

The AST parse rather than a grep is deliberate: a parenthesised multi-line import defeats a
regex, and every name inside the brackets would go unexamined.
