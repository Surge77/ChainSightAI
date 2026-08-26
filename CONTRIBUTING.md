# Contributing

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows;  source .venv/bin/activate elsewhere
pip install -e ".[web,dev]"
```

Python 3.11+. Dependencies are pinned exactly in `pyproject.toml`; if you need to move a
pin, move it in a commit of its own so a regression can be bisected to it.

## The gate

Everything below must be green **before** a commit, not before a pull request:

```bash
ruff check . && ruff format --check .
pyright
pytest -q --cov=src --cov-report=term-missing
python scripts/check_taught.py
```

A change that formats, but fails `pyright`, is not finished. A change that type-checks but
drops coverage under 80% on the code it touched is not finished either.

### The taught-set gate

`scripts/check_taught.py` fails on any scikit-learn import in `src/` outside the
curriculum, and on any import of a banned library (XGBoost, LightGBM, SHAP, Optuna,
MLflow, and friends) anywhere in `src/`.

If you genuinely need a new name, add it to `TAUGHT_NOTEBOOK` or `TAUGHT_CHEATSHEET` in
that file **in the same commit as the code that uses it**, and say in the commit message
which notebook or which page of the revision notes it comes from. Forcing the
justification into the diff is the entire mechanism. Do not add anything to
`BANNED_MODULES`' complement to make a red build green.

Notebooks and documentation are exempt. Discussing XGBoost is fine; shipping it is not.

## Branches

Never commit to `main`.

```
feature/<short-description>
fix/<short-description>
docs/<short-description>
chore/<short-description>
```

One branch is one phase or one fix. Open a pull request, merge with `--no-ff` so the
phase boundary survives in the history, and tag when the version moves.

## Commits

Conventional commits, and the subject says what changed for a reader, not what you typed:

```
feat(leakage): train twice and print what the post-dispatch columns are worth
fix(features): fit the regional late-rate on the training slice only
docs(audit): the eleven columns that do not exist when an order is placed
chore(deps): pin scikit-learn to 1.9.0
test(split): a fold boundary that let three days of the future into training
```

One logical change per commit. Do not batch a refactor with a behaviour change — the
review cannot separate them afterwards, and neither can `git bisect`.

## Tests

- Test file mirrors the source path: `src/chainsight/features.py` → `tests/test_features.py`.
- One test per behaviour, named for the behaviour: `test_unseen_category_falls_back_to_the_training_prior`.
- Arrange, act, assert — with blank lines between them.
- No network in unit tests. No writes outside `tmp_path`. No test that depends on another
  test having run first.
- 80% line coverage on new code. 100% on anything in `leakage.py`, `split.py` or
  `decision.py`, because a silent bug in those three does not crash — it produces a
  confident wrong number, which is worse.

Do not test implementation details. `test_random_forest_uses_100_estimators` tells you
nothing; `test_ranks_a_high_value_late_risk_order_above_a_cheap_one` tells you the product
works.

## Style

- Ruff, line length 100. `X_train` / `Y_test` capitals are deliberate and configured.
- Type annotations on every public signature.
- No file over 300 lines. Split by responsibility before you get there.
- Comments explain **why**, never what. If a line needs a comment to say what it does,
  rename something instead.
- No `print()` in `src/`; the CLI layer does the printing.

## Documentation

If a change alters a number in `docs/results.md`, the number moves in the same commit. A
results table that describes a previous version of the model is worse than no table.

## Data

`data/raw/` is gitignored and stays that way. Never commit the DataCo CSV, and never commit
anything derived from it that still carries `Customer Password`, `Customer Email`, a
customer name, a street, or a zipcode — see [SECURITY.md](SECURITY.md).
