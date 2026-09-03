---
title: ChainSight
emoji: 📦
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Pre-dispatch late-delivery risk and margin, behind a cost-sensitive decision engine.
---

# ChainSight

An order has been placed and has not shipped yet. ChainSight estimates how likely it is to
arrive late, works out how much money that would cost, and answers the question you actually
have: **is this order worth doing something about?**

Orders are ranked by what acting on them is worth, not by how risky they are. Being told an
order is 90% likely to be late is not useful on its own — if the order is worth twenty
dollars, chasing it costs more than losing it.

Source, measurements and the full argument: **https://github.com/Surge77/ChainSightAI**

## What you are looking at

Register an account, enter an order, and read the report. The sixteen fields on the form are
the ones known *before* dispatch, and the dropdowns are built from the categories the model
was actually fitted on.

## Read this before you judge the numbers

**It is trained on 500 rows.** The full DataCo table is ~92 MB and is not ours to
redistribute, so this Space runs on the committed sample. The accuracy figures quoted in the
repository come from the full 180,519-row table; nothing here reproduces them. The sample's
own late rate is 0.5800 against the population's 0.5483, which is rounding in the per-cell
allocation and is not a fact about the dataset.

**It is not connected to anything.** No live shipments, no real customers. The data is a
public historical teaching dataset, and every column that could identify a person is dropped
at load rather than later as a courtesy.

**The cost model is assumptions.** What stepping in costs, what a late delivery costs in
goodwill — these are stated business judgements with no empirical basis in this dataset. The
repository's `docs/decision_engine.md` argues each one and keeps saying they are assumptions.

**Do not put anything real in it.** It is a demo with a public sign-up form.

## The part the repository is actually about

`Late_delivery_risk` in this dataset is derived from the outcome it labels. Published
notebooks report accuracy around 0.98 on it. That number is a leak, not a model — a depth-5
tree needs one split on `Delivery Status` and it is done.

ChainSight drops every column that does not exist at the moment an order is placed, and
trains the same model twice to show the price:

| | accuracy |
|---|---|
| with the post-dispatch columns | **1.0000** |
| honest | 0.6956 |

Thirty accuracy points is what it costs to ask the question when you would actually need the
answer. The second leak is the more interesting one, and it is in the repository.
