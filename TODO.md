# Open work

Things known to be missing, so a cold start does not rediscover them. Closed items move to
`CHANGELOG.md` rather than being ticked here.

## Next

- [ ] **Phase 1** — `scripts/fetch_data.py`, the DataCo download, the recorded SHA-256, and
      the committed 500-row sample.

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
