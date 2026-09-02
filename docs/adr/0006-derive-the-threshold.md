# 0006 — Derive the decision threshold from costs

**Status:** accepted; the formula below is corrected by [0011](0011-one-set-of-books.md), which keeps the threshold and the ranking on the same accounting

## Context

A classifier emits a probability. Turning it into an action needs a threshold, and 0.5 is the
default everywhere.

0.5 is not neutral. It silently assumes that an unnecessary intervention and a missed late
delivery cost the same amount.

## Decision

Derive it. Acting on an order that would have arrived on time wastes `intervention`; failing
to act on one that arrives late costs the late cost. Setting the two expected costs equal
gives

```
p* = intervention / (intervention + cost of a late delivery)
```

which on the project's default costs is **0.2966**.

Ranking is separate, and is by **net benefit** — `probability × late cost − intervention` —
not by probability. The threshold exists only for the risk label an operator reads at a
glance.

## Consequences

An order at 0.35 risk is flagged. At a threshold of 0.5 it would be ignored, and on these
costs ignoring it is the wrong call.

A 499.95 order at 85% risk outranks a 20.00 order at 90%. That inversion is the entire reason
the decision module exists.

**Every cost in the model is an assumption with no empirical basis in this dataset.** The data
records no intervention, no penalty and no customer response. They are named, editable fields
carrying an author and a timestamp rather than constants buried in a formula, so that
disagreeing with them is a conversation about the business rather than about the code — and
the documentation must keep saying they are assumptions.

Measuring first caught a real error. An earlier draft reasoned about interventions costing 200
against orders worth 50,000. This is a retail table: the largest order is 499.95 and the
average carries about 21 of margin. Every default was rescaled.

One consequence is stated rather than hidden: because every order is under 500, the fixed
goodwill penalty is the larger half of a typical exposure, so **a typical order can never
reach CRITICAL however risky it is**. Value ranking does less work here than it would in a
business with a wider price range. That is a property of the data, and a test pins it so the
UI never implies otherwise.
