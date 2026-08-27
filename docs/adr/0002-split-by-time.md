# 0002 — Split by time, not at random

**Status:** accepted

## Context

The course splits with `train_test_split`, and its reason is the right one: test on data the
model has not seen. A shuffled split on this table satisfies the letter of that and not the
point — orders from March 2017 would train a model scored on orders from January 2017, and
the model would be asked to predict a past it had already been shown.

## Decision

Split chronologically. Train on 2015–2016, tune on 2017 H1, and look at everything from
2017 H2 onward exactly once. Grid search uses expanding windows inside the training slice, so
no fold is ever scored on data older than its own training block.

`split.at_random` is kept, clearly labelled, so the two can be compared rather than the
difference asserted.

## Consequences

**The comparison was worth running, and the result is not the expected one.** On this dataset
the shuffled split scores 0.6923 against the chronological 0.6956 — it barely flatters the
model at all, because the late rate is remarkably stable across the three slices (0.5497,
0.5405, 0.5511).

A demonstration that lands where nobody expects is worth more than one confirming a slogan,
so it is reported rather than quietly dropped.

The chronological split is kept regardless. It costs nothing here and it is the only honest
arrangement for a question about the future — and the *other* thing it exposes is real: 40%
of test-slice orders carry a product the training slice never saw, which a shuffled split
would have hidden completely.
