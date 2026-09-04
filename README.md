# ChainSight

[![CI](https://github.com/Surge77/ChainSightAI/actions/workflows/ci.yml/badge.svg)](https://github.com/Surge77/ChainSightAI/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/licence-MIT-green)](LICENSE)

Predicts whether a customer order will be delivered late, before it ships, and works out
whether the order is worth acting on.

**Live demo: https://chainsight-wf9i.onrender.com** — register an account and enter an order.

The hosted demo trains on a 500-row sample committed to this repository, so its scores are
not the numbers quoted below. Those come from the full 180,519-row table.

## What it does

For an order that has not shipped, it answers two questions and turns them into one decision:

1. How likely is this order to arrive late?
2. What margin should we expect on it?

Risk alone is not a decision. An order at 90% risk carrying $200 of margin and an order at
85% risk carrying $50,000 are not the same problem, and flagging both as `HIGH` helps nobody.
So a cost-sensitive engine combines the two and ranks orders by what acting on them is worth.

## The finding

`Late_delivery_risk` in this dataset is derived from the outcome it labels. It is true exactly
when real shipping days exceed scheduled shipping days, and `Delivery Status` spells the answer
out in English. Published notebooks report accuracy around 0.98 on it. That number is a leak,
not a model: a depth-5 tree needs one split on `Delivery Status` and it is done.

ChainSight drops every column that does not exist at the moment an order is placed, then trains
the same model twice to show what honesty costs.

| trained on | accuracy |
|---|---|
| all columns, including post-dispatch | 1.0000 |
| the 16 fields known before dispatch | 0.6956 |

Thirty accuracy points is the price of asking the question when you would actually need the
answer.

There is a second leak on the regression side, and it is the more interesting one.
`Order Item Profit Ratio` is exactly `Order Profit Per Order / Order Item Total`, and the
divisor is known at order time. Give a linear model the profit column alone and it reaches
R² 0.1938, which looks like a mediocre model rather than an alarm. Give it the quotient too
and it reaches 1.0000. The leak hides because `LinearRegression` cannot divide.

So ChainSight predicts the margin ratio and multiplies by the order total, which is already
in hand.

## Results

Every model is measured against a rule, not against the majority class. A single `if` on
shipping mode scores 0.6953 accuracy, so that is the bar.

| | accuracy | average precision |
|---|---|---|
| majority class | 0.5483 | — |
| shipping-mode rule | 0.6953 | 0.7528 |
| serving model | 0.6956 | 0.8215 |

On accuracy the model beats the rule by half a point, which reads as nothing. On average
precision it beats it by 0.069. Accuracy and F1 hid the models' real advantage completely,
which is why the production model is selected on ranking.

Two negative results worth as much as the positive ones:

- **The margin ratio cannot be predicted by anything.** An oracle allowed to cheat reaches
  R² 0.0036. The product computes expected profit instead of modelling it.
- **The stronger learners lose.** `HistGradientBoostingClassifier` ranks below a one-hot
  random forest, so the forest serves.

Full workings, including two places where an earlier claim here turned out to be wrong and was
corrected next to the original, are in [`docs/results.md`](docs/results.md).

## The dataset

| | |
|---|---|
| Name | DataCo Smart Supply Chain for Big Data Analysis |
| Source | [Kaggle](https://www.kaggle.com/datasets/shashwatwork/dataco-smart-supply-chain-for-big-data-analysis) |
| Licence | CC0-1.0 |
| Shape | 180,519 rows × 53 columns |
| Period | 2015-01-01 to 2018-01-31 |
| Size | ~92 MB, latin-1 encoded |
| Late rate | 0.5483 |

It is not redistributed here. `scripts/fetch_data.py` downloads it and verifies the SHA-256,
the row count and the column count. `data/sample_orders.csv` is a 500-row slice for tests and
the demo.

Of the 53 columns, 16 survive. Each of the 35 that are dropped carries a one-line reason in
`src/chainsight/columns.py`, and a test keeps that file in step with
[`docs/data_audit.md`](docs/data_audit.md). Three properties to know before trusting any number
from this data:

- First Class shipping with any payment type other than TRANSFER is late on all 20,001 such
  rows, a rate of exactly 1.0000.
- Fitted before 2017 and applied after, `Product Name` is unseen on 19.56% of rows. The model
  has a shelf life of months.
- 7,754 cancelled shipments are labelled not-late because they never went. That is label noise,
  not on-time delivery.

## Run it

Everything here runs on the committed 500-row sample. No download needed.

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; source .venv/bin/activate elsewhere
pip install -e ".[web,dev]"

python -m chainsight leakage      # both leaks, trained twice each
python -m chainsight compare      # the fourteen-model comparison
python scripts/report_baselines.py
```

The web application:

```bash
export CHAINSIGHT_SESSION_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
python -m chainsight train --sample --promote
python -m chainsight_web init --email you@example.com
python -m chainsight_web serve                    # http://127.0.0.1:8000
```

It refuses to start without a session secret rather than inventing one. Data lives in SQLite by
default; point `CHAINSIGHT_DATABASE` at Postgres for a deployment whose filesystem is rebuilt on
restart. Container builds for Render and Hugging Face are in [`deploy/`](deploy/).

## One constraint worth mentioning

The modelling is restricted to the scikit-learn covered in the coursework this was built
alongside. Anything reached for beyond it has to carry the measurement that justified it, and
that is enforced rather than promised: `scripts/check_taught.py` parses every module under
`src/` and fails the build on an undeclared import.

XGBoost, LightGBM, Optuna and MLflow are not used. The reasons are measured, not asserted. An
untried import is worth less than a measured refusal.

## What this is not

It is not connected to any live system, and it should not be pointed at real orders. The
`First Class` finding above is on its own sufficient reason. The costs in the decision engine
are stated business judgements with no empirical basis in this dataset, and the docs keep saying
so. The demo has a public sign-up form, so do not put anything real into it.

## Where to read more

| | |
|---|---|
| [`docs/results.md`](docs/results.md) | every number above, and how it was measured |
| [`docs/leakage.md`](docs/leakage.md) | both leaks in full |
| [`docs/data_audit.md`](docs/data_audit.md) | all 53 columns, kept or dropped, with reasons |
| [`docs/model_card.md`](docs/model_card.md) | what the serving model may and may not be used for |
| [`docs/data_card.md`](docs/data_card.md) | provenance and the four properties of the data |
| [`docs/decision_engine.md`](docs/decision_engine.md) | the cost model, and why each cost is an assumption |
| [`docs/architecture.md`](docs/architecture.md) | how the pieces fit |
| [`docs/adr/`](docs/adr/) | fourteen decisions, with the arguments against each |
| [`SECURITY.md`](SECURITY.md) | what is defended against, and what deliberately is not |
| [`TODO.md`](TODO.md) | open work, kept honest |

`v1.2.0`. 634 tests, `src/` at 100% line and branch coverage, CI on Python 3.11 and 3.12, and
the web suite runs a second time against a real Postgres.

## Licence

MIT. See [LICENSE](LICENSE).
