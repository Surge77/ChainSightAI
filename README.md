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
| SHAP | Global importances, plus **local counterfactual deltas** — re-predict with one field changed and report the difference. "Switch to First Class: −31pp" is a more useful sentence for an operator than a SHAP bar |
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

Early. This README describes the destination; the table below is where the code actually
is. Every phase is a branch, a pull request and a tag.

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
| 10 — decision engine | next |
| 11 — persistence and CLI | pending |
| 12–14 — FastAPI service, operator pages, control tower | pending |
| 15 — model card, ADRs, release | pending |

## Getting started

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate elsewhere
pip install -e ".[web,dev]"

python scripts/check_taught.py  # the curriculum gate
pytest -q
```

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
| `docs/decision_engine.md` | The cost model, and every assumption in it | phase 9 |
| `docs/model_card.md` | Intended use, known weaknesses, what this must not be used for | phase 15 |
| `docs/architecture.md` | How the pieces fit | phase 15 |
| `docs/adr/` | Why the load-bearing decisions were made | phase 15 |

Already written: [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md),
[CHANGELOG.md](CHANGELOG.md), [TODO.md](TODO.md).

## Licence

MIT — see [LICENSE](LICENSE). The dataset is not redistributed here and keeps its own
terms; the data card lands with phase 15.
