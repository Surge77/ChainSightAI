# 0003 — Drop every post-dispatch column, and show what it costs

**Status:** accepted

## Context

`Late_delivery_risk` in this dataset is derived from the outcome it labels: it is true exactly
when real shipping days exceed scheduled shipping days, and `Delivery Status` states the
answer in English. Published notebooks report accuracy around 0.98. That number is the leak.

## Decision

Two questions are asked of every one of the 53 columns, and they are kept separate:

- **`Availability`** — when is this value knowable, relative to the moment of prediction?
- **`Disposition`** — what do we do about it?

Every column whose value only exists after dispatch is dropped at ingest, before any other
code sees the frame. Keeping the two questions apart is what makes the audit reviewable:
"dropped" alone invites the reader to assume leakage, while `AT_ORDER` + `DROP_DUPLICATE`
says plainly that the column was available and discarded for a different reason.

And the cost is **demonstrated, not asserted**: `leakage.py` trains the identical estimator
twice and prints both numbers.

## Consequences

| | accuracy |
|---|---|
| with the post-dispatch columns | **1.0000** |
| honest | 0.6956 |

Thirty accuracy points. Not 0.98 — a depth-5 tree needs one split on `Delivery Status` and it
is done.

A second leak was found the same way and is the more interesting one, because it produces a
number that reads as success rather than as an alarm. `Order Item Profit Ratio` is exactly
`Order Profit Per Order / Order Item Total`, and the divisor is a feature. A linear model
given the profit column alone reaches R² 0.1938 — mediocre, unremarkable, nobody investigates
it. Give it the quotient too and it reaches 1.0000. The leak hides because
`LinearRegression` cannot divide.

The whole project's headline number is therefore 0.70 rather than 0.98, and the thirty-point
gap is the deliverable.
