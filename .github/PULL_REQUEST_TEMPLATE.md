## What this changes

<!-- One paragraph. What a reader of the history needs, not a restatement of the diff. -->

## Why

<!-- The problem. If this is a phase from the plan, say which one. -->

## The gate

- [ ] `ruff check . && ruff format --check .`
- [ ] `pyright`
- [ ] `pytest -q --cov=src --cov-report=term-missing`
- [ ] `python scripts/check_taught.py`

## If this touches modelling

- [ ] No column that is unavailable at order time entered a feature set
- [ ] Any historical aggregate was fitted on the training slice only
- [ ] `docs/results.md` moved in this PR if a number moved
- [ ] `scripts/check_taught.py` was not edited — or, if it was, the commit message names
      the notebook or revision page the new name comes from

## If this touches the web app

- [ ] Input is validated at the route boundary before it reaches the pipeline or the ORM
- [ ] Ownership is filtered in the query, not asserted after the fetch
- [ ] No new route reads a role, an id, or a permission from a form field or a cookie value

## Notes for the reviewer

<!-- What you are unsure about. What you deliberately left out and why. -->
