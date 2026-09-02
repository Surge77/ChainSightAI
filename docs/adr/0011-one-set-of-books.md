# 0011 — Keep the threshold and the ranking on one set of books

**Status:** accepted, corrects [0006](0006-derive-the-threshold.md)

## Context

[0006](0006-derive-the-threshold.md) derives the flagging threshold from the cost model and
ranks separately on net benefit. Both halves were right to exist. They were computed from
different assumptions about who pays for an intervention.

```
threshold    p* = intervention / (intervention + late cost)   = 0.2966
net benefit       probability x late cost - intervention
```

The first is Elkan's false-positive rule: it charges the intervention only when the order
would have arrived on time anyway. The second charges it always, which is what actually
happens — you pay to expedite before you know the outcome.

The result was two answers to one question on one screen. Orders between 0.2966 and 0.4216
were counted on the dashboard as flagged and ranked `LOW`, whose recommendation reads "leave
it". Three of the twenty orders entered into the running application sat in that band. The
prose in `docs/decision_engine.md` derived `intervention / late cost` in words and printed
`intervention / (intervention + late cost)` underneath, which is how a plain arithmetic
disagreement survived review.

A second assumption was unstated. `net benefit = value at risk - intervention` says that
spending the intervention removes the entire expected cost of lateness: expediting is
assumed to work every time. Nothing in the cost model said so, and nothing let an operator
disagree.

## Decision

One accounting, and every assumption in it named.

```
net benefit  =  effectiveness x probability x late cost  -  intervention
threshold    =  intervention / (effectiveness x late cost)              = 0.4216
break-even   =  the same, with this order's own value rather than the typical one
```

`intervention_effectiveness` becomes a field of `CostModel` beside the others, dated and
attributed like every other cost an admin edits. It defaults to **1.0** — the assumption the
engine was already making. Inventing a smaller number would assert something about a
business this dataset does not record, which is the mistake an earlier draft of the cost
model already made once with interventions costing 200 against orders worth 50,000.

`Decision.break_even` is stored on every prediction beside the threshold, because the two
can legitimately disagree and the report has to be able to say why.

## Consequences

The threshold moves from 0.2966 to 0.4216 on the default costs. It is still below 0.5, and
the reason to derive it rather than round at half is unchanged, but the marketing version of
that claim — "we flag orders a default threshold would ignore, and there are a lot of them"
— is weaker than it was. It was weaker all along; the number was flattering because half the
intervention cost was not being charged.

Flag and priority now agree exactly on an order of `typical_order_value`. They still diverge
either side of it, and that divergence is real rather than a bug: one global cut-off cannot
be the break-even for every price in a catalogue. A cheap order can be flagged and still not
be worth acting on. The report says so in the order's own numbers instead of leaving an
operator to notice a contradiction and distrust the page.

Lowering effectiveness rescales every net benefit, so the priority bands need rescaling with
it. Below about 0.75 nothing in this catalogue can reach `CRITICAL`. That is documented in
`docs/decision_engine.md` and in the field's own help text rather than discovered.

Predictions already stored keep the numbers they were made under, as they always have. The
dashboard therefore aggregates rows from before and after this change, and derives its
exposure decomposition from each row's own stored figures rather than from today's cost
model, so a re-reading of history is never silently mixed in.
