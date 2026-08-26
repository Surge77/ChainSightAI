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

Everything modelled here comes from one curriculum — the scikit-learn covered in the
notebooks and revision notes this project was built alongside. No XGBoost, no LightGBM, no
SHAP, no Optuna, no MLflow.

That is enforced, not promised. `scripts/check_taught.py` parses every module under `src/`
and fails the build on an import outside the taught set:

```console
$ python scripts/check_taught.py
clean: every import in src/ is within the notebook tier + cheatsheet tier.
```

The consequences are real and are documented rather than hidden:

| Missing from the curriculum | What this project does instead |
|---|---|
| `roc_auc_score` | Precision / recall / F1 at a stated threshold, a confusion matrix, a hand-computed threshold sweep, and a decile reliability table |
| `OneHotEncoder`, `ColumnTransformer` | `LabelEncoder` integer codes — correct for trees, false-ordinal for Logistic/KNN/SVC, and a stated reason tree models are expected to win here |
| tree and ensemble regressors | The margin model is `LinearRegression` / `Ridge` / `Lasso` / `PolynomialFeatures`+linear only |
| SHAP | Global importances, plus **local counterfactual deltas** — re-predict with one field changed and report the difference. "Switch to First Class: −31pp" is a more useful sentence for an operator than a SHAP bar |
| Optuna | `GridSearchCV` over time-ordered folds |
| MLflow | A JSON model registry and a `model_versions` table |

## The part worth reading first

`Late_delivery_risk` in the DataCo dataset is **derived from the outcome it labels**. It is
true exactly when real shipping days exceed scheduled shipping days, and `Delivery Status`
spells the answer out in English. Published notebooks on this dataset report accuracy
around 0.98. That number is the leak, not the model.

ChainSight removes every column that does not exist at the moment an order is placed, and
`python -m chainsight leakage` trains the same model twice — once with the post-dispatch
columns, once without — and prints both numbers side by side. The honest number is far
lower. Demonstrating exactly how much lower, and why, is the point of the project.

The same audit found a second leak on the regression side that is easy to miss:
`Order Profit Per Order` is `Order Item Total × Order Item Profit Ratio`, and
`Benefit per order` is a near-duplicate of the target. So ChainSight predicts the **margin
ratio** and multiplies it by the order total, which is already known when the order is
placed.

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
| 4–5 — features, split, baselines | next |
| 6 — the leakage demonstration | pending |
| 7–11 — models, decision engine, explanations, CLI | pending |
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
| `docs/leakage.md` | The two leaks, and what removing them costs | phase 6 |
| `docs/results.md` | Baselines first, then every model against them | phase 5 |
| `docs/decision_engine.md` | The cost model, and every assumption in it | phase 9 |
| `docs/model_card.md` | Intended use, known weaknesses, what this must not be used for | phase 15 |
| `docs/architecture.md` | How the pieces fit | phase 15 |
| `docs/adr/` | Why the load-bearing decisions were made | phase 15 |

Already written: [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md),
[CHANGELOG.md](CHANGELOG.md), [TODO.md](TODO.md).

## Licence

MIT — see [LICENSE](LICENSE). The dataset is not redistributed here and keeps its own
terms; the data card lands with phase 15.
