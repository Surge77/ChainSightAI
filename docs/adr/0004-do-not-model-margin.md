# 0004 — Do not model margin; compute it

**Status:** accepted

## Context

The product needs an expected profit per order, so that the decision engine can rank on money
rather than on probability. The obvious move is to fit a regressor on
`Order Item Profit Ratio`.

Four taught regressors were fitted. The best beat the mean baseline by **0.0003 MAE**. Lasso
tied it exactly, having driven every coefficient to zero and reinvented the mean. Degree-2
polynomial expansion was measurably worse than doing nothing.

That leaves two explanations with opposite next steps: the model class is too weak, or there
is no signal.

## Decision

Settle it before choosing, with an oracle that **cheats** — for a given column it predicts
each group's mean taken from the test set itself. No honest model restricted to that column
can beat it.

| columns | groups | rows/group | oracle R² |
|---|---:|---:|---:|
| `Shipping Mode` | 4 | 6,092 | 0.0001 |
| `Category Name` | 45 | 542 | 0.0024 |
| `Product Name` | 73 | 334 | 0.0036 |
| all thirteen combined | 23,707 | **1.03** | 0.9696 — memorising rows |

**It is the data.** A predictor allowed to read the answers reaches R² 0.0036, so no model of
any class will predict this target from at-order features here.

So the application computes expected profit rather than predicting it:

```
expected profit  =  0.1196  ×  Order Item Total
```

0.1196 is the measured mean margin ratio on the training slice; `Order Item Total` is known
exactly at order time.

## Consequences

The product keeps the number the operator needs, and it is an estimate with a stated basis
rather than a model output dressed up as one. The UI says so.

The last row of that table is why rows-per-group is printed beside every oracle score.
Combine enough columns and every order lands in a group of its own, at which point the oracle
scores 0.97 by reading the answers — that is not a ceiling, and the tool says so rather than
leaving a reader to notice.

An earlier claim in this repository was wrong and is superseded here: `docs/data_audit.md`
cited a "0.1385 spread" in `Category Name` as where the margin signal lived. That figure is
max−min across 50 category means, several of them tiny. The largest categories sit within
0.008 of each other. The original is left in place with the correction beside it.
