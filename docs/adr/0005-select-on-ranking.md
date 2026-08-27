# 0005 — Select the production model on ranking, not accuracy

**Status:** accepted. Supersedes the metric choice made in phases 5–8.

## Context

Phases 5 through 8 measured every model with accuracy and F1 against two baselines, concluded
that nothing cleared both at once, and were correct about that. A threshold sweep confirmed
it: at 0.35 the best model clears the F1 bar and loses accuracy; at 0.50 it clears accuracy
and loses F1. There is no threshold that clears both.

The conclusion was right and the question was wrong.

## Decision

**A control tower does not answer "is this order late, yes or no". It works down a list.** The
product is a *ranking*, and neither accuracy nor F1 measures one — both collapse a probability
to a label at some threshold and throw the ordering away.

`roc_auc_score` and `average_precision_score` are therefore declared in the curriculum gate,
each with the measurement that justified it, and the production model is chosen on ranking.

| | accuracy | f1 | roc auc | avg precision |
|---|---|---|---|---|
| shipping-mode rule | 0.6956 | 0.6635 | 0.7341 | 0.7528 |
| **one-hot random forest** | 0.7008 | 0.6828 | **0.7518** | **0.8215** |

## Consequences

On average precision the models beat the four-line rule baseline by **0.069**. That is a real
and useful margin for a queue, and accuracy and F1 hid all of it — on those two the same
models looked interchangeable with a `groupby`.

The earlier conclusion stands as written for the bar it was measured against, and the
correction sits next to it rather than replacing it. That is the honest record: the finding
was not that the models were bad, it was that the measurement was answering a question nobody
asked.

**This obliges the model card to say something uncomfortable**, and it does: on accuracy alone
the production model beats the rule baseline by half a point, and anybody quoting an accuracy
figure for it is quoting a number a `groupby` already achieves.
