# Data audit

Every column of `DataCoSupplyChainDataset.csv`, and what this project does with it.

Two questions are asked of each column, and they are different questions:

- **When does the value exist?** A value known only after the lorry arrives cannot be an
  input to a prediction made before it leaves.
- **What do we do about it?** Several columns exist at order time and are still dropped,
  because they duplicate another column, identify a row, or identify a person.

The table at the bottom is generated from `src/chainsight/columns.py`, which is the
executable form of the same decisions. `python scripts/render_audit.py --check` fails if
the two disagree, and CI runs it. Neither can drift without the other breaking.

Every equality below was measured on all 180,519 rows.

---

## 1. The classification target is derived from its own outcome

`Late_delivery_risk` is not an observation. It is a comparison:

```
Late_delivery_risk == (Days for shipping (real) > Days for shipment (scheduled))
```

That identity holds on **176,096 of 180,519 rows**. Every one of the 4,423 exceptions is a
`Shipping canceled` row, where the label is 0 regardless of the arithmetic — a shipment
that never went cannot be late.

`Delivery Status` separates the target perfectly:

| Delivery Status | not late | late |
|---|---:|---:|
| Late delivery | 0 | 98,977 |
| Advance shipping | 41,592 | 0 |
| Shipping on time | 32,196 | 0 |
| Shipping canceled | 7,754 | 0 |

And `shipping date (DateOrders) − order date (DateOrders)` reproduces
`Days for shipping (real)` on 175,862 rows, so the dates leak by another route.

Published analyses of this dataset report accuracy around 0.98. Any model with
`Delivery Status` in its features scores that, and so does a two-line `if` statement. It is
not a result.

**Dropped as leaks:** `Days for shipping (real)`, `Delivery Status`,
`shipping date (DateOrders)`, `Order Status`.

## 2. The regression side leaks too, and this is the one usually missed

The classification leak is well known. The profit leak is not, and it is worse, because it
produces an R² near 1.0 that looks like success.

- `Benefit per order` is **byte-identical** to `Order Profit Per Order`. The same number,
  twice, under two names.
- `Order Profit Per Order ≈ Order Item Total × Order Item Profit Ratio`. The relation is
  approximate only because the ratio is rounded to two decimals.

So predicting profit from a feature set containing either column is predicting a number
from itself.

`Order Item Total` **is** known when the order is placed. The only unknown is the margin.
ChainSight therefore regresses `Order Item Profit Ratio` and reports

```
expected_profit = predicted_ratio × Order Item Total
```

Same business answer, honest problem, and a scale-free target — which matters, because the
curriculum offers only linear regressors and a target dominated by order size would give
them an R² that flatters the model rather than describing it.

## 3. Eleven columns are the same information twice

Measured, not guessed. Each of these is exactly equal to another column on every row:

| Duplicate | Kept instead |
|---|---|
| `Sales per customer` | `Order Item Total` |
| `Benefit per order` | (dropped as a leak — equals `Order Profit Per Order`) |
| `Category Id`, `Product Category Id` | `Category Name` |
| `Department Id` | `Department Name` |
| `Order Customer Id` | (dropped as an identifier — equals `Customer Id`) |
| `Order Item Cardprod Id`, `Product Card Id` | `Product Name` |
| `Order Item Product Price` | `Product Price` |
| `Sales` | `Product Price × Order Item Quantity`, both kept |
| `Order Item Discount` | `Order Item Discount Rate` |

And one that is not an equality but is just as redundant:

**`Shipping Mode` and `Days for shipment (scheduled)` are a perfect bijection.**

| Shipping Mode | scheduled days | rows |
|---|---:|---:|
| Same Day | 0 | 9,737 |
| First Class | 1 | 27,814 |
| Second Class | 2 | 35,216 |
| Standard Class | 4 | 107,752 |

No mode ever takes a second value; no value ever belongs to a second mode. `Shipping Mode`
is kept because it is what an operator actually chooses in the form.

## 4. Personal data

The dataset ships nine columns that identify a person or a household. All are dropped at
load, before any other code sees the frame — a column that never exists cannot reach a log
line, a traceback, a feature-importance table or a committed artefact.

`Customer Email` and `Customer Password` are masked to the constant `XXXXXXXXX` in this
release. That is not a reason to read them. `Latitude` and `Longitude` carry 11,250
distinct customer coordinates and are a street address in another notation.

See [SECURITY.md](../SECURITY.md).

## 5. Two columns are empty

`Product Description` is null on all 180,519 rows. `Product Status` is `0` on all of them.

## 6. What is left, and how much of it matters

Sixteen columns survive. Their signal is very unevenly distributed, and saying so up front
is more useful than a dashboard that implies otherwise.

**Shipping Mode dominates everything else combined:**

| Shipping Mode | late rate | rows |
|---|---:|---:|
| First Class | 0.9532 | 27,814 |
| Second Class | 0.7663 | 35,216 |
| Same Day | 0.4574 | 9,737 |
| Standard Class | 0.3807 | 107,752 |

A single `if` on that column scores **0.6953 accuracy**, against a majority-class baseline
of 0.5483. Every model in this project is measured against 0.6953, not against 0.5483.

**Payment type is a real second signal that accuracy cannot see:**

| within mode | CASH | DEBIT | PAYMENT | TRANSFER |
|---|---:|---:|---:|---:|
| First Class | 1.0000 | 1.0000 | 1.0000 | 0.8335 |
| Second Class | 0.7873 | 0.7958 | 0.8063 | 0.6811 |
| Same Day | 0.5018 | 0.4772 | 0.4778 | 0.3963 |
| Standard Class | 0.3884 | 0.3965 | 0.3999 | 0.3397 |

Adding `Type` to the one-rule model changes accuracy by **nothing at all** — 0.6953 either
way — because the majority side never flips. It changes the *probability* from 1.00 to
0.83 on a group of 7,813 orders. ChainSight's decision engine consumes probability, not
labels, so `Type` is worth keeping even though the accuracy column says it is worthless.
This is the clearest example in the dataset of why accuracy is the wrong headline metric.

Note also that First Class with any payment type other than TRANSFER is late on **all
19,997 rows**. A deterministic subgroup like that is a fingerprint of synthetic generation,
not of a real carrier. It is not leakage — payment type is chosen at checkout — but it
should be read as an artefact of how this data was made, and it caps how much a model can
be said to have learned about logistics.

**Geography barely matters:**

| | late rate |
|---|---|
| Market (5 levels) | 0.5436 – 0.5521 |
| Order Region (23 levels) | 0.4880 – 0.5796, extremes on the smallest groups |

A control-tower dashboard showing regions at 72% / 48% / 34% would be inventing its own
data. `docs/results.md` and the admin panel report the real spread, which is about five
points around the base rate.

**The target is stable over time**, which is good news for the time-aware split — there is
no drift to confound it:

| Shipping Mode | 2015 | 2016 | 2017 | 2018 |
|---|---:|---:|---:|---:|
| First Class | 0.9576 | 0.9549 | 0.9449 | 0.9787 |
| Second Class | 0.7705 | 0.7679 | 0.7594 | 0.7708 |
| Same Day | 0.4459 | 0.4321 | 0.5022 | 0.4167 |
| Standard Class | 0.3794 | 0.3840 | 0.3780 | 0.3911 |

**The honest ceiling.** A lookup table over five surviving features and 6,509 groups
reaches 0.7062 accuracy *in sample*. No model in this project should be expected to beat
that by much out of sample, and one that does should be suspected of a leak rather than
congratulated.

## 7. Dates

`order date (DateOrders)` runs 2015-01-01 to 2018-01-31: 62,650 rows in 2015, 62,550 in
2016, 53,196 in 2017 and 2,123 in January 2018. The format is `%m/%d/%Y %H:%M`.

The raw timestamp is never a feature. It selects the split and it produces calendar
features; a model that reads it as a number learns "later is different", which is the
one thing the split exists to stop it doing.

---

## The table

<!-- BEGIN GENERATED: python scripts/render_audit.py -->

| disposition | columns |
|---|---:|
| use | 16 |
| target | 2 |
| drop: leak | 6 |
| drop: personal data | 9 |
| drop: identifier | 7 |
| drop: duplicate | 11 |
| drop: constant or empty | 2 |
| **total** | **53** |

| # | column | available | disposition | why |
|---:|---|---|---|---|
| 0 | `Type` | at order | use | Payment method, chosen at checkout. TRANSFER runs 8-12pp less late than the other three inside every shipping mode. |
| 1 | `Days for shipping (real)` | post dispatch | drop: leak | Actual transit time. With the scheduled days it reconstructs the classification target exactly. |
| 2 | `Days for shipment (scheduled)` | at order | drop: duplicate | A perfect 1:1 bijection with Shipping Mode: 0=Same Day, 1=First Class, 2=Second Class, 4=Standard Class. The same variable twice. |
| 3 | `Benefit per order` | post dispatch | drop: leak | Byte-identical to Order Profit Per Order on all 180,519 rows, which is the regression target multiplied by the order total. |
| 4 | `Sales per customer` | at order | drop: duplicate | Byte-identical to Order Item Total on all 180,519 rows. |
| 5 | `Delivery Status` | post dispatch | drop: leak | Separates the target perfectly: 'Late delivery' is exactly the 98,977 positive rows and nothing else appears there. |
| 6 | `Late_delivery_risk` | post dispatch | target | The classification target. Equals (real > scheduled) on 176,096 rows; all 4,423 exceptions are 'Shipping canceled'. |
| 7 | `Category Id` | at order | drop: duplicate | Identical to Product Category Id, and Category Name is the readable form of the same 50 levels. |
| 8 | `Category Name` | at order | use | 50 product categories. The readable key kept in place of two integer twins. |
| 9 | `Customer City` | at order | drop: identifier | 563 levels naming where one customer lives. Near-identifying, and geography carries almost no signal here. |
| 10 | `Customer Country` | at order | use | Two levels, EE. UU. and Puerto Rico. Cheap, and pairs with Order Country to say whether a shipment crosses a border. |
| 11 | `Customer Email` | never | drop: personal data | Personal data. Masked to a single constant in this release, which does not make it a column to read. |
| 12 | `Customer Fname` | never | drop: personal data | Personal data. |
| 13 | `Customer Id` | at order | drop: identifier | 20,652 levels. A model that learns a customer id has memorised the table, not the problem. |
| 14 | `Customer Lname` | never | drop: personal data | Personal data. |
| 15 | `Customer Password` | never | drop: personal data | A password column in a public teaching dataset. Never read, never stored, never logged. |
| 16 | `Customer Segment` | at order | use | Consumer, Corporate or Home Office. Three levels, known at checkout. |
| 17 | `Customer State` | at order | use | 46 levels. Coarse enough not to locate a household, fine enough to carry regional effects if any exist. |
| 18 | `Customer Street` | never | drop: personal data | Personal data. Locates a household. |
| 19 | `Customer Zipcode` | never | drop: personal data | Personal data. Locates a household to a few streets. |
| 20 | `Department Id` | at order | drop: duplicate | Department Name is the readable form of the same 11 levels. |
| 21 | `Department Name` | at order | use | 11 departments, from Fan Shop at 66,861 rows to Health and Beauty at 362. |
| 22 | `Latitude` | never | drop: personal data | 11,250 distinct customer coordinates. A street address in another notation. |
| 23 | `Longitude` | never | drop: personal data | As Latitude. |
| 24 | `Market` | at order | use | Five levels. Kept for reporting rather than for signal: late rate ranges 0.5436 to 0.5521 across all five, which is noise. |
| 25 | `Order City` | at order | drop: identifier | 3,597 levels. Order Region and Order Country say the same thing without one level per town. |
| 26 | `Order Country` | at order | use | 164 destinations. High cardinality under LabelEncoder, so it helps trees and misleads the linear models; the model card says so. |
| 27 | `Order Customer Id` | at order | drop: duplicate | Identical to Customer Id on all 180,519 rows. |
| 28 | `order date (DateOrders)` | at order | use | The moment the order is placed. Used for the time-aware split and for derived calendar features, never as a raw number. |
| 29 | `Order Id` | at order | drop: identifier | 65,752 orders. An identifier. |
| 30 | `Order Item Cardprod Id` | at order | drop: duplicate | Identical to Product Card Id on all 180,519 rows. |
| 31 | `Order Item Discount` | at order | drop: duplicate | Sales minus Order Item Total to within a hundredth of a currency unit. The rate carries the same information scale-free. |
| 32 | `Order Item Discount Rate` | at order | use | 18 discrete rates from 0.00 to 0.25. |
| 33 | `Order Item Id` | at order | drop: identifier | One value per row. A row number wearing a business name. |
| 34 | `Order Item Product Price` | at order | drop: duplicate | Identical to Product Price on all 180,519 rows. |
| 35 | `Order Item Profit Ratio` | post dispatch | target | The regression target: margin as a fraction of the order total. Ranges -2.75 to 0.50; 18.7% of rows are loss-making. |
| 36 | `Order Item Quantity` | at order | use | 1 to 5 units. Just over half of all rows are single-unit. |
| 37 | `Sales` | at order | drop: duplicate | Exactly Product Price times Order Item Quantity, both of which are kept. |
| 38 | `Order Item Total` | at order | use | The line value after discount. Kept because the decision engine multiplies it by the predicted margin; the feature builder may still drop it as collinear. |
| 39 | `Order Profit Per Order` | post dispatch | drop: leak | The regression target multiplied by the order total. Keeping it hands the model the answer. |
| 40 | `Order Region` | at order | use | 23 regions. Real but small: 0.488 to 0.580 late, and the extremes sit on the smallest groups. |
| 41 | `Order State` | at order | drop: identifier | 1,089 levels. Order Region covers the same geography at a usable cardinality. |
| 42 | `Order Status` | post dispatch | drop: leak | Assigned after the fact. SUSPECTED_FRAUD and CANCELED cannot be known when the order is placed. |
| 43 | `Order Zipcode` | never | drop: personal data | Personal data, and 86% null besides. |
| 44 | `Product Card Id` | at order | drop: duplicate | 118 levels; Product Name is the readable form of the same catalogue. |
| 45 | `Product Category Id` | at order | drop: duplicate | Identical to Category Id on all 180,519 rows. |
| 46 | `Product Description` | at order | drop: constant or empty | Null on all 180,519 rows. |
| 47 | `Product Image` | at order | drop: identifier | A URL per product. Product Name is the same key, readable. |
| 48 | `Product Name` | at order | use | 118 products. The readable catalogue key. |
| 49 | `Product Price` | at order | use | 75 distinct list prices. |
| 50 | `Product Status` | at order | drop: constant or empty | Zero on all 180,519 rows. |
| 51 | `shipping date (DateOrders)` | post dispatch | drop: leak | Subtracting the order date reconstructs the real transit time, and with it the target. |
| 52 | `Shipping Mode` | at order | use | The dominant signal by a wide margin: 38.1% late on Standard Class against 95.3% on First Class. |

<!-- END GENERATED -->
