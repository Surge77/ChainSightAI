# Architecture

How the pieces fit, and the four boundaries that are load-bearing rather than tidy.

---

## The shape of it

```
                      data/raw/DataCoSupplyChainDataset.csv   (gitignored, 53 columns)
                                        │
                          ┌─────────────▼─────────────┐
                          │  chainsight.ingest        │  the single door
                          │  contract + columns +     │  53 → 18 columns
                          │  schema                   │  drops leaks, PII, ids, dupes
                          └─────────────┬─────────────┘
                                        │
                          ┌─────────────▼─────────────┐
                          │  chainsight.split         │  train 2015-16 │ val 17H1 │ test 17H2+
                          └─────────────┬─────────────┘
                                        │
                          ┌─────────────▼─────────────┐
                          │  chainsight.features      │  one FeatureSpace, fitted on train
                          │  + encoding               │  codes | one-hot
                          └─────────────┬─────────────┘
                                        │
             ┌──────────────────────────┼──────────────────────────┐
             │                          │                          │
   ┌─────────▼────────┐      ┌──────────▼─────────┐     ┌──────────▼─────────┐
   │ models/regressors│      │ chainsight.training│     │ leakage / ceiling  │
   │ tuning / compare │      │ fits the one that  │     │ the evidence, not  │
   │ the comparison   │      │ gets served        │     │ the product        │
   └─────────┬────────┘      └──────────┬─────────┘     └────────────────────┘
             │                          │
       docs/results.md      ┌───────────▼───────────┐
                            │ chainsight.persistence│  Artefact = space + estimator
                            │ + registry            │  + manifest (hashes, versions)
                            └───────────┬───────────┘
                                        │  artifacts/*.joblib, registry.json
                       ┌────────────────┴────────────────┐
                       │                                 │
             ┌─────────▼────────┐              ┌─────────▼─────────┐
             │ chainsight.cli   │              │ chainsight_web    │
             │ describe leakage │              │ FastAPI + SQLite  │
             │ compare train    │              │ operator + admin  │
             │ registry predict │              │ pages             │
             └──────────────────┘              └─────────┬─────────┘
                                                         │
                                               ┌─────────▼─────────┐
                                               │ chainsight.       │
                                               │ decision          │
                                               │ probability + £   │
                                               │ → one ranked act  │
                                               └───────────────────┘
```

## The four boundaries that matter

### 1. `ingest` is the only door into the data

Nothing downstream reads a CSV. Everything receives a frame that has already lost the leaks,
the personal data, the identifiers, the duplicates and the empty columns, so no later module
has to remember to avoid them.

This is why a column cannot become a feature by being mentioned in a feature builder. It
becomes a feature by being listed in `columns.py` with `Disposition.USE` and a written
reason, which also puts it in `docs/data_audit.md`, which a test holds in step.

**What it buys:** a whole category of bug — "somebody used `Delivery Status` by accident" —
cannot happen, rather than being caught in review.

### 2. `FeatureSpace` is fitted once and travels with the estimator

There is one feature builder, used by training and by serving. Two implementations would be
two implementations and would disagree within a month, and the disagreement would not raise:
scikit-learn indexes features positionally once fitted, so a frame with the right columns in
the wrong order predicts confidently and wrongly.

The fitted space is therefore stored *inside* the artefact alongside the estimator, and the
manifest carries a hash of its column order. `persistence.load` checks the hash before
handing the artefact back.

**What it buys:** the failure that produces a plausible wrong number becomes a hard error.

### 3. The model, the cost model and the engine are three separate things

`chainsight.decision` knows nothing about scikit-learn. The classifier knows nothing about
money. The cost model is a dataclass an administrator edits.

**What it buys:** the arithmetic that turns a probability into a priority is tested without
fitting anything, and a change to what a late delivery costs is a configuration change rather
than a code change. It also keeps a fact visible that a merged design would bury — every cost
is an assumption, and none of it is learned.

### 4. The registry is the authority on what is serving

`artifacts/registry.json` is what `chainsight train` writes and what the promotion guard runs
against. The database's `model_versions` table is a **read model** refreshed from it, never
written to independently.

**What it buys:** one answer to "which model is live", and one implementation of
compare-then-promote that both the CLI and the admin route call.

## Package layout

### `chainsight` — the modelling core, no web server anywhere in it

| module | what it is |
|---|---|
| `contract`, `columns`, `schema` | the column contract: when a value exists, what we do about it, why |
| `ingest` | the single door; 53 → 18 columns, dates parsed, rates rounded |
| `encoding` | `CategoryCodes` (the course's `LabelEncoder`, with an `UNSEEN` fallback) and `OneHotColumns` |
| `features` | `FeatureSpace`: 23 columns, fitted on train, used by training and serving alike |
| `split` | chronological by default; a labelled shuffled split kept only for comparison |
| `baselines` | majority class, per-shipping-mode rate, mean margin |
| `evaluate` | accuracy / precision / recall / F1, ranking metrics, threshold sweep, reliability |
| `models`, `regressors`, `tuning` | the candidates and `GridSearchCV` over expanding time-ordered folds |
| `compare` | one function that runs the whole comparison, baselines included as rows |
| `leakage`, `ceiling` | the evidence: train it twice; let a predictor cheat and see the ceiling |
| `decision` | cost model, derived threshold, priority bands |
| `persistence` | artefacts, manifests, and a loader that refuses a path |
| `registry` | the JSON registry and the compare-then-promote guard |
| `training` | fits the one model that gets served |
| `cli` | `python -m chainsight` |

### `chainsight_web` — the application

| module | what it is |
|---|---|
| `config` | settings from the environment; refuses to start without a session secret |
| `database`, `tables` | engine, session factory, and six tables |
| `security` | bcrypt and signed cookies, with no web framework near either |
| `schemas` | Pydantic models; every posted body stops here first |
| `dependencies` | who is asking, what they may see, where the session comes from |
| `service` | the one place a model is loaded and a prediction is written |
| `analytics` | the control tower's numbers, each with its sample size |
| `routes_auth`, `routes_orders`, `routes_admin` | the three route groups |
| `templating`, `templates/`, `static/` | one `render`, one layout, one stylesheet |
| `app`, `__main__` | the factory, and `init` / `serve` |

Nothing under `chainsight/` imports FastAPI. The web stack is an optional extra, so somebody
who wants the models does not have to install a web server to get them.

## Request path, end to end

An operator posts an order:

1. **`schemas.OrderInput`** validates it. A negative total is a field error here, not a 500
   from inside `decision.decide`.
2. **`routes_orders.create_order`** writes the `orders` row, owned by the caller.
3. **`service.predict_for`** asks `ModelService.live()` for the promoted artefact — loaded
   once and cached, keyed on the registry's promoted version, so a promotion elsewhere takes
   effect without a restart.
4. **`Order.as_fields()` → `features.single_order` → `FeatureSpace.transform`** builds the
   one-row matrix through the same code training used.
5. **`decision.decide`** combines the probability with the known order total and the
   administrator's cost model.
6. Every field of the resulting `Decision` is **written** to `predictions`, not recomputed on
   read — because the cost model is editable, and a report should say what the system said.

## What is deliberately not here

- **No ORM-level migration tool, and no Postgres by default.** SQLite is sufficient for a
  single-node deployment and stays the default. The schema uses nothing SQLite-only, so
  `CHAINSIGHT_DATABASE` takes a Postgres URL where the filesystem does not persist —
  [ADR 0014](adr/0014-postgres-when-the-filesystem-does-not-persist.md).
- **No migration tool.** One deployment, and a schema change means a new database file. That
  is stated rather than discovered.
- **No background jobs.** A retrain runs to completion inside the request, in FastAPI's
  threadpool. On the full table that is minutes, and the page says so.
- **No SPA.** Server-rendered HTML, one stylesheet, one CDN script for the charts.
- **No XGBoost, LightGBM, SHAP, Optuna or MLflow.** Each is excluded with a measurement
  rather than on principle; `docs/results.md` shows the strongest available learner ranking
  *below* the model that ships.

## The gates

Everything below runs in CI on Python 3.11 and 3.12, and all of it must be green:

```bash
ruff check . && ruff format --check .
pyright
pytest -q --cov=src --cov-report=term-missing   # src/ at 100% line and branch
python scripts/check_taught.py                  # the curriculum gate
python scripts/render_audit.py --check          # the audit still matches the contract
```
