# Open work

Things known to be missing, so a cold start does not rediscover them. Closed items move to
`CHANGELOG.md` rather than being ticked here.

## Next

- [ ] **Phase 5** — `split.py`, the time-aware split, and the two baselines every model is
      measured against: the shipping-mode rule at 0.6953 accuracy, and the mean margin at
      0.2941 MAE.

## Questions raised and not settled

- [ ] Product identity may be worth dropping entirely. Fitted before 2017 and applied
      after, `Product Name` is unseen on 19.56% of rows and `Category Name` on 17.38%.
      A feature that is absent for a fifth of the future is a liability; measure whether
      keeping it beats dropping it before assuming either.
- [ ] Whether to train with `exclude_cancelled=True`. The 7,754 cancelled shipments are
      labelled not-late because they never went, which is label noise rather than an
      on-time delivery. Excluding them moves the late rate 0.5483 -> 0.5729. Measure the
      effect on held-out scores in phase 7 and then choose, rather than choosing now.
- [ ] First Class with any payment type other than TRANSFER is late on all 19,997 rows.
      That is a fingerprint of synthetic generation. Decide whether the model card should
      cap its claims accordingly, or whether the subgroup should be reported separately.
- [ ] `Order Country` has 164 levels under LabelEncoder. Measure what that costs the linear
      models before assuming the trade-off named in the audit is the right one.
- [ ] The 500-row sample's late rate is 0.5800 against the population's 0.5483, from
      rounding in the per-cell allocation. Harmless for tests; do not quote it as a
      dataset statistic anywhere.

## Security, before this faces anything but localhost

Named in `SECURITY.md` as deliberately absent. All four are required for a real deployment.

- [ ] CSRF tokens on every form post.
- [ ] Login rate limiting and account lockout.
- [ ] An audit log of admin actions — promotions, retrains, config changes.
- [ ] A guard against an operator poisoning the retraining set through the UI.

## Methodology, deferred on purpose

- [ ] Probability calibration is reported (decile reliability table) but never corrected.
      `CalibratedClassifierCV` is outside the curriculum; a hand-rolled isotonic fit would
      be inside it, and is worth doing once the honest baseline exists.
- [ ] Group-aware splitting. The time-aware split does not prevent the same customer
      appearing either side of the boundary. Whether that matters here is an open question
      and should be measured, not assumed.
- [ ] The decision engine's late-delivery penalty is a configurable guess. It has no
      empirical basis in this dataset and the documentation must keep saying so.

## Deferred infrastructure

- [ ] Dockerfile and compose (phase 16).
- [ ] Postgres. SQLite is sufficient for a single-node portfolio deployment and the schema
      is written to survive the swap.
