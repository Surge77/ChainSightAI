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

## Classifiers

Ten taught estimators, `GridSearchCV` over four expanding time-ordered folds, scored on the
same held-out slice as the baselines. Regenerate with `python scripts/report_classifiers.py`.

| model | accuracy | precision | recall | f1 | fit (s) | trained on |
|---|---|---|---|---|---|---|
| baseline: majority class | 0.5511 | 0.5511 | 1.0000 | **0.7106** | 0.0 | 125,200 |
| logistic regression | 0.6992 | 0.8048 | 0.5997 | 0.6873 | 1.2 | 125,200 |
| voting | 0.6992 | 0.8048 | 0.5997 | 0.6873 | 5.3 | 125,200 |
| random forest | 0.6794 | 0.7431 | 0.6392 | 0.6873 | 12.7 | 125,200 |
| bagging logistic | 0.6978 | 0.8021 | 0.5996 | 0.6862 | 83.9 | 20,000 of 125,200 |
| adaboost | **0.7017** | 0.8217 | 0.5858 | 0.6840 | 39.9 | 125,200 |
| gradient boosting | 0.6969 | 0.8453 | 0.5508 | 0.6670 | 63.9 | 125,200 |
| baseline: shipping-mode rule | 0.6956 | 0.8489 | 0.5445 | 0.6635 | 0.0 | 125,200 |
| naive bayes | 0.6837 | 0.8188 | 0.5471 | 0.6559 | 0.4 | 125,200 |
| decision tree | 0.5972 | 0.6322 | 0.6438 | 0.6379 | 4.4 | 125,200 |
| k nearest neighbours | 0.5864 | 0.6372 | 0.5794 | 0.6069 | 2.9 | 20,000 of 125,200 |
| support vector machine | 0.6355 | 0.8150 | 0.4380 | 0.5698 | 1.4 | 5,000 of 125,200 |

**Clears both baselines at once: nothing.**

Three models beat the shipping-mode rule on accuracy — adaboost by 0.6 of a point, logistic
regression and voting by 0.4. Not one of the ten gets near the majority baseline's 0.7106
F1. The best is 0.6873.

The row caps are printed in the same row as the score because they change what the score
means. `SVC` saw 5,000 of 125,200 training rows; `KNeighborsClassifier` and the bagged
logistic saw 20,000. They are not comparable to the models that saw everything, and
presenting them without the cap would imply they were.

### Three predictions from the audit, checked

`docs/data_audit.md` and the section above were written before any of this ran.

| prediction | outcome |
|---|---|
| "The classifiers land near 0.70 accuracy" | **Right.** 0.6969–0.7017 for the top five. |
| "…and struggle to clear 0.7106 F1" | **Right, and worse than expected.** None came within 0.023. |
| "Tree models beat the linear ones, because `LabelEncoder` gives every categorical a false ordering and only trees are indifferent to it" | **Wrong.** `LogisticRegression` beats `RandomForest` on accuracy (0.6992 vs 0.6794) and ties it on F1. The tuned decision tree is fourth from bottom at 0.5972. |

The third one deserves the correction rather than a quiet edit. The reasoning was sound and
the premise was wrong: with the signal concentrated almost entirely in one four-level
column, there is barely any interaction structure for a tree to find that a linear model
cannot approximate — and the extra capacity mostly buys overfitting. The tuned tree is the
clearest case: `GridSearchCV` optimising F1 over the folds selected a deeper tree than the
depth-5 one used in `docs/leakage.md`, and it scored **0.6956 → 0.5972**. More capacity,
less accuracy.

## The threshold does not rescue it

Best model by F1, swept across operating points:

| threshold | accuracy | precision | recall | f1 | flagged |
|---|---|---|---|---|---|
| 0.20 | 0.5511 | 0.5511 | 1.0000 | 0.7106 | 24,369 |
| 0.30 | 0.5511 | 0.5511 | 1.0000 | 0.7106 | 24,369 |
| 0.35 | 0.5720 | 0.5654 | 0.9658 | **0.7132** | 22,943 |
| 0.40 | 0.6365 | 0.6340 | 0.8054 | 0.7095 | 17,061 |
| 0.45 | 0.6814 | 0.7467 | 0.6386 | 0.6884 | 11,487 |
| 0.50 | **0.6992** | 0.8048 | 0.5997 | 0.6873 | 10,007 |
| 0.60 | 0.6813 | 0.8240 | 0.5363 | 0.6497 | 8,740 |
| 0.70 | 0.5889 | 0.8327 | 0.3179 | 0.4602 | 5,128 |
| 0.80 | 0.5908 | 0.8701 | 0.3027 | 0.4491 | 4,672 |

At 0.35 the model clears the F1 bar (0.7132) and loses the accuracy bar (0.5720). At 0.50
it clears accuracy (0.6992) and loses F1 (0.6873). **There is no threshold that clears
both.** The two-metric bar is not merely unmet by these models; it is unmeetable by them.

Note what 0.35 costs operationally: 22,943 of 24,369 orders flagged. A control tower that
escalates 94% of its orders has not prioritised anything. This is why the threshold in
phase 9 is derived from the cost of intervening rather than picked off a metric.

## Calibration is poor, and not monotone

The decision engine multiplies this probability by money, so it has to be looked at.

| predicted band | orders | mean predicted | observed rate | gap |
|---|---:|---:|---:|---:|
| (0.3, 0.4] | 7,308 | 0.3677 | 0.3577 | +0.010 |
| (0.4, 0.5] | 7,054 | 0.4313 | 0.3916 | +0.040 |
| (0.5, 0.6] | 1,267 | 0.5891 | 0.6725 | −0.083 |
| (0.6, 0.7] | 3,612 | 0.6520 | 0.8117 | −0.160 |
| (0.7, 0.8] | 456 | 0.7849 | **0.4496** | **+0.335** |
| (0.8, 0.9] | 969 | 0.8322 | 0.5769 | +0.255 |
| (0.9, 1.0] | 3,703 | 0.9240 | 0.9468 | −0.023 |

The extremes are fine. The middle is not, and it is **not monotone**: orders the model
scores 0.78 are late 45% of the time, while orders it scores 0.65 are late 81% of the time.
The model's ordering is inverted across those two bands.

That is a serious defect for this application specifically. Ranking orders by predicted risk
is the product, and in the 0.6–0.9 range the ranking is wrong. Nothing here corrects it —
`CalibratedClassifierCV` is outside the curriculum — so it is recorded, it goes in the model
card, and `TODO.md` carries a hand-rolled isotonic fit as follow-up work.

## Where this leaves the project

The honest summary is that **on this dataset, with these features, the delivery-risk problem
is close to solved by one `if` statement, and ten taught estimators cannot do much better.**

That is not a disappointing result, it is the result. It was predictable from the audit —
`Shipping Mode` spans 57 points of late rate and everything else spans under 3 — and the
value of the project is that it says so with numbers instead of shipping a 0.98 that is a
leak. What remains genuinely useful is the second model, the margin ratio, and the decision
layer that turns two numbers into one ranked action.
