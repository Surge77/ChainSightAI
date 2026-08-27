# Glossary

Terms this project uses in a specific way, and the dataset's own vocabulary where it is
misleading. Where a term has a number attached, the number is measured on this dataset.

---

## The problem

**At-order** — knowable at the moment an order is placed, and therefore eligible to be a
feature. The opposite is **post-dispatch**. This distinction is the whole project: 16 of 53
columns are at-order.

**Late delivery** — the shipment took longer than it was scheduled to. This is the
classification target, `Late_delivery_risk`, and its base rate here is **0.5483** — an
unusually balanced problem.

**Leak** — a feature that only exists because the outcome already happened. On this dataset
they are worth thirty accuracy points: 1.0000 with them, 0.6956 without.

**Margin ratio** — `Order Item Profit Ratio`, margin as a share of the order total. Mean
0.1196 on the training slice. Nothing predicts it (see **oracle ceiling**).

## Measurement

**Baseline** — the number a model has to beat before it has earned its complexity. Three
here: **majority class** (predict "late" always; F1 0.7106 for free), the **shipping-mode
rule** (each mode's own training late rate, thresholded at a half; accuracy 0.6956, and four
lines of pandas), and **mean margin** (MAE 0.2930).

**The two-metric bar** — clearing 0.6956 accuracy *and* 0.7106 F1 at once. Neither alone is a
bar: the first is a `groupby`, the second is free. Nothing in this project clears both, at any
threshold. See ADR [0005](adr/0005-select-on-ranking.md) for why that turned out to be the
wrong question.

**Ranking metrics** — **ROC-AUC** and **average precision**. Threshold-free: they measure how
well a model *orders* orders rather than how often it labels one correctly. They disagree
usefully — ROC-AUC weights both classes equally, average precision follows the positive class,
which is the one that costs money when missed. This is what the production model is selected
on.

**Calibration** — whether a model claiming 0.80 is late about 80% of the time. Measured with a
**reliability table**: predicted probability binned into deciles against the observed rate.
The production model's worst gap is 0.122; the model it replaced had 0.334 and was
*non-monotone*, meaning its ordering was inverted between 0.6 and 0.9.

**Threshold sweep** — precision, recall, F1, accuracy and orders-flagged at each operating
point. What stands in for a ROC curve, and arguably the more useful object: a curve integrates
over thresholds nobody would ship, while this names the operating points and says what each
costs in orders flagged.

**Oracle ceiling** — a predictor allowed to **cheat**, predicting each group's mean taken from
the test set itself. No honest model restricted to those columns can beat it, so it separates
"this model class is too weak" from "there is no signal". On the margin target it reaches R²
**0.0036**, which is how this project knows no margin model can exist.

**Rows per group** — printed beside every oracle score, because a ceiling computed over groups
of one row is memorisation, not a ceiling.

**Expanding folds** — cross-validation windows where every scoring block sits strictly after
its own training block. `cv=5` shuffles, which reintroduces inside the training slice exactly
what the chronological split removed across it.

**Row cap** — a limit on training rows for an estimator too slow to see all 125,200 (`SVC` at
5,000; `KNeighborsClassifier` and the bagged logistic at 20,000). Printed in the same table row
as the score, because a cap changes what the score means.

## The decision layer

**Cost model** — what a late delivery is assumed to cost and what intervening is assumed to
cost. **Every field is an assumption with no empirical basis in this dataset**, which records
no intervention, no penalty and no customer response.

**Derived threshold** — `intervention / (intervention + late cost)`, which is **0.2966** here
rather than 0.5. A threshold of 0.5 silently assumes the two mistakes cost the same.

**Value at risk** — `probability × what a late delivery on this order costs`.

**Net benefit** — value at risk, less the cost of intervening. **This is the ranking.** It is
why a 499.95 order at 85% risk outranks a 20.00 order at 90%.

**Priority** — `CRITICAL`, `HIGH`, `MONITOR`, `LOW`, banded on net benefit rather than on
probability. Because every order here is under 500 and the fixed goodwill penalty does not
scale with order size, a *typical* order can never reach `CRITICAL` however risky it is.

**Expected profit** — `0.1196 × Order Item Total`. Computed, not predicted, and the UI says so.

## Serving

**Feature space** — a fitted `FeatureSpace`: the category encoder and the column order,
learned on the training slice and carried with the estimator. The column *order* matters:
scikit-learn indexes features positionally once fitted, so the right columns in the wrong
order predict confidently and wrongly.

**UNSEEN** — the code given to a category absent from training. Negative, so it cannot collide
with a real `LabelEncoder` code. It exists because `LabelEncoder.transform` raises on an
unseen label, and an operator will eventually enter a product that was not in the training
slice — 40% of them do, six months out.

**Artefact** — a joblib file holding the fitted feature space, the estimator and a manifest.
Treated as code, because `joblib.load` unpickles and unpickling executes.

**Manifest** — the feature-set hash, the dataset hash, four library versions and the scores.
A mismatch on load is a hard error, not a warning.

**Registry** — `artifacts/registry.json`: the list of trained models and which one is serving.
The authority; the database's `model_versions` table is a read model refreshed from it.

**Promotion** — making a registered version live. Compares against the incumbent on ranking
and refuses a regression, because retraining produces a model that is newer and newer is not
better.

## The dataset's own vocabulary

**`Type`** — the payment type (`CASH`, `DEBIT`, `PAYMENT`, `TRANSFER`), not a type of anything
else.

**`Market` vs `Order Region` vs `Order Country`** — three nested geographies of the
destination. `Market` has 5 values and spans **0.0085** of late rate; `Order Region` has 23
and spans 0.0916. Neither is worth much next to `Shipping Mode`'s 0.5725.

**`EE. UU.` vs `Estados Unidos`** — the same country, spelled two ways in two columns. Comparing
them as strings makes every domestic order look international, which is why
`features.derive` hard-codes the destination-side spelling.

**`Order Item Total`** — the line value after discount. The number the decision engine
multiplies. Known exactly at order time.

**`Sales` / `Sales per customer` / `Order Item Product Price`** — duplicates of quantities
already present under other names, dropped by the contract with the reason recorded.

**Cancelled order** — `Delivery Status == "Shipping canceled"`. All 7,754 are labelled
not-late because the shipment never went, which is label noise rather than an on-time
delivery. `ingest(..., exclude_cancelled=True)` removes them; it is off by default so the
frame matches the task as published.
