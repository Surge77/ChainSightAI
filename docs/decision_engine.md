# The decision engine

A probability is not a decision. This document is the argument for every number that turns
one into the other, so that disagreeing with ChainSight's rankings is a conversation about
the business rather than about the code.

Three things are kept separate on purpose:

| | what it knows | where it comes from |
|---|---|---|
| **the model** | how likely a late delivery is | learned from 125,200 orders |
| **the cost model** | what lateness costs, what acting costs | **assumed**, and argued below |
| **the engine** | which orders to act on first | arithmetic over the other two |

The middle row is not learned and cannot be. The dataset records no intervention, no
penalty and no customer response, so every figure in it is a business assumption. They live
in one editable `CostModel` rather than in a formula, and an admin can change them without
touching code.

---

## First, the scale of this business

Measured on the training slice, and worth stating before any of the rest:

| | |
|---|---|
| mean `Order Item Total` | **176.88** |
| median | 159.99 |
| largest order in the table | **499.95** |
| mean margin ratio | 0.1196 |
| mean expected profit per order | **21.15** |

This is retail. Orders are small and the spread is narrow.

An earlier draft of this project reasoned about interventions costing 200 against orders
worth 50,000, and produced a threshold of 0.55 — *above* 0.5, implying it is barely ever
worth acting. That was not a modelling error; it was arithmetic applied to invented figures
for a business that does not exist in this data. Measuring first is what caught it, and the
constants now carry the measurement in their comments.

## The assumptions

| field | default | the argument |
|---|---:|---|
| `intervention` | **15.00** | Expediting a small parcel, a carrier call, a proactive message. Under a tenth of a typical order and about 70% of its margin. |
| `margin_lost_when_late` | **0.5** | Half the order's margin is assumed lost to remediation — partial refunds, reshipping, discounts. |
| `fixed_penalty_when_late` | **25.00** | Goodwill that does not scale with order size: a support contact, a discount on the next order, some chance of losing the customer. |
| `mean_margin` | **0.1196** | Measured, not assumed. See below. |
| `typical_order_value` | **176.88** | Measured. The order the global threshold is calibrated against. |

The one figure that is *not* an assumption is `mean_margin`, and it is measured rather than
predicted for a documented reason: [`results.md`](results.md) establishes that
`Order Item Profit Ratio` cannot be predicted from at-order features by anything. A
predictor allowed to cheat with the test set's own group means reaches R² 0.0036. So

```
expected profit  =  0.1196  ×  Order Item Total
```

where `Order Item Total` is known exactly when the order is placed. It is an estimate with
a stated basis, not a model output dressed up as one, and the UI must say so.

## The threshold is derived, not chosen

A threshold of 0.5 silently asserts that the two mistakes cost the same. Acting on an order
that would have arrived on time wastes the intervention; failing to act on one that arrives
late costs the lateness. Setting the two expected costs equal gives the standard rule:

```
p*  =  intervention / (intervention + cost of a late delivery)
    =  15.00 / (15.00 + 35.60)
    =  0.2966
```

**0.2966, not 0.5.** On these costs a missed late delivery is a little over twice as
expensive as an unnecessary intervention, so ChainSight flags orders that a default
threshold would ignore. `docs/results.md` shows the operational consequence in the threshold
sweep: at 0.5 the model flags 10,007 of 24,369 orders; nearer 0.30 it flags many more, and
the cost model is what says that is the right trade.

## Ranking is by net benefit, not by probability

```
value at risk  =  P(late)  ×  (expected profit × 0.5  +  25.00)
net benefit    =  value at risk  −  15.00
```

The threshold produces a label an operator reads at a glance. The **ranking** ignores it
entirely and sorts on net benefit, which is what puts a large order at 85% above a small one
at 90%:

| order | P(late) | exposure | net benefit | priority |
|---|---:|---:|---:|---|
| 499.95 | 0.85 | 46.66 | **31.66** | critical |
| 176.88 | 0.90 | 32.02 | 17.02 | high |
| 20.00 | 0.90 | 23.55 | 8.55 | monitor |
| 100.00 | 0.10 | 3.10 | −11.90 | low |

## Priority bands

| band | net benefit above | meaning |
|---|---:|---|
| `CRITICAL` | 25.00 | Act now. |
| `HIGH` | 10.00 | Worth intervening. |
| `MONITOR` | 0.00 | Exposure exceeds the cost of acting, but barely. |
| `LOW` | — | Not worth the intervention. |

**A typical order can never be CRITICAL, and that is deliberate.** A 176.88 order exposes at
most 35.60, so its best possible net benefit is 20.60 against a band starting at 25. Only
the upper end of the catalogue reaches critical, which is what a value-aware priority is
supposed to mean. A test asserts it so it cannot drift into a bug.

## What this engine does not do, and one honest limitation

It does not learn. It does not adapt the costs to observed outcomes, because there are no
observed outcomes to adapt to. It does not model a capacity constraint — if 6,000 orders are
flagged, it says so and does not know that the team can handle forty.

And the limitation that matters most for reading its output: **because every order in this
table falls under 500, the fixed goodwill penalty is the larger half of the exposure on a
typical order.** Of a typical 32.02 exposure, 25.00 is the fixed penalty and 7.02 is the
margin at risk. Value ranking therefore does less work here than it would in a business with
a wider price range, and the ordering is closer to a probability ranking than the formula
suggests.

That is a property of the data, not of the design. It is stated here and in the model card
rather than hidden by inventing a bigger spread.
