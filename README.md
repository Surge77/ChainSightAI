# ChainSight — a predictive supply chain control tower

[![CI](https://github.com/Surge77/ChainSightAI/actions/workflows/ci.yml/badge.svg)](https://github.com/Surge77/ChainSightAI/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/licence-MIT-green)](LICENSE)
[![Checked with pyright](https://img.shields.io/badge/types-pyright-blue)](https://github.com/microsoft/pyright)

**For an order that has not shipped yet, ChainSight answers two questions and turns them
into one decision.**

1. What is the probability this order arrives late?
2. What margin should we expect on it?

Then a cost-sensitive decision engine combines them, because those two numbers are not a
decision. An order at 90% risk carrying ₹200 of margin and an order at 85% risk carrying
₹50,000 are not the same problem, and a system that flags both as `HIGH` has not helped
anybody.

---

## The constraint that shapes this repository

The modelling starts from one curriculum -- the scikit-learn covered in the notebooks and
revision notes this project was built alongside -- and anything reached for beyond it has
to carry the measurement that justified it.

That is enforced, not promised. `scripts/check_taught.py` parses every module under `src/`
and fails the build on an import that is neither taught nor declared with a reason:

```console
$ python scripts/check_taught.py
clean: 24 scikit-learn names from the course material, 5 declared with a reason.

$ python scripts/check_taught.py --report
notebook     18 names  62.1%
cheatsheet    6 names  20.7%
declared      5 names  17.2%
              OneHotEncoder  - LabelEncoder gives Category Name an arbitrary code 0-49 that
                               linear models read as a quantity. Measured: one-hot cuts the
                               worst calibration gap from 0.334 to 0.074.
```

XGBoost, LightGBM, SHAP, Optuna and MLflow stay out entirely -- not on principle, but
because the measurements below say they would not help. An untried import is worth less
than a measured refusal.

The consequences are real and are documented rather than hidden:

| Missing from the curriculum | What this project does instead |
|---|---|
| `roc_auc_score` (later declared, with a measurement) | Started with precision / recall / F1 at a stated threshold and a decile reliability table. Those turned out to hide the models' real advantage, so ranking metrics were declared and added — see [`docs/results.md`](docs/results.md) |
| `OneHotEncoder` (later declared, with a measurement) | Started with `LabelEncoder` integer codes. They inverted the probability ordering between 0.6 and 0.9, so one-hot was declared and added; the worst calibration gap fell from 0.334 to 0.122 |
| tree and ensemble regressors | The margin model is `LinearRegression` / `Ridge` / `Lasso` / `PolynomialFeatures`+linear only |
| SHAP | Nothing, yet — and this row is the one place the README described code that does not exist. Local counterfactual deltas (re-predict with one field changed, report the difference) are designed and unbuilt; they are in [`TODO.md`](TODO.md), not in `src/` |
| XGBoost, LightGBM | Not used, and the reason is measured rather than asserted: `HistGradientBoostingClassifier`, the strongest learner tried, ranks *below* a one-hot random forest |
| Optuna | `GridSearchCV` over time-ordered folds |
| MLflow | A JSON model registry and a `model_versions` table |

## The part worth reading first

`Late_delivery_risk` in the DataCo dataset is **derived from the outcome it labels**. It is
true exactly when real shipping days exceed scheduled shipping days, and `Delivery Status`
spells the answer out in English. Published notebooks on this dataset report accuracy
around 0.98. That number is the leak, not the model.

ChainSight removes every column that does not exist at the moment an order is placed, and
trains the same model twice to show what that costs. Measured, not asserted:

| | accuracy |
|---|---|
| with the post-dispatch columns | **1.0000** |
| honest | 0.6956 |

Not 0.98 — a depth-5 tree needs one split on `Delivery Status` and it is done. Thirty
accuracy points is the price of asking the question at the moment you would actually need
the answer.

The audit found a second leak on the regression side that is usually missed, and it is the
more interesting one. `Order Item Profit Ratio` is exactly
`Order Profit Per Order / Order Item Total`, and the divisor is known at order time. Give a
linear model the profit column alone and it reaches R² 0.1938 — a mediocre-looking model
nobody would investigate. Give it the quotient too and it reaches **1.0000**. The leak
hides because `LinearRegression` cannot divide.

So ChainSight predicts the **margin ratio** and multiplies it by the order total, which is
already in hand.

Full column-by-column reasoning, with every equality measured on all 180,519 rows, is in
[`docs/data_audit.md`](docs/data_audit.md). The short version: 16 of 53 columns survive,
and one of them — `Shipping Mode` — carries a 57-point spread in late rate while `Market`
carries 0.9. A single `if` on shipping mode scores 0.6953 accuracy, so that, and not the
0.5483 majority class, is the number every model here is measured against.

## Status

**`v1.1.0`.** Every phase below is a branch and a tag, and every one landed behind a green CI
run on Python 3.11 and 3.12. 516 tests; `src/` at 100% line and branch coverage.

| Phase | State |
|---|---|
| 0 — scaffold, docs, CI, taught-set gate | done (`v0.1.0`) |
| 1 — data acquisition | done |
| 2 — column contract, data audit, committed sample | done |
| 3 — ingest | done |
| 4 — features and encoding | done |
| 5 — time-aware split and baselines | done (`v0.2.0`) |
| 6 — the leakage demonstration | done |
| 7 — the classification registry | done (`v0.3.0`) |
| 8 — the margin model, and the oracle ceiling | done |
| 9 — ranking metrics, one-hot, declared models | done |
| 10 — decision engine | done (`v0.4.0`) |
| 11 — persistence, registry and CLI | done (`v0.5.0`) |
| 12–14 — FastAPI service, operator pages, control tower | done (`v0.6.0`) |
| 15 — model card, data card, ADRs, release | done (`v1.0.0`) |
| after the release — CSRF, administrator surface, `init` fix | done (`v1.1.0`) |

## Getting started

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate elsewhere
pip install -e ".[web,dev]"

python scripts/check_taught.py  # the curriculum gate
pytest -q
```

## The command line

Every command runs on the committed 500-row slice with `--sample`, so the output below can
be reproduced without downloading the 92 MB source file.

```console
$ python -m chainsight describe --sample
500 rows x 18 columns (16 feature candidates)
orders from 2015-01-01 to 2018-01-30
late rate 0.5800
margin ratio: mean 0.1200, 16.2000% loss-making

$ python -m chainsight train --sample --promote
one-hot random forest: fitted on 347 orders, scored on 65
threshold       0.2966 (derived from the cost model, not assumed)
registered as version 1
promoted version 1; it is now serving

$ python -m chainsight predict order.json
HIGH  Worth intervening. 75% risk, and acting costs less than the exposure.

  late-delivery risk   0.7478  (flagged above 0.2966)
  order total          191.99
  value at risk        27.28
  net benefit of act   12.28
```

`predict --template` prints a blank order with every field an order needs, because
`features.single_order` refuses a field list that is not exactly right — a silently
defaulted feature is a prediction about a different order.

Two things the registry does that are worth naming. **Training never promotes**: a fresh
model is a candidate, and serving it because it is last in the list is the accident the
registry exists to prevent. And **promotion compares before it promotes** — a retrain that
scores below the model already serving is refused, on ranking rather than accuracy, and
`--force` is how you say you meant it.

## The application

```bash
export CHAINSIGHT_SESSION_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

python -m chainsight train --sample --promote          # something to serve
python -m chainsight_web init --email you@example.com  # prompts for a password
python -m chainsight_web serve                         # http://127.0.0.1:8000
```

There is no default session secret and the process will not start without one. A default in
a public repository is a forged-session vulnerability with the key published beside it.

An **operator** enters an order — the same sixteen at-order fields the model was trained on,
with the dropdowns built from the categories it was actually fitted on — and gets a report:
the risk, the expected profit, the exposure, and the net benefit that decides the priority.
An **administrator** additionally sees the control tower, the model registry and the cost
model, and can retrain and promote from the browser.

Four things about it are worth stating, because each is a decision rather than a default:

- **Promotion compares before it promotes**, through the same `registry.promote` the CLI
  uses. A retrain that scores below the model already serving is refused and the refusal is
  written to `training_runs` with its reason — that row is what answers "why is the serving
  model three weeks old".
- **Ownership is a `WHERE` clause**, not a check after the fetch, and a missing order and
  somebody else's order are the same 404.
- **The admin role is read from the database on every request.** Granting or revoking it
  takes effect immediately, because nothing about the role is cached in the cookie.
- **Retraining reads a file on the server.** Nothing entered through the UI reaches the
  training set, so an operator cannot poison it through the order form.

The charts are held to the same standard as the rest of the project. They plot *predicted*
risk on entered orders rather than an observed late rate, every mean carries its sample size,
a group under five orders is marked noisy, and the axis is pinned to [0, 1] — because the
observed regional spread on this dataset is about five points around a 0.5483 base rate, and
a cropped axis would turn that into a cliff.

## This is not a live system

ChainSight is a production-*shaped* application running on a historical benchmark dataset.
It does not observe real shipments, it has no live carrier feed, and it predicts nothing
that is actually in transit. The application simulates the workflow a real control tower
would have. That distinction is stated here so it never has to be walked back.

It also binds to localhost, has no TLS and no rate limiting. See [SECURITY.md](SECURITY.md)
for what is defended and what deliberately is not.

## Documentation

Written as the phase that earns it lands, so nothing here describes code that does not
exist.

| | | |
|---|---|---|
| [`docs/data_audit.md`](docs/data_audit.md) | All 53 columns: available at order time, or not, and why | **done** |
| [`docs/leakage.md`](docs/leakage.md) | The two leaks, and what removing them costs | **done** |
| [`docs/results.md`](docs/results.md) | Baselines first, then every model against them | **done** |
| [`docs/decision_engine.md`](docs/decision_engine.md) | The cost model, and every assumption in it | **done** |
| [`docs/model_card.md`](docs/model_card.md) | Intended use, known weaknesses, what this must not be used for | **done** |
| [`docs/data_card.md`](docs/data_card.md) | Provenance, licence, personal data, and four properties to know first | **done** |
| [`docs/architecture.md`](docs/architecture.md) | How the pieces fit, and the four boundaries that are load-bearing | **done** |
| [`docs/glossary.md`](docs/glossary.md) | Every term this project uses in a specific way | **done** |
| [`docs/adr/`](docs/adr/) | Why the load-bearing decisions were made, one file each | **done** |

Already written: [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md),
[CHANGELOG.md](CHANGELOG.md), [TODO.md](TODO.md).

## Licence

MIT — see [LICENSE](LICENSE). The dataset is not redistributed here and keeps its own terms
(CC0-1.0); its provenance is in [`docs/data_card.md`](docs/data_card.md).
