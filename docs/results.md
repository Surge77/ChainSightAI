# Results

Baselines first. Every model added later appears in the same tables, against the same
split, on the same held-out slice.

Regenerate everything below with:

```bash
python scripts/report_baselines.py
```

---

## The split

Chronological, on `order date (DateOrders)`. Train on 2015–2016, tune on the first half of
2017, and look at everything from July 2017 onward exactly once.

```
chronological split
  train      125,200 rows  2015-01-01 to 2016-12-31  late 0.5497
  validation  30,950 rows  2017-01-01 to 2017-06-30  late 0.5405
  test        24,369 rows  2017-07-01 to 2018-01-31  late 0.5511
```

The late rate barely moves across the three slices — 0.5497, 0.5405, 0.5511 — which says
there is no drift to confound the comparison. That is convenient, and it is also why the
shuffled-versus-chronological comparison in `docs/leakage.md` is worth running: on this
dataset the split choice turns out to cost very little, and demonstrating that is more
useful than asserting the opposite.

## Classification baselines

Held-out test slice, 24,369 orders.

| model | accuracy | precision | recall | f1 |
|---|---|---|---|---|
| majority class | 0.5511 | 0.5511 | 1.0000 | 0.7106 |
| shipping-mode rule | 0.6956 | 0.8489 | 0.5445 | 0.6635 |

**These two disagree about which is better, and that is the point.**

The majority-class baseline predicts "late" for every order. It is the least informative
model that can exist, and it scores an F1 of **0.7106** — higher than the rule baseline's
0.6635 — because predicting one class always buys recall of exactly 1.0 for free.

The shipping-mode rule predicts each mode's own training late rate, thresholded at a half.
Four lines of pandas. It scores **0.6956 accuracy** against the majority's 0.5511.

So there is no single number to beat. A model earns its place here by clearing
**0.6956 accuracy and 0.7106 F1 at the same time**, which is a materially harder target
than either alone, and a considerably more honest one. This is the revision notes'
"why accuracy lies" argument arriving from the other direction: F1 lies too, and it lies
in favour of the model that has learned nothing.

### Confusion matrix, shipping-mode rule

|  | predicted not late | predicted late |
|---|---:|---:|
| **actual not late** | 9,637 | 1,302 |
| **actual late** | 6,117 | 7,313 |

The rule is precise and timid: when it calls an order late it is right 85% of the time, but
it misses 6,117 of the 13,430 orders that actually were. For a control tower that is the
wrong balance — a missed late delivery costs more than an unnecessary check — which is
what the cost-sensitive threshold in `docs/decision_engine.md` exists to fix, and why the
threshold is derived rather than left at 0.5.

## Regression baseline

| model | mae | rmse | r2 |
|---|---|---|---|
| mean margin | 0.2930 | 0.4659 | -0.0001 |

Predicting the training mean margin ratio for every order. R² is −0.0001 because R² is
*defined* against exactly this predictor; the tiny negative is the gap between the training
mean and the test mean.

**MAE 0.2930 is the number to beat.** It is the one that can be said out loud: the margin
prediction is wrong by about 29 percentage points of the order value, on average, when you
do not model at all.

## What the audit predicts will happen

Recorded before the models exist, so the prediction can be wrong in public.

`docs/data_audit.md` measured a lookup table over five features and 6,509 groups reaching
0.7062 accuracy **in sample**. Out of sample, and against a two-metric bar, the honest
expectation is:

- The classifiers land near 0.70 accuracy and struggle to clear 0.7106 F1 without a
  threshold moved deliberately away from 0.5.
- Tree models beat the linear ones, because `LabelEncoder` gives every categorical a false
  ordering and only trees are indifferent to it.
- The engineered calendar and value features contribute nothing measurable to the delivery
  target, and `Lasso` drives them to zero.
- The margin model does better than its baseline than the delivery model does than its own,
  because `Category Name` carries a real 0.1385 spread.

Anything that clears these by a wide margin gets checked for a leak before it gets
believed.

---

## Model results

Nothing yet. Phase 6 adds the leakage demonstration; phase 7 adds the classifiers.
