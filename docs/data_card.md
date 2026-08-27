# Data card — DataCo Smart Supply Chain

What the dataset is, where it came from, what this project does to it before anything else
touches it, and the four properties of it that a reader should know before believing any
number derived from it.

The column-by-column argument is in [`data_audit.md`](data_audit.md); this is the summary and
the provenance.

---

## Provenance

| | |
|---|---|
| **Name** | DataCo Smart Supply Chain for Big Data Analysis |
| **Source** | [Kaggle: `shashwatwork/dataco-smart-supply-chain-for-big-data-analysis`](https://www.kaggle.com/datasets/shashwatwork/dataco-smart-supply-chain-for-big-data-analysis) |
| **Licence** | CC0-1.0 (public domain dedication) |
| **Retrieved** | 2026-08-26 |
| **File** | `DataCoSupplyChainDataset.csv`, 95,910,149 bytes |
| **SHA-256** | `fa6d022ed437155e1a2f0378710602848703c8a7f203f7ff5d77805bf8480aa6` |
| **Shape** | 180,519 rows × 53 columns |
| **Period** | orders from 2015-01-01 to 2018-01-31 |
| **Encoding** | **latin-1**, not UTF-8 |

The dataset is **not redistributed here.** `scripts/fetch_data.py` downloads it into a
gitignored directory and verifies it against the hash, row count and column count above:

```bash
python scripts/fetch_data.py            # fetch
python scripts/fetch_data.py --verify   # check an existing copy
```

Two things in the same archive are handled explicitly rather than silently:

- `DescriptionDataCoSupplyChain.csv`, the publisher's own column glossary, is kept — because
  `docs/data_audit.md` disagrees with parts of it and it is fairer to keep the thing being
  disagreed with.
- `tokenized_access_logs.csv`, a 95 MB clickstream table, is **deleted on fetch**. It shares
  no key with the order table and answers no question this project asks, and 95 MB of
  unusable data sitting in `data/raw/` is an invitation to a mistake.

### Encoding, and a bug it caused

The source is latin-1. The committed slice is UTF-8. `ingest.read_raw` therefore tries UTF-8
strictly first and falls back to latin-1, which is safe in that order and only in that order:
UTF-8 is self-validating, so a latin-1 file carrying an accent cannot be read as UTF-8 by
accident, while a UTF-8 file read as latin-1 succeeds and silently produces `AfganistÃ¡n`.

That is not hypothetical. It is exactly what happened, and it was found by looking at a
dropdown in the running application rather than by any test.

## What survives ingest

53 columns in, 18 out: **16 feature candidates and 2 targets.** 35 are dropped, and each one
carries a one-sentence reason in `src/chainsight/columns.py` that a test holds in step with
`docs/data_audit.md`.

| disposition | columns | why, in one line |
|---|---:|---|
| feature | 16 | knowable at the moment the order is placed |
| target | 2 | `Late_delivery_risk`, `Order Item Profit Ratio` |
| drop: leak | 6 | only exists after the shipment happened |
| drop: personal data | 9 | identifies a person or a household |
| drop: identifier | 7 | identifies a row, not a pattern |
| drop: duplicate | 11 | the same quantity under another name |
| drop: constant or empty | 2 | one value, or none |

### The 16 features

`Type`, `Category Name`, `Customer Country`, `Customer Segment`, `Customer State`,
`Department Name`, `Market`, `Order Country`, `Order Region`, `Product Name`,
`Shipping Mode`, `Order Item Discount Rate`, `Order Item Quantity`, `Order Item Total`,
`Product Price`, `order date (DateOrders)`.

## Personal data

Nine columns are dropped **at load**, before any other code in the project sees the frame:

| column | why |
|---|---|
| `Customer Password` | A password column, in a public teaching dataset. Never read, never stored, never logged. |
| `Customer Email` | Direct identifier. |
| `Customer Fname`, `Customer Lname` | Direct identifiers. |
| `Customer Street`, `Customer Zipcode` | Locates a household. `Customer City` / `State` / `Country` are coarse enough to keep. |
| `Latitude`, `Longitude` | A coordinate pair is a household at street resolution, whatever it is labelled. |
| `Order Zipcode` | Same reason as `Customer Zipcode`, on the delivery side. |

They are not dropped downstream as a courtesy. A column that never exists cannot reach a log
line, a traceback, a feature-importance table or a committed artefact, and
`tests/test_ingest.py` asserts their absence rather than trusting the pipeline to remember.

`data/raw/` is gitignored. The only committed slice, `data/sample_orders.csv`, is produced by
`scripts/make_sample.py` through the same ingest path, so it is post-redaction by construction
rather than by inspection.

## The targets

**`Late_delivery_risk`** — 1 when the shipment took longer than scheduled. Base rate
**0.5483** across the whole table, and remarkably stable: 0.5497 in 2015–2016, 0.5405 in
2017 H1, 0.5511 from 2017 H2. There is no drift here to confound a chronological comparison,
which is convenient and slightly surprising.

**`Order Item Profit Ratio`** — margin as a share of the order total. Mean 0.1196 on the
training slice; 18.71% of orders are loss-making. `docs/results.md` establishes that nothing
predicts it from at-order features: an oracle allowed to cheat reaches R² 0.0036.

## Four properties to know before believing a number

### 1. The published label is derived from the outcome it labels

`Late_delivery_risk` is true exactly when `Days for shipping (real)` exceeds `Days for
shipment (scheduled)`, and `Delivery Status` states the answer in English. Notebooks on this
dataset routinely report ~0.98 accuracy. That number is the leak.

Trained with the post-dispatch columns, a depth-5 tree scores **1.0000**. Without them,
0.6956. `docs/leakage.md` runs both.

### 2. The profit leak is quieter, and worse

`Order Item Profit Ratio` is exactly `Order Profit Per Order / Order Item Total`, and the
divisor is a feature. Hand a linear model the profit column alone and it reaches R² 0.1938 —
a mediocre-looking model nobody would investigate. Hand it the quotient too and it reaches
1.0000. The leak hides because `LinearRegression` cannot divide.

### 3. The data is generated, and it shows

**Every First Class order paid by anything other than TRANSFER is late — all 20,001 of them,
at a rate of exactly 1.0000.** A real logistics network does not produce that. It is a rule
inside whatever generated this data.

This is the property that most limits what any result here means, and it is why the model
card says performance on real shipments should be assumed to be worse.

### 4. The catalogue turns over quickly

Fitting on 2015–2016 and applying forward, the share of orders with a previously unseen
`Product Name` is 3.40% in 2017 H1 and **40.10%** from 2017 H2. Both encoders tolerate an
unseen value without raising, so this is invisible unless it is measured.

## The committed sample

`data/sample_orders.csv` — 500 rows, deterministic, stratified by shipping mode and year,
written as UTF-8 with the nine personal-data columns removed using the contract's own
drop-list rather than one retyped in the script. It exists so the test suite and every CLI
command run without a 92 MB download.

**Its late rate is 0.5800 against the population's 0.5483**, from rounding in the per-cell
allocation. Harmless for tests. It must never be quoted as a statistic about the dataset.

## Reproducing everything here

```bash
python scripts/fetch_data.py --verify        # provenance
python scripts/render_audit.py --check       # the audit matches the contract
python -m chainsight describe                # shape, base rate, what ingest dropped
python -m chainsight leakage                 # both leaks, trained twice each
```
