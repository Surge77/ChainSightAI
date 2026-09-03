# Open work

Things known to be missing, so a cold start does not rediscover them. Closed items move to
`CHANGELOG.md` rather than being ticked here.

---

## Where the project is

Fifteen phases merged to `main`, every one behind a green CI run on Python 3.11 and 3.12.
**516 tests, `src/` at 100% line and branch coverage.** Tags: `v0.1.0` through `v1.1.0`.

The ML core is finished, its findings are written down, a trained model can be saved,
registered, promoted and served, the application around it runs, and the model card, data
card, architecture, glossary and ten ADRs say what all of it may and may not be used for.

`v1.1.0` is tagged — the release plus the CSRF check, the administrator surface and the
`init` fix that followed it. Everything below is optional.

### To pick it up again

```bash
cd C:/Users/tdmne/Desktop/ML/Projects/ChainSightAI
.venv/Scripts/activate                  # the venv is already built
python scripts/fetch_data.py --verify   # confirms the 92 MB source file is intact

# the gate, green before any commit
ruff check . && ruff format --check .
pyright
pytest -q --cov=src --cov-report=term-missing
python scripts/check_taught.py
python scripts/render_audit.py --check
```

Reproduce the headline numbers:

```bash
python -m chainsight_web serve          # the application, once a model is promoted
python -m chainsight compare            # the fourteen-model comparison
python -m chainsight compare --margin   # and the margin half, which finds nothing
python -m chainsight leakage            # both leaks, trained twice each
python scripts/report_baselines.py      # what every model is measured against
```

The `scripts/` versions are kept: they are pinned to regenerating the numbers in the
documents, and a document whose figures cannot be reproduced by running the file that
produced them is a document that will drift.

Read `docs/results.md` first. It carries the findings, and two places where an earlier claim
in this repository turned out to be wrong and was corrected next to the original.

### The four findings, one line each

1. **The published ~0.98 on this dataset is a leak.** With the post-dispatch columns a
   depth-5 tree scores **1.0000**; without them, 0.6956.
2. **The profit column leaks too, and quietly.** `Order Profit Per Order / Order Item Total`
   *is* the regression target. A linear model given the profit column alone reaches R²
   0.1938, which reads as a mediocre model rather than an alarm.
3. **The margin ratio cannot be predicted by anything.** An oracle allowed to cheat reaches
   R² 0.0036, so the product computes expected profit rather than modelling it.
4. **Accuracy and F1 were the wrong metrics.** On average precision the models beat the rule
   baseline by 0.069 — 0.8215 against 0.7528 — which both hid completely.

---

## Next, in dependency order

Nothing is required for `v1.0.0`. What follows is the work that would make it better.

- [ ] **Counterfactual explanations.** Re-predict with one controllable field changed and
      report the delta — "switch to First Class: +31pp" is a more useful sentence for an
      operator than a feature-importance bar. Deferred from phase 10 and still the most
      droppable piece in the plan; the README's comparison table promises it, so either build
      it or amend that row.
- [ ] **A retraining monitor.** `CategoryCodes.unseen_rate` already measures catalogue
      turnover and the model card records that it reaches 40% six months past the training
      window. Nothing watches it. A model with a shelf life of months and no alarm on it is
      the most likely way this application becomes quietly wrong.
- [ ] **Recalibration.** The serving model's worst reliability gap is 0.122, which is a model
      saying 0.85 about orders that are late 98% of the time. Ranking survives it; the value
      figures the UI shows are weaker than they look because of it.

## Questions raised and not settled

- [ ] Whether to train with `exclude_cancelled=True`. The 7,754 cancelled shipments are
      labelled not-late because they never went, which is label noise rather than an on-time
      delivery. Excluding them moves the late rate 0.5483 → 0.5729. Measure the effect on
      held-out scores and then choose.
- [ ] Product identity may be worth dropping entirely. Fitted before 2017 and applied after,
      `Product Name` is unseen on 19.56% of rows and `Category Name` on 17.38%. A feature
      absent for a fifth of the future is a liability; measure whether keeping it beats
      dropping it.
- [x] ~~First Class with any payment type other than TRANSFER is late on **all 19,997 rows**.~~
      Measured again for the model card: it is **20,001 rows**, at a rate of exactly 1.0000
      across CASH, DEBIT and PAYMENT. The original count is left here rather than quietly
      edited. `docs/model_card.md` and `docs/data_card.md` both now carry it as the single
      strongest reason not to deploy this artefact against live orders.
- [ ] The depth-5 tree in the leakage demo scores 0.6956, matching the shipping-mode rule to
      four decimals; the *tuned* tree scores 0.5972. Read both fitted trees and confirm the
      first is the rule and the second is overfitting.
- [x] ~~The model card has to explain that the production model is chosen on ranking.~~ Done:
      `docs/model_card.md` says it under "What it is measured against", including that on
      accuracy the serving model beats the rule baseline by half a point.
- [ ] `Order Country` has 164 levels. One-hot with `min_frequency=50` handles it now, but
      what integer codes cost the linear models was never separately measured.
- [ ] The 500-row committed sample's late rate is 0.5800 against the population's 0.5483,
      from rounding in the per-cell allocation. Harmless for tests; never quote it as a
      dataset statistic.
- [ ] The decision engine's costs are assumptions with no empirical basis in this dataset.
      `docs/decision_engine.md` argues each one, and the documentation must keep saying they
      are assumptions.

## Security, before this faces anything but localhost

Named in `SECURITY.md` as deliberately absent.

- [x] ~~CSRF tokens on every form post.~~ Done, and checked by a dependency registered on
      the application rather than route by route, so a form added later is covered without
      anybody remembering. See `docs/adr/0010-csrf-tokens.md`.
- [x] ~~Login rate limiting and account lockout.~~ Rate limiting is done, per source address
      and not per account — the lockout half of that line was rejected rather than skipped,
      because locking an account after N wrong passwords lets anybody lock anybody else out
      of an application with no recovery flow. See `docs/adr/0013-count-attempts-per-address.md`.
- [ ] A distributed brute force, spread across many source addresses, is still not slowed
      down. That is the part per-account counting would catch, and it needs an answer to the
      denial-of-service problem above before it can be built.
- [ ] Record model promotions made from the registry page. Retrains, cost-model edits and
      role changes all carry an author and a timestamp; a model promotion made on its own
      does not.

Closed by construction rather than by a check: an operator cannot poison the retraining set
through the UI, because retraining reads `CHAINSIGHT_DATASET` — a file on the server — and
nothing entered through the application reaches the training data.

## Known noise

- [ ] Every test run prints `StarletteDeprecationWarning: Using httpx with
      starlette.testclient is deprecated; install httpx2 instead`. It comes from FastAPI's
      own `TestClient` and cannot be silenced by anything this repository does short of
      taking `httpx2` as a dependency — which needs the same audit as any other new
      dependency, so it is recorded here rather than papered over with a warning filter.
      This project's own position is that a warning on every run trains a reader to ignore
      warnings, so this should not sit here indefinitely.

## Deferred infrastructure

- [ ] Dockerfile and compose.
- [ ] Postgres. SQLite is sufficient for a single-node portfolio deployment and the schema
      is written to survive the swap.
