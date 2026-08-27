# Model card — ChainSight late-delivery risk

What this model is, what it is measured to do, and the four things that should stop somebody
deploying it into a real supply chain without further work.

Every number here is reproducible:

```bash
python -m chainsight compare            # the model table
python scripts/report_classifiers.py    # the threshold sweep and the reliability table
```

---

## At a glance

| | |
|---|---|
| **Task** | Binary classification: will this order be delivered later than scheduled? |
| **Serving model** | `one-hot random forest` — `RandomForestClassifier(n_estimators=200, max_depth=12)` over a one-hot feature space |
| **Chosen on** | Ranking (ROC-AUC 0.7518, average precision 0.8215), not accuracy |
| **Features** | 16 fields known at order time, from 53 source columns |
| **Trained on** | 125,200 orders placed in 2015–2016 |
| **Evaluated on** | 24,369 orders placed from July 2017 onward, looked at once |
| **Decision threshold** | 0.2966, derived from a cost model, not set at 0.5 |
| **Version** | `v1.0.0` |

## Intended use

ChainSight is built for one job: **ordering a queue of not-yet-shipped orders so an operator
works down it in the order that is worth working down.** It answers "which of these should I
look at first", and it answers it with a cost-weighted ranking rather than a probability.

The intended user is an operator or supply-chain analyst inside the organisation that placed
the orders. There is no external-facing use, and no customer ever sees a prediction about
their own order.

The prediction is made **before dispatch**, which is the only moment at which it could
change anything. Every column that only exists after the shipment happened is dropped at
ingest — `docs/leakage.md` measures what that costs, and the answer is thirty accuracy
points.

## Out of scope

Stated as flatly as possible, because a model card that only lists strengths is marketing.

- **Not for deciding anything about a person.** No customer-level decision, no credit or
  service tiering, no "this customer's orders are always late". The model does not see a
  customer identity: `Customer Fname`, `Customer Lname`, `Customer Email`, `Customer
  Street`, `Customer Zipcode` and `Customer Password` are dropped at load and never reach a
  feature, a log line, or an artefact.
- **Not a carrier evaluation.** `Shipping Mode` carries almost all of the signal, and the
  model would read "this mode is late" as "this carrier is bad" if anybody let it. It has no
  information that separates the two.
- **Not a promise to a customer.** These probabilities are not calibrated well enough to
  quote (see below), and this dataset is a historical benchmark rather than a live feed.
- **Not transferable to another dataset.** It is fitted to DataCo's own vocabulary — 164
  countries, 50 categories, its own four shipping modes — and to fingerprints of that
  dataset described below that are almost certainly artefacts of how it was generated.

## What it is measured against

A model here has to beat a one-line rule, not a coin. On the held-out slice:

| | accuracy | f1 | roc auc | avg precision |
|---|---|---|---|---|
| majority class | 0.5511 | 0.7106 | – | – |
| **shipping-mode rule** | 0.6956 | 0.6635 | 0.7341 | 0.7528 |
| **one-hot random forest** (serving) | 0.7008 | 0.6828 | **0.7518** | **0.8215** |

Read that honestly:

**On accuracy the model beats four lines of pandas by half a point.** 0.7008 against 0.6956.
Anybody quoting an accuracy figure for this model is quoting a number that a `groupby` on
`Shipping Mode` already achieves.

**On ranking it beats the rule by 0.069 average precision.** 0.8215 against 0.7528. That is
the real advantage, it is worth having for a queue, and accuracy and F1 both hid it
completely — which is why the production model is selected on ranking and why `TODO.md`
carries the finding that the original bar was measuring the wrong thing.

**No model tried clears both original baselines at once**, at any threshold. `docs/results.md`
sweeps the operating points and shows there is no threshold where accuracy beats 0.6956 and
F1 beats 0.7106 together.

## Known weaknesses

### 1. Calibration is poor in the middle of the range

The decision engine multiplies this probability by money, so this is the defect that matters
most. Under the serving model:

| band | orders | mean predicted | observed rate | gap |
|---|---:|---:|---:|---:|
| (0.3, 0.4] | 3,523 | 0.3861 | 0.3244 | +0.062 |
| (0.4, 0.5] | 11,286 | 0.4387 | 0.3932 | +0.045 |
| (0.5, 0.6] | 945 | 0.5257 | 0.5672 | −0.042 |
| (0.6, 0.7] | 1,292 | 0.6781 | 0.6772 | +0.001 |
| (0.7, 0.8] | 4,284 | 0.7401 | 0.8109 | −0.071 |
| (0.8, 0.9] | 3,039 | 0.8538 | 0.9753 | −0.122 |

The observed rate rises monotonically, which is the property ranking needs, and the worst gap
is 0.122. Both are large improvements on the integer-coded model this replaced, whose worst
gap was 0.334 and whose ordering was *inverted* between 0.6 and 0.9. But a 0.122 gap is still
a model that says 0.85 about orders that are late 98% of the time.

**Consequence:** treat the probability as a rank, not as a quantity. The value-at-risk
figures the application shows are directionally right and should not be summed and reported
as a financial forecast.

### 2. The catalogue turns over, and faster than it looks

Fitted on 2015–2016 and applied forward, the share of orders whose `Product Name` the model
has never seen is:

| slice | Product Name | Category Name | Department Name |
|---|---:|---:|---:|
| 2017 H1 (validation) | 3.40% | 1.71% | 0.00% |
| 2017 H2 onward (test) | **40.10%** | **37.28%** | 19.49% |

Six months after the training window, two in five orders arrive with a product the model has
never seen; the one-hot encoder gives them an all-zero block and predicts from the rest.
Nothing raises, and nothing in the output says the prediction was made with a feature
missing.

**Consequence:** this model has a shelf life of months, not years. A deployment needs a
retraining cadence and a monitor on `CategoryCodes.unseen_rate`, and the number above is the
argument for both.

### 3. The dataset carries fingerprints of being generated

**Every First Class order paid by anything other than TRANSFER is late. All 20,001 of them.**
Not 99.9% — 1.0000, across three payment types and three years.

```
Shipping Mode = First Class
  Type = CASH       3,017 orders   late rate 1.0000
  Type = DEBIT     10,762 orders   late rate 1.0000
  Type = PAYMENT    6,222 orders   late rate 1.0000
  Type = TRANSFER   7,813 orders   late rate 0.8335
```

A real logistics network does not do this. It is the signature of a rule inside whatever
generated the data, and any model fitted here will learn the rule and report high confidence
about it.

**Consequence:** the model's headline performance is partly the recovery of a synthetic rule.
Its performance on real shipments is unknown and should be assumed to be worse. This is the
single strongest reason not to deploy this artefact against live orders.

*(`TODO.md` previously recorded this as 19,997 rows. The measured figure is 20,001; the
original is left in the history rather than quietly edited.)*

### 4. Almost all of the signal is one column

| column | spread in late rate |
|---|---|
| `Shipping Mode` | **0.5725** (0.3807 → 0.9532) |
| `Order Region` | 0.0916 across 23 regions |
| `Market` | 0.009 |
| day of week | 0.0087 |
| weekend flag | 0.0010 |

The model is, to a first approximation, an elaborate way of asking which shipping mode was
chosen. That is why the rule baseline is so hard to beat and why the honest gain is a
ranking one.

**Consequence:** do not read the application's regional chart as a finding. Regional late
rate varies by about five points either side of a 0.5483 base rate, and the dashboard pins
its axis to [0, 1] so that this looks as small as it is.

## What the model does *not* predict

**Order margin.** ChainSight shows an expected profit, and it is arithmetic, not a model:

```
expected profit  =  0.1196  ×  Order Item Total
```

0.1196 is the measured mean margin ratio on the training slice, and `Order Item Total` is
known exactly when the order is placed. This is deliberate. `docs/results.md` builds an
oracle allowed to read the answers from the test set and it reaches R² **0.0036** on
`Order Item Profit Ratio` — so no model of any class can predict it from at-order features
here. Four linear models were fitted anyway and the best beat the mean by 0.0003 MAE, which
is rounding.

The application must present this figure as an estimate with a stated basis, and it does.

## The decision layer

The model's output is not the product. `docs/decision_engine.md` argues each assumption; in
summary:

- The flagging threshold is **0.2966**, derived from `intervention / (intervention + cost of
  a late delivery)` rather than left at 0.5. A threshold of 0.5 silently assumes an
  unnecessary intervention and a missed late delivery cost the same; here the miss costs a
  little over twice as much.
- Priority is **net benefit**, not probability. A 499.95 order at 85% risk outranks a 20.00
  order at 90%.
- **Every cost in that model is an assumption with no empirical basis in this dataset.** The
  data records no intervention, no penalty and no customer response. They are editable in the
  application, they carry an author and a timestamp, and they must never be described as
  measured.

A consequence worth stating because the UI could otherwise imply otherwise: every order in
this catalogue is under 500, so the fixed goodwill penalty is the larger half of the exposure
on a typical order, and **a typical order can never reach CRITICAL however risky it is**.
Value-ranking does less work here than it would in a business with a wider price range.

## Ethical and operational considerations

- **No personal data is used.** Nine columns are dropped at load; `tests/test_ingest.py`
  asserts their absence rather than trusting the pipeline.
- **The model can be wrong in a way that costs a customer nothing and the operator time.**
  That asymmetry is the right one for this application, and the derived threshold encodes it
  deliberately: it flags more orders than a 0.5 threshold would.
- **Automation bias is the realistic harm.** A ranked list looks authoritative. The report
  page therefore shows the arithmetic behind every priority, states that the costs are
  assumptions, and names the model version that produced each stored decision.
- **Retraining cannot be poisoned through the UI.** Training reads a file on the server;
  nothing an operator types reaches it.

## Maintenance

- A model is registered but never promoted automatically. Promotion compares the candidate
  against the incumbent on ranking and refuses a regression; `--force` exists and is a
  deliberate act.
- Every artefact records the feature-set hash, the dataset hash and four library versions,
  and refuses to load if any disagrees.
- Retrain when `unseen_rate` on `Product Name` passes a threshold the deployment chooses.
  Measured turnover above suggests months, not years.

## Version history

| version | change |
|---|---|
| 1.0.0 | First card. Serving model: one-hot random forest, selected on ranking. |
