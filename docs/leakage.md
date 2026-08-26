# What the forbidden columns are worth

Published notebooks on the DataCo table report accuracy around 0.98 predicting
`Late_delivery_risk`. This document trains the same model twice — once with the
post-dispatch columns, once without — and prints both numbers.

Reproduce all of it with:

```bash
python -m chainsight leakage        # or: python -c "from chainsight import leakage; print(leakage.report('data/raw/DataCoSupplyChainDataset.csv'))"
```

Every run below uses `DecisionTreeClassifier(max_depth=5, random_state=42)` or
`LinearRegression` — the cheatsheet's own estimators. The depth cap matters: it means the
honest run cannot be waved away as an under-trained straw man set up to lose.

Full table, 180,519 orders. Chronological split, scored on the 24,369 orders from July 2017
onward.

---

## 1. Will this order be delivered late?

| model | accuracy | precision | recall | f1 |
|---|---|---|---|---|
| with post-dispatch columns | **1.0000** | 1.0000 | 1.0000 | 1.0000 |
| honest | 0.6956 | 0.8474 | 0.5459 | 0.6641 |

Not 0.98. **1.0000.** A depth-5 tree needs one split on `Delivery Status` and it is
finished — `Delivery Status == "Late delivery"` is exactly the 98,977 positive rows and
nothing else appears there.

The three columns removed are `Days for shipping (real)`, `Delivery Status` and
`Order Status`. None of them exists at the moment an operator would want this prediction.

So the honest cost of asking the question at the right time is **30 accuracy points**, and
0.6956 is what the problem is actually worth. That figure also happens to equal the
shipping-mode rule baseline in [`results.md`](results.md) to four decimals — the tree found
the same rule and nothing else, which is its own finding.

## 2. What margin should we expect on this order?

The delivery leak is well known. This one is usually missed, and it is worse, because it
produces a number that reads as success rather than as an alarm.

| model | mae | rmse | r2 |
|---|---|---|---|
| with the profit column | 0.1595 | 0.4183 | 0.1938 |
| with the profit column and one division | **0.0013** | 0.0021 | **1.0000** |
| honest | 0.2927 | 0.4659 | −0.0001 |

The middle row is the argument.

```
Order Item Profit Ratio  ==  Order Profit Per Order / Order Item Total
```

`Order Item Total` is a column we legitimately keep — it is known when the order is placed.
So a feature set containing `Order Profit Per Order` contains the target divided by a
number already in hand. Supply the quotient and R² is 1.0000; MAE is 0.0013 rather than 0
only because the publisher rounds the ratio to two decimals.

**And this is why the leak survives review.** `LinearRegression` cannot divide. Given the
profit column alone it reaches R² 0.1938 — a number that looks like a mediocre but working
model, not like a mistake. Nobody investigates a mediocre model. A tree, or a modeller who
adds one ratio feature during "feature engineering", finds the rest of it immediately.

`Benefit per order` is byte-identical to `Order Profit Per Order`, so dropping one and
keeping the other achieves nothing.

## 3. Does the shuffled split flatter the model?

| model | accuracy | precision | recall | f1 |
|---|---|---|---|---|
| shuffled split | 0.6923 | 0.8428 | 0.5393 | 0.6578 |
| chronological | 0.6956 | 0.8474 | 0.5459 | 0.6641 |

**No — and on this table it does not even help.** The shuffled split scores three
thousandths *worse*.

This comparison is here because the expected answer was the opposite one. The reason is in
[`results.md`](results.md): the late rate is 0.5497, 0.5405 and 0.5511 across the three
slices, and stable within each shipping mode across all four years. There is essentially
nothing for a shuffle to smuggle across the boundary.

The chronological split is still the one reported everywhere in this project — not because
it produces a worse number, but because it is the one that matches the question being
asked. A result that happens to be convenient is not a reason to stop being correct, and
the next dataset will not be this well behaved.

---

## What this means for the rest of the project

1. **0.6956 accuracy is the honest ceiling**, and it comes almost entirely from
   `Shipping Mode`. Any model here reporting materially more should be checked for a leak
   before it is believed.
2. **The margin problem is nearly all noise once the leak is gone.** R² −0.0001 says the
   honest linear model is indistinguishable from predicting the mean. Phase 8 has to
   improve on that or say plainly that it could not.
3. **The two guards that make this repeatable** are the column contract, which decides what
   `ingest` lets through, and `test_the_honest_feature_matrix_contains_no_leak_column`,
   which asserts the boundary rather than trusting it. A leak escaping into the honest run
   would *improve* the honest number, and an improved number is not something anybody
   investigates.
