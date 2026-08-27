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

## The margin model, and why there is no margin model

| model | mae | rmse | r2 | fit (s) |
|---|---|---|---|---|
| linear regression | 0.2927 | 0.4659 | −0.0001 | 0.1 |
| ridge | 0.2927 | 0.4659 | −0.0001 | 0.1 |
| baseline: mean margin | 0.2930 | 0.4659 | −0.0001 | 0.0 |
| lasso | 0.2930 | 0.4659 | −0.0001 | 0.1 |
| polynomial linear | 0.3020 | 0.4701 | −0.0184 | 2.8 |

Linear regression and ridge "beat" the baseline by **0.0003 MAE**. That is not a model, it
is rounding. Lasso ties it exactly — L1 drove every coefficient to zero and reinvented the
mean, which is the cleanest possible demonstration of the revision notes' line about L1
being feature selection. Degree-2 polynomial expansion, 300 features, is measurably *worse*
than doing nothing.

### Is that the model class, or the data?

Two explanations, opposite next steps. `ceiling.py` settles it by building a predictor that
**cheats**: for a given column it predicts each group's mean taken from the test set
itself. No honest model restricted to that column can beat it.

| columns | groups | rows per group | oracle r2 | meaningful |
|---|---:|---:|---:|---|
| Market | 2 | 12,184 | 0.0000 | yes |
| Shipping Mode | 4 | 6,092 | 0.0001 | yes |
| Order Item Discount Rate | 18 | 1,354 | 0.0008 | yes |
| Category Name | 45 | 542 | 0.0024 | yes |
| Order Country | 42 | 580 | 0.0025 | yes |
| Product Name | 73 | 334 | 0.0036 | yes |
| all thirteen combined | 23,707 | **1.03** | 0.9696 | **no — memorising rows** |

**It is the data.** A predictor allowed to cheat reaches R² 0.0036. Nothing honest can do
better, so no model of any class — linear, tree, boosted, or otherwise — will predict
`Order Item Profit Ratio` from at-order features in this dataset. It sits at about 0.12
with a within-category standard deviation of roughly 0.46: the between-category variation
is a rounding error against the noise.

The last row is why `rows per group` is printed beside every score. Combine enough columns
and every order lands in a group of its own, at which point the oracle scores 0.97 by
reading the answers. That is not a ceiling and the table says so rather than leaving a
reader to notice.

### A number I over-read, corrected

`docs/data_audit.md` and the prediction section above both cite a "0.1385 spread" in
`Category Name` as the place the margin model's signal lives. That figure is
max−min across 50 category means, several of them tiny. It is not signal. The largest
categories all sit within 0.008 of each other, and the oracle above puts the honest number
at 0.0024. The audit's claim was wrong and this supersedes it.

### What the product does instead

Expected profit stays in the application, because the operator needs it, but it is computed
rather than predicted:

```
expected profit  =  mean training margin (0.1196)  x  Order Item Total
```

`Order Item Total` is known exactly at order time. So the value at risk on an order is
known to within the noise of a quantity nothing can predict, and the decision engine ranks
on a number that is measured rather than modelled. The UI must present it as an estimate
with that stated, not as a model output.

## The bar was wrong, and a ranking metric shows it

Everything above measures the models with accuracy and F1, concludes that none of them
clears both baselines, and is correct about that. It is also asking the wrong question.

**A control tower does not answer "is this order late, yes or no". It works down a list.**
The product is a *ranking*, and neither accuracy nor F1 measures one — both collapse a
probability to a label at some threshold and throw the ordering away. Adding two
threshold-free ranking metrics changes the picture:

| model | accuracy | f1 | roc auc | avg precision | tier |
|---|---|---|---|---|---|
| baseline: majority class | 0.5511 | 0.7106 | – | – | course |
| baseline: shipping-mode rule | 0.6956 | 0.6635 | 0.7341 | 0.7528 | course |
| logistic regression | 0.6992 | 0.6873 | 0.7346 | 0.8015 | course |
| random forest | 0.6794 | 0.6873 | 0.7379 | 0.8074 | course |
| voting | 0.6992 | 0.6873 | 0.7471 | 0.8193 | course |
| adaboost | 0.7017 | 0.6840 | 0.7468 | 0.7827 | course |
| gradient boosting | 0.6969 | 0.6670 | 0.7485 | 0.8200 | course |
| **one-hot random forest** | 0.7008 | 0.6828 | **0.7518** | **0.8215** | declared |
| one-hot logistic | 0.6940 | 0.6662 | 0.7472 | 0.8187 | declared |
| hist gradient boosting | 0.6802 | 0.6798 | 0.7360 | 0.8127 | declared |
| calibrated hist gradient boosting | 0.6909 | 0.6672 | 0.7392 | 0.8130 | declared |
| naive bayes | 0.6837 | 0.6559 | 0.7354 | 0.8020 | course |
| decision tree | 0.5972 | 0.6379 | 0.5919 | 0.6033 | course |
| k nearest neighbours | 0.5864 | 0.6069 | 0.6322 | 0.6860 | course |
| support vector machine | 0.6355 | 0.5698 | – | – | course |

On **average precision** — the ranking measure that follows the positive class, which is
the one that costs money when missed — the models beat the rule baseline by **0.069**.
0.8215 against 0.7528. That is a real, useful margin, and accuracy and F1 hid all of it:
on those two the same models looked interchangeable with a four-line lookup.

The earlier conclusion, that nothing clears the bar, stands as written for the bar it was
measured against. The correction is that the bar was measuring the wrong thing.

## What the added tools bought, and what they did not

Each name outside the course material is declared in `scripts/check_taught.py` with the
measurement that justified it. `python scripts/check_taught.py --report` prints the
breakdown; the course material still supplies 24 of the 29 scikit-learn names in `src/`.

**One-hot encoding earned its place twice.** It gives the best ranking in the table, and it
repairs the calibration defect that `LabelEncoder` caused:

| band | orders | mean predicted | observed rate | gap |
|---|---:|---:|---:|---:|
| (0.3, 0.4] | 3,523 | 0.3861 | 0.3244 | +0.062 |
| (0.4, 0.5] | 11,286 | 0.4387 | 0.3932 | +0.045 |
| (0.5, 0.6] | 945 | 0.5257 | 0.5672 | −0.042 |
| (0.6, 0.7] | 1,292 | 0.6781 | 0.6772 | +0.001 |
| (0.7, 0.8] | 4,284 | 0.7401 | 0.8109 | −0.071 |
| (0.8, 0.9] | 3,039 | 0.8538 | 0.9753 | −0.122 |

The observed rate now rises monotonically — 0.32, 0.39, 0.57, 0.68, 0.81, 0.98 — and the
worst gap falls from **0.334 to 0.122**. Under integer codes the ordering was *inverted*
between 0.6 and 0.9. Since ranking is the product, that was the most serious defect in the
project and it is now gone.

**Boosting bought nothing**, which is the useful part. `HistGradientBoostingClassifier`,
the strongest learner available, ranks *below* the one-hot random forest (0.7360 against
0.7518). Isotonic recalibration on top of it moves ROC-AUC by 0.003. That is the evidence
the oracle ceiling was honest: there is no model waiting to do dramatically better, so
XGBoost and LightGBM stay out of the repository rather than being tried and quietly
forgotten.

## Where this leaves the project

**The delivery-risk problem is mostly solved by one `if` statement, and the models add a
real but modest amount on top of it — visible only when you measure ranking.**

That is the result, not a disappointment. It was predictable from the audit: `Shipping
Mode` spans 57 points of late rate and everything else spans under three. The value of the
project is that it says so with numbers, and that it says so instead of shipping a 0.98
that is a leak.

What ChainSight ships, then, is the one-hot random forest for the ranking it provides, the
measured mean margin in place of a margin model that cannot exist, and the decision layer
that turns a probability and a known order value into one ordered list of actions.
