# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `deploy/docker/` — a Dockerfile, an entrypoint and a runbook for hosting this on a generic
  Docker host, plus `render.yaml` at the root as a Render Blueprint. It is a second Dockerfile
  rather than a flag on the first because the two platforms disagree about the thing most
  likely to break a deployment: a Space is told its port at build time and bakes it in, while
  Render, Koyeb and Fly choose one at run time and inject it as `PORT`. An image that gets
  that wrong builds, starts, logs a clean startup line, and fails its health check against a
  port nothing is listening on. Nothing is assembled — the repository is public, so the
  platform clones it and builds against the root, which is `push-space.sh`'s whole job made
  unnecessary rather than duplicated.
- `tests/test_deploy_docker.py`, the sibling of `test_deploy_hf.py`, checking the second image
  against the application it deploys. It carries one assertion the Space's file has no reason
  to: `chainsight train` writes to `persistence.ARTEFACTS_DIR`, a *relative* `Path("artifacts")`
  resolved against the working directory, while the application reads `CHAINSIGHT_ARTEFACTS`.
  Nothing connects the two but a Dockerfile agreeing with itself, and disagreeing is silent at
  both ends — the build succeeds, having trained a model, and the container starts, serving
  from a directory nobody put one in.
- All four secrets in `render.yaml` are `sync: false`, so the blueprint names them and is
  structurally unable to carry their values. A blueprint that could hold a secret would be a
  secret in git history.

### Changed
- The repository is public. The Dockerfile in `deploy/hf/` builds from the source pushed
  beside it because it was private and an unauthenticated build 404s; that is now a
  belt-and-braces choice rather than a necessity, and it is left alone — a deployment that
  copies files it is already being handed has one fewer thing that can fail.
- `TODO.md`'s "deferred infrastructure" section said a Dockerfile and Postgres were still
  missing. Postgres shipped in 1.2.0 and there are now two Dockerfiles; both lines are closed
  where they stood, and a "not yet deployed" item replaces them, because neither image has
  ever been built — there is no Docker on the development machine.

## [1.2.0] - 2026-09-03

**The release that makes this deployable in public.** Three things stood between a working
application on localhost and a URL anybody can open: a login form that would check as many
passwords as anybody cared to post, a wheel with no pages in it, and a database that lived on
a filesystem rebuilt every restart. All three are closed, and `deploy/hf/` is the container
that follows from them.

615 tests. `src/` at 100% line and branch coverage, on Python 3.11 and 3.12, and the web
suite runs a second time against a real Postgres.

### Added
- `deploy/hf/` — a Dockerfile, an entrypoint and a runbook for hosting this as a Hugging Face
  Docker Space, plus `push-space.sh`, which assembles the Space's tree from a `git archive` of
  the current commit and refuses to run against a dirty one. The image builds from that source
  rather than installing a tag from GitHub, because this repository is private and an
  unauthenticated build 404s on both the release tarball and the raw file — the alternative
  was a credential in a deployment to avoid copying files it is already handed. It trains the
  500-row sample during the build rather than shipping a `.joblib`, because a repository that
  refuses to commit a pickled model should not smuggle one into an image. The first
  administrator is made by the entrypoint, since `chainsight_web init` normally wants a shell
  and a Space has none; running it on every start is a no-op after the first.
- `tests/test_deploy_hf.py`, which checks the deployment files against the application they
  deploy: the port in the Space header matches the one the container binds, the ref is a tag
  and not a branch, the entrypoint has Unix line endings, and every `CHAINSIGHT_*` the
  Dockerfile exports is a name `src/` actually reads. That last one already earned its place
  — it caught the Dockerfile setting a rate-limiting variable that the branch it was built on
  did not yet have, which would have deployed a public sign-up form with the limiter inert.
- Postgres, through `CHAINSIGHT_DATABASE`. SQLite stays the default; this is for a
  deployment whose filesystem is rebuilt on every restart, where a database file means every
  account registered yesterday is gone today — and where the attempts table the rate limiter
  counts in would reset on anything that restarted the process, making "cause a restart" the
  cheapest way past the limit. `psycopg[binary]` is its own `postgres` extra, because nothing
  in the application imports it and somebody running against a file should not have to
  acquire a database driver.
  [ADR 0014](docs/adr/0014-postgres-when-the-filesystem-does-not-persist.md).
- A second CI job running the web suite against a real `postgres:17`. The dialect a
  deployment serves on should not be the one dialect nothing tests: SQLite returns a naive
  datetime from a timezone-aware column and Postgres returns an aware one, and mixing them is
  a `TypeError` rather than a wrong answer.
- `pool_pre_ping` and a five-minute `pool_recycle` on every engine. A serverless Postgres
  suspends an idle branch and drops its connections without telling the pool, so the first
  request after an idle period gets a closed socket and dies with `OperationalError: server
  closed the connection unexpectedly`, then works on a retry — a failure that reads as
  flakiness rather than as configuration.
- Money is labelled. Every amount on a page and in the CLI now carries a currency symbol,
  defaulting to the dollar this dataset is priced in — every customer in it is in the United
  States or Puerto Rico, and none of its 118 products is ever sold at two prices, so the
  per-destination currency the 164 `Order Country` values suggest is not what the table
  holds. `CHAINSIGHT_CURRENCY` relabels the pages for a deployment that bills in something
  else, which matters because the cost model at `/admin/costs` is the operator's own money
  rather than the dataset's. Only two-decimal currencies are accepted: an unsupported code
  stops the process at startup rather than printing cents that the currency does not have.
  [ADR 0012](docs/adr/0012-name-the-currency.md).
- Rate limiting on every POST a stranger can reach. Ten sign-in attempts per source address
  per fifteen minutes, shared between `/login` and `/admin/login`; five registrations per
  address per hour. The window slides, so there is no lockout period to serve — an address
  recovers as its oldest attempt ages out. This closes the first item in `SECURITY.md`'s
  "what is not defended against", which had said that an attacker with a candidate list was
  limited only by bcrypt's own cost.

  Counted per address rather than per account, deliberately. Per-account lockout hands
  anybody a way to lock anybody else out of an application with no recovery flow, and it
  catches strictly less: one source guessing many passwords at one account and one source
  guessing one password at many accounts are the same bucket when the bucket is the source.
  `docs/adr/0013-count-attempts-per-address.md` argues it, and records what stays open.
- `CHAINSIGHT_FORWARDED_ALLOW_IPS`, passed to uvicorn along with `proxy_headers`. It decides
  which address a request appears to come from, and therefore what the rate limiter counts.
  It defaults to trusting a proxy on this machine and nobody else; both ways of getting it
  wrong are named beside the constant in `config.py`.
- `intervention_effectiveness` on the cost model: the share of the damage stepping in is
  assumed to prevent, editable at `/admin/costs` and dated and attributed like every other
  cost. It defaults to 1.0, which is the assumption the decision engine was already making
  without saying so — `net benefit = value at risk − intervention` claims that paying to
  expedite removes the whole expected cost of lateness. `docs/decision_engine.md` shows what
  lowering it does: at 0.6 the recoverable total over the same orders falls by three
  quarters.
- A per-order break-even probability, stored beside the threshold on every prediction and
  shown on the order's report. One global cut-off cannot be the break-even for a catalogue
  running from a few dollars to $499.95, and this is the number the order's priority is
  actually decided on.

### Fixed
- A built wheel contained no templates and no stylesheet. `[tool.setuptools.package-data]`
  declared `py.typed` and nothing else, so `pip install chainsight[web]` installed a web
  application with no pages in it and `create_app` died on the `StaticFiles` mount. Every
  install anyone has ever done was editable — which points at the source tree and therefore
  hides this completely — so the bug was only ever going to appear the first time somebody
  packaged the thing properly. `tests/test_packaging.py` now checks the declared patterns
  against what is actually on disk, which costs a file walk rather than a build.
- Nine sentences across the README, the decision engine, the order report and its tests
  described this catalogue in **rupees**. It is a United States retail table. The figures
  were never wrong; the unit attached to them in prose was.

### Changed
- The dashboard's "worth acting on" card is now "Recoverable", and carries the share of
  exposure it represents, how many orders it covers, what acting on them costs, and the
  exposure being carried on the orders where acting would cost more than it saves. The card
  previously invited a subtraction against "money at risk" that did not hold: the gap was
  the cost of acting *plus* the exposure on excluded orders, and only the first was implied.
- "Worth acting on" is no longer the name of a money column on `/orders` and a report
  figure, because it is also the plain-English gloss of the `high` band in the legend
  directly beneath that column. Both are now "net saving if we act".
- The dashboard's flagged card is "Above the risk cut-off", and says it is a risk label
  rather than an instruction.

### Fixed
- The flagging threshold and the ranking were computed from different assumptions about who
  pays for an intervention, so they contradicted each other on screen: orders between 0.2966
  and 0.4216 were counted as flagged and ranked `LOW`, which reads "leave it". The threshold
  was `intervention / (intervention + late cost)` — Elkan's false-positive rule, which
  charges the intervention only when it turns out to have been unnecessary — while net
  benefit charged it always. Both now derive from one accounting, and the threshold on the
  default costs is 0.4216 rather than 0.2966. [ADR 0011](docs/adr/0011-one-set-of-books.md)
  records the correction; [ADR 0006](docs/adr/0006-derive-the-threshold.md) is marked as
  corrected rather than rewritten.
- The application refuses to start against a database that predates a column, naming the
  column and both ways out, instead of failing as a 500 inside a template on the first
  request that reads it.
- `init --reset-password` no longer moves the account's role. `--operator` defaulted to
  "administrator" when it was absent, so the natural way to help a locked-out operator —
  `init --email them --reset-password` — silently promoted them, and the same flag on an
  admin silently demoted them. Both bypassed the `role_changes` row that `/admin/users/role`
  writes on every web-initiated role change, so the promotion left no trail to find. The
  role now moves only when a role flag is actually typed.
- `init --reset-password` marks the account `must_change_password`. A password typed at a
  shell is one the administrator knows, and without the hold it kept working for the life of
  the account — the deniability `/admin/users` has always closed by issuing passwords it
  never lets the administrator choose. A reset now opens exactly one door, the same as
  every other administrator-set password.
- The `[1.1.0]` heading is a link again, and `[Unreleased]` compares from v1.1.0 rather than
  showing the release that just shipped.

## [1.1.0] - 2026-08-28

Everything the application grew after the first release: the CSRF gap `SECURITY.md` had
listed as open since phase 0, an administrator surface that can grant a role without a
shell, and a `init` that no longer discards a password it asked for.

**516 tests. `src/` at 100% line and branch coverage**, on Python 3.11 and 3.12.

### Added
- **CSRF tokens on every state-changing request**, closing the first of the four gaps
  `SECURITY.md` has listed as deliberately absent since phase 0. The check is a dependency
  registered on the *application* rather than on individual routes, so a form added later is
  covered without anybody remembering — and a form without a token fails closed, loudly, as
  a 403 rather than silently as a hole. The token cookie is `HttpOnly` (nothing reads it
  from script; the server renders the value into the HTML) and rotates when a session
  starts, which is the CSRF half of session fixation. A test posts to every state-changing
  route without a token and requires all of them to refuse, and a second test scans the
  templates so a form without one is a build failure. See `docs/adr/0010-csrf-tokens.md`.
- An administrator can create an account at `/admin/users`, but never choose its password.
  One is generated, shown exactly once, and marked `must_change_password`: until the owner
  replaces it the account reaches nothing but `/password`. That hold is the whole point — it
  is the difference between a password an administrator *set* and a password an
  administrator *knows*, and without it every action by that account stays deniable.
- `/admin/users`: an administrator can grant and revoke the administrator role. ADR 0009 is
  amended rather than contradicted — its objections were to the role being *self*-granted
  (a registration checkbox, a first-user-wins race), and neither describes an existing
  administrator promoting a colleague. Requiring a shell for that is a bottleneck, and what
  people do about bottlenecks is share the admin password.
- `role_changes`: every grant and revoke, naming both parties, written in the same commit as
  the change and shown on the page that makes them. The emails are stored on the row rather
  than joined, so the record survives the account being deleted.
- Three things the page still will not do: create an account (no password field, because an
  administrator who sets your password makes your every action deniable), remove the last
  administrator (whoever asks), or change a role without recording it.
- A separate administrator sign-in at `/admin/login`, and an anonymous visitor to an admin
  page is now sent there rather than to the operator form. It is a separate door, not a
  separate mechanism: the same credential check, the same signed cookie, and the same role
  read from the database on every request. It cannot grant the role, and a valid operator's
  credentials are refused with the *same* sentence a wrong password gets — a different one
  would turn the page into an oracle for which accounts are administrators.

### Changed
- One measure for the whole page. The masthead and the disclaimer were full-bleed while the
  content and footer were centred in a 62rem column, so a wide window showed three different
  left edges. All four now read from `--measure` and `--gutter`.
- The sign-in, registration and administrator pages get their own narrow centred column. A
  login form stranded at the left of a 62rem measure looks lost on a wide screen.

### Fixed
- `python -m chainsight_web init` read the password before it looked the account up, so on
  an email that already existed it set `is_admin`, committed, printed a success line — and
  dropped the password the caller had just typed. Somebody locked out could run it, type a
  new password, read `is_admin is now True`, and reasonably believe the password worked. It
  did not. The lookup happens first now, an existing account is never asked for a password
  it cannot use, and the message says outright that the password is unchanged;
  `--reset-password` remains the way to actually replace one.

## [1.0.0] - 2026-08-27

The first release. Fifteen phases: the leakage audit, the models, the decision engine, the
artefacts and registry, the application, and the documents that say what all of it may and
may not be used for.

**438 tests. `src/` at 100% line and branch coverage. Every phase behind a green CI run on
Python 3.11 and 3.12.**

### The four findings this release exists to record

1. **The published ~0.98 on this dataset is a leak.** With the post-dispatch columns a
   depth-5 tree scores 1.0000; without them, 0.6956.
2. **The profit column leaks too, and quietly.** `Order Profit Per Order / Order Item Total`
   *is* the regression target. A linear model given the profit column alone reaches R² 0.1938,
   which reads as a mediocre model rather than an alarm.
3. **The margin ratio cannot be predicted by anything.** An oracle allowed to cheat reaches
   R² 0.0036, so the product computes expected profit rather than modelling it.
4. **Accuracy and F1 were the wrong metrics.** On average precision the models beat the rule
   baseline by 0.069 — 0.8215 against 0.7528 — which both hid completely.

### Added
- `scripts/fetch_data.py` and `data/dataset_manifest.json`: the dataset is downloaded into a
  gitignored directory and checked against a recorded SHA-256, row count and column count.
  The manifest also records that the file is latin-1 rather than UTF-8, that the archive's
  95 MB clickstream table is discarded because it shares no key with the order table, and
  that the licence is CC0-1.0.
- `src/chainsight/contract.py`, `src/chainsight/columns.py` and `src/chainsight/schema.py`:
  the column contract. Every one of the 53 source columns carries when its value exists and
  what this project does about it, with a one-sentence reason. 16 survive as feature
  candidates, 2 are targets, 35 are dropped as leaks, personal data, identifiers,
  duplicates or empties.
- `docs/data_audit.md`: the argument behind those decisions, with the numbers measured on
  all 180,519 rows. Its column table is generated by `scripts/render_audit.py`, and
  `--check` fails the build when the document and the contract disagree.
- `scripts/make_sample.py` and `data/sample_orders.csv`: a 500-row deterministic slice,
  stratified by shipping mode and year, with the nine personal-data columns removed using
  the contract's own list rather than one retyped in the script.

- `src/chainsight/ingest.py`: the single door into the data. Reads the latin-1 source,
  refuses a frame that is missing a feature or carries a column absent from the contract,
  drops the 35 columns the contract rejects, parses the order date and rounds the
  publisher's float32 discount rate. Verified end to end on all 180,519 rows: 18 columns
  out, late rate 0.5483, 18.71% loss-making.
- `ingest(..., exclude_cancelled=True)`: an explicit flag for the 7,754 orders labelled
  not-late because the shipment never went. Off by default, so the frame matches the task
  as published; excluding them moves the late rate from 0.5483 to 0.5729.

- `src/chainsight/encoding.py`: `LabelEncoder` category codes with an `UNSEEN` fallback.
  Fitting on orders before 2017 and applying to 2017 onward leaves 19.56% of rows with an
  unseen `Product Name`, 17.38% unseen `Category Name` and 8.59% unseen `Department Name` —
  the catalogue turns over, and `LabelEncoder.transform` would raise on one row in five.
- `src/chainsight/features.py`: one feature builder, 23 columns, used by training and by
  serving. A test asserts a single operator order produces the same columns in the same
  order *and the same values* as that row did in training.

- `src/chainsight/split.py`: a chronological split (train 2015-2016, validate 2017 H1, test
  2017 H2 onward) alongside a labelled shuffled split kept only for comparison.
- `src/chainsight/baselines.py`: majority class, per-shipping-mode rate, and mean margin.
- `src/chainsight/evaluate.py`: accuracy, precision, recall and F1 -- the last three derived
  from the confusion matrix rather than imported, which matches the formulas in the revision
  notes and makes a model that predicts no positives score zero instead of warning.
- `docs/results.md` and `scripts/report_baselines.py`: the numbers to beat, and the command
  that regenerates them. On the held-out slice the majority baseline scores 0.5511 accuracy
  and 0.7106 F1; the one-line shipping-mode rule scores 0.6956 accuracy and 0.6635 F1. A
  model has to clear both at once. The mean-margin baseline sets MAE at 0.2930.

- `src/chainsight/leakage.py` and `docs/leakage.md`: the same estimator trained twice, and
  the numbers printed side by side. With the post-dispatch columns a depth-5 tree scores
  **1.0000** accuracy; without them, 0.6956. The margin leak is worse and quieter: handing
  a linear model `Order Profit Per Order` reaches R-squared 0.1938, which reads as a
  mediocre model, but adding the single ratio `profit / order total` reaches **1.0000**,
  because that quotient is the target. A shuffled split, by contrast, scores 0.6923 against
  the chronological 0.6956 - it does not flatter the model on this table at all.

- `src/chainsight/models.py`, `tuning.py` and `compare.py`: ten taught classifiers, grid
  searched over four expanding time-ordered folds, scored beside the baselines in one table.
  Row caps for `SVC`, `KNeighborsClassifier` and the bagged logistic are printed in the same
  row as the score, because a cap changes what the score means.
- `evaluate.threshold_sweep` and `evaluate.reliability`: what stands in for a ROC curve and
  a calibration plot. The sweep names operating points and says how many orders each flags;
  the reliability table bins predicted probability against observed rate.

- `src/chainsight/regressors.py` and `compare.run_margin`: the four taught regressors on the
  margin target. None of them separates from the mean baseline; lasso ties it exactly, having
  driven every coefficient to zero.
- `src/chainsight/ceiling.py`: an oracle that cheats, to distinguish "this model class cannot
  reach the signal" from "there is no signal". On `Order Item Profit Ratio` the cheating
  predictor reaches R-squared 0.0036, so no model of any class can predict it here. The tool
  reports rows-per-group beside every score and marks a ceiling as memorising rather than
  meaningful once the groups get finer than five rows each.

- `evaluate.ranking_scores`, `encoding.OneHotColumns`, and four declared classifiers. On
  average precision the models beat the rule baseline by 0.069 - 0.8215 against 0.7528 -
  which accuracy and F1 had hidden entirely. One-hot encoding also repairs the calibration
  defect: the worst gap falls from 0.334 to 0.122 and the probability ordering, previously
  inverted between 0.6 and 0.9, is now monotone.

- `src/chainsight/decision.py` and `docs/decision_engine.md`: the cost model, the derived
  threshold and the priority bands. The threshold works out at 0.2966 rather than 0.5,
  because on these costs a missed late delivery is a little over twice as expensive as an
  unnecessary intervention. Ranking is by net benefit, so a 499.95 order at 85% risk
  outranks a 20.00 order at 90%.

- `src/chainsight/persistence.py`: artefacts, and the two ways loading one goes wrong.
  `joblib.load` unpickles, so the loader takes a *name* and refuses anything resolving
  outside the artefacts directory — the sentence `SECURITY.md` has carried since phase 0 is
  now the code that keeps it. Every artefact carries a manifest recording the feature-set
  hash, the dataset hash and the four library versions inside the pickle, and a mismatch on
  any of them is a hard error. The failure being defended against is silent: an estimator
  indexes its features positionally, so the same columns in a different order predicts
  confidently and wrongly.
- `src/chainsight/training.py`: one path that fits the model the application serves, reusing
  `split.by_date`, `FeatureSpace.fit` and `tuning.tune` rather than reimplementing any of
  them. The production default is the one-hot random forest, chosen on ranking, and the
  threshold in its manifest comes from the cost model rather than from 0.5.
- `src/chainsight/registry.py`: a JSON model registry, readable in a text editor in two
  years with no tooling installed. Registering never promotes, and promoting compares the
  candidate against the incumbent on ranking and refuses a regression — newer is not better.
  `force` exists so that overriding the guard appears in the argument list.
- `src/chainsight/cli.py` and `python -m chainsight`: `describe`, `leakage`, `compare`,
  `train`, `registry` and `predict`, every one of them able to run against the committed
  500-row slice so a fresh clone can see the output without a download.

- `src/chainsight_web/`: the application. FastAPI, SQLAlchemy over SQLite, Jinja2 templates
  and one stylesheet. Six tables — `users`, `orders`, `predictions`, `model_versions`,
  `training_runs`, `decision_config` — where `model_versions` is a read model refreshed from
  `artifacts/registry.json` rather than a second place that decides which model is live.
- Operator pages: an order form whose dropdowns come from the categories the live model was
  fitted on, and a report that renders a `decision.Decision` field for field. Every field of
  the decision is stored rather than recomputed, so editing the cost model does not rewrite
  what a past report says the system decided.
- Admin pages: a control tower, the model registry, and an editable cost model. Retraining
  and promotion both go through `registry.promote`, so the compare-then-promote guard has one
  implementation. A refused promotion is written to `training_runs` with its reason.
- Security, as `SECURITY.md` has described it since phase 0 and now implements: bcrypt with
  a refusal rather than silent truncation past its 72-byte limit, signed session cookies
  carrying nothing but a user id, no default session secret, the admin role read from the
  database on every request, ownership filtered in the query, and Pydantic validation at
  every route boundary.
- `python -m chainsight_web init` and `serve`. Making an administrator is a server-side
  command because the alternatives — a first-user-becomes-admin rule, or a checkbox on the
  registration form — are a race and a privilege escalation respectively.

- `docs/model_card.md`: intended use, out-of-scope uses, and four measured weaknesses — a
  0.122 calibration gap, 40% catalogue turnover six months out, the synthetic fingerprint
  below, and the fact that almost all the signal is one column.
- `docs/data_card.md`: provenance, licence, the nine personal-data columns and where they go,
  and the four properties to know before believing any number derived from this dataset.
- `docs/architecture.md` and `docs/glossary.md`: how the pieces fit, the four boundaries that
  are load-bearing rather than tidy, and every term this project uses in a specific way.
- `docs/adr/`: nine architecture decision records, each carrying the measurement that settled
  the argument — the curriculum gate, the time split, the dropped columns, the margin model
  that does not exist, selection on ranking, the derived threshold, the JSON registry,
  server-rendered pages over SQLite, and the absent session-secret default.

### Measured for the model card
- **Every First Class order paid by anything other than TRANSFER is late — all 20,001 of
  them, at a rate of exactly 1.0000** across CASH, DEBIT and PAYMENT. A real logistics network
  does not do this; it is a rule inside whatever generated the data, and it is the single
  strongest reason not to deploy this artefact against live orders. `TODO.md` had recorded
  19,997; the corrected figure sits next to the original rather than replacing it.
- **Catalogue turnover accelerates.** Fitting on 2015–2016, the share of orders with an unseen
  `Product Name` is 3.40% in 2017 H1 and **40.10%** from 2017 H2. The model has a shelf life
  of months, not years.

### Fixed
- `docs/results.md` cited the training mean margin as 0.1206. The measured figure, and the
  constant `decision.py` has always used, is **0.1196**.
- `SECURITY.md` and the data card listed six personal-data columns. The contract drops
  **nine**: `Latitude`, `Longitude` and `Order Zipcode` were omitted from the prose while
  being dropped by the code all along.
- `ingest.read_raw` decoded every CSV as latin-1, which is right for the published 92 MB
  source and wrong for `data/sample_orders.csv`, which `scripts/make_sample.py` writes as
  UTF-8. Reading the slice by path therefore produced `AfganistÃ¡n` — silently, because
  latin-1 cannot fail. It now tries UTF-8 strictly first and falls back to latin-1, which is
  safe in that order and only in that order: UTF-8 is self-validating, so a latin-1 file
  cannot be misread as UTF-8, while the reverse succeeds and corrupts. Caught by looking at
  the order form in a browser, where the mangled country names were in a dropdown.

### Changed
- `scripts/check_taught.py` now labels rather than blocks. A third tier, `DECLARED`, holds
  names from outside the course material, each carrying the measurement that justified it,
  and `--report` prints how much of `src/` rests on each tier. 24 of 29 scikit-learn names
  still come from the course material.
- CI now runs `scripts/render_audit.py --check`, and uses `actions/checkout@v5` and
  `actions/setup-python@v6` — the v4/v5 pair is pinned to a deprecated Node runtime.

## [0.1.0] — 2026-08-26

The scaffold, and the rule the rest of the project has to live inside.

### Added
- Packaging (`pyproject.toml`) with every dependency pinned exactly, a `web` extra so the
  models can be installed without a web server, and a `dev` extra.
- `scripts/check_taught.py` — an AST-based gate that fails the build on any scikit-learn
  import in `src/` outside the taught curriculum, on any import of a banned modelling
  library, and on `import sklearn` itself, which would hide later attribute access from
  the check. Thirteen tests, including the parenthesised multi-line import that defeats a
  grep-based version of the same idea.
- Continuous integration running ruff, pyright, pytest and the taught-set gate in both its
  default and `--strict` modes.
- `SECURITY.md`, recording that the DataCo dataset ships a `Customer Password` column and
  what happens to it, and that a `joblib` artefact is executable code rather than data.
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CITATION.cff`, `LICENSE` (MIT), issue and pull
  request templates, and a README stating up front that this is a production-shaped
  application over a historical dataset, not a live system.

[Unreleased]: https://github.com/Surge77/ChainSightAI/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/Surge77/ChainSightAI/releases/tag/v1.1.0
[1.0.0]: https://github.com/Surge77/ChainSightAI/releases/tag/v1.0.0
[0.1.0]: https://github.com/Surge77/ChainSightAI/releases/tag/v0.1.0
