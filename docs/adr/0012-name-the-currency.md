# 0012 — Name the currency, once, for the whole deployment

**Status:** accepted

## Context

Every amount this project prints was rendered bare. `499.95` on a report, `176.88` in a
docstring, `21` of margin in a comment. A number with no unit invites the reader to supply
one, and over eleven months the prose supplied the wrong one: nine sentences across
`README.md`, `decision.py`, `report.html`, `docs/decision_engine.md` and `test_decision.py`
described this catalogue in **rupees**.

The dataset is not in rupees, and it is not ambiguous either:

| evidence | measurement |
|---|---|
| `Customer Country` | two values only — `EE. UU.` (111,146) and Puerto Rico (69,373). Both on the dollar. |
| price by destination | 118 distinct products, **none** sold at two prices. The Perfect Fitness Rip Deck is 59.99 into all 150 countries it reaches. |
| currency column | none |
| FX rate column | none |

The obvious-looking alternative was a currency per order, taken from `Order Country` — 164
destinations, France and Mexico and Australia among them. The second row above rules it out.
A product priced identically into 150 countries is not being sold in 150 currencies; these
are one seller's books. Rendering `€59.99` on a French order would assert something the row
does not say, and converting properly would need an FX rate as of a 2015–2018 order date
that the repository does not have and cannot reconstruct.

There is a second, sharper reason. `/orders` ranks on `net_benefit`. A ranking is only
meaningful inside one currency, so per-order currencies would not merely mislabel the page —
they would break the sort that the decision engine exists to produce.

## Decision

One display currency per deployment, `CHAINSIGHT_CURRENCY`, defaulting to **USD**.

`chainsight/money.py` owns the symbol table and the formatter; `chainsight_web.config` reads
the same variable through the same function, so the CLI and the web app cannot drift into
different answers. `templating.render` binds the currency into every template context as
`money()`, alongside `user` and the CSRF token, for the reason that function already exists:
a page cannot forget what it is never asked to remember.

It is a setting rather than a constant because two kinds of money reach the screen. Order
totals come from the dataset and are dollars permanently. The cost model on `/admin/costs` —
what an intervention costs, what a late delivery costs in goodwill — is typed in by whoever
runs the application, in whatever currency their business runs on. A `$` hard-coded into the
templates would put a dollar sign on a number somebody entered in rupees, which is the
failure this ADR is fixing, reintroduced from the other end.

Only currencies with a two-decimal minor unit are accepted, and the list is a whitelist. The
formatter writes cents unconditionally, and `JPY 1,234.56` shows a subunit the yen does not
have. An unsupported code stops the process at startup rather than printing a wrong figure
on every page that shows a price — the same posture as
[0009](0009-no-default-session-secret.md), for the same reason.

## Consequences

No stored number changes and no model is retrained. `CostModel.threshold` is
`intervention / (effectiveness × late_cost)`, a ratio, so the currency cancels out of it
entirely; the amounts scale linearly and are relabelled, not recomputed.

The defaults in `CostModel` were always dollars. `TRAINING_MEAN_ORDER_VALUE = 176.88`,
`intervention = 15.0` and `fixed_penalty_when_late = 25.0` were calibrated against this
table's scale, and an operator who switches the display currency without re-entering them is
reading dollars under a different symbol. The cost page says which currency it is asking
for; it cannot say whether the numbers already in the fields mean it.

One dollar sign survives translation, on the order report: the sentence naming the training
catalogue's price range, a few dollars to $499.95. That range is a fact about the dataset
rather than about the operator's money, the sentence says so, and a test asserts it is the
only one left when the app is configured in another currency.

The non-ASCII symbols reach a Windows console through whatever code page it is set to, and a
legacy one cannot render `₹`. The default is ASCII and unaffected; `money.py` says so.
