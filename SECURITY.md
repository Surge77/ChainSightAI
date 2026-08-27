# Security Policy

## Reporting a vulnerability

Open a [private security advisory](https://github.com/Surge77/ChainSightAI/security/advisories/new)
rather than a public issue. Expect an acknowledgement within seven days.

Please do not open a public issue for anything that would let someone read another user's
predictions, escalate to the admin role, or execute code on a machine running this app.

## Supported versions

The tip of `main` only. This is a portfolio project, not a maintained product, and no
patches are backported to tags.

---

## What this project deliberately does

### The dataset contains personal data, and it never enters the repository

The DataCo Smart Supply Chain CSV ships with nine columns that have no business being in a
model or in version control:

| Column | Why it is dropped |
|---|---|
| `Customer Password` | A password column in a public teaching dataset. Never read, never stored, never logged. |
| `Customer Email` | Direct identifier. |
| `Customer Fname`, `Customer Lname` | Direct identifiers. |
| `Customer Street`, `Customer Zipcode` | Locates a household. `Customer City`/`State`/`Country` are coarse enough to keep. |
| `Latitude`, `Longitude` | A coordinate pair is a household at street resolution, whatever the column is called. |
| `Order Zipcode` | Same reason as `Customer Zipcode`, on the delivery side. |

`chainsight.ingest` drops these **at load**, before any other code sees the frame, and
`tests/test_ingest.py` asserts they are absent from the returned columns. They are not
dropped later, downstream, as a courtesy — a column that never exists cannot leak into a
log line, a traceback, a feature-importance table, or a committed artefact.

`data/raw/` is gitignored. The only committed slice, `data/sample_orders.csv`, is produced
by `scripts/make_sample.py`, which runs the same ingest path, so it is post-redaction by
construction rather than by inspection.

### Model artefacts are code, and are treated as code

`joblib.load` unpickles, and unpickling executes arbitrary code in the current process.
Loading an artefact somebody sent you is equivalent to running a script they sent you.

Accordingly:

- `artifacts/` and `*.joblib` are gitignored. Nothing in this repository ships a
  pre-trained binary you are invited to load.
- `chainsight.persistence` loads only from the configured artefacts directory and refuses
  a path that resolves outside it, so a crafted filename cannot walk to another location.
- Every artefact carries a manifest recording the library versions, the feature-set hash
  and the training dataset hash. A mismatch is a hard error, not a warning: silently
  serving a model against features it was not trained on is a correctness bug that looks
  like a working system.

### Web application

- Passwords are hashed with `bcrypt`. No plaintext, no reversible encoding, no home-made
  hashing.
- Sessions are signed cookies (`itsdangerous`) with the secret read from the environment.
  The app **refuses to start** without one rather than falling back to a default — a
  default secret in a portfolio repo is a forged-session vulnerability with a public key.
- The admin role is checked server-side on every admin route. It is never inferred from a
  form field, a cookie value, a query parameter, or a template variable.
- Every state-changing request carries a CSRF token, checked by a dependency registered on
  the application rather than on individual routes — so a form added later is protected
  without anybody remembering to protect it. The token cookie is `HttpOnly`, and it rotates
  when a session starts.
- An administrator may grant and revoke the role at `/admin/users`, and every change writes
  a `role_changes` row naming both parties. Nobody can grant themselves the role and the
  last administrator cannot be demoted. Making the *first* administrator still requires
  `python -m chainsight_web init` on the server, because there is nobody to authorise it.
- An administrator may create an account, but never choose its password. One is generated,
  shown once, and marked `must_change_password`: it opens exactly one door, and that door is
  the change-password page. Until the owner replaces it the account reaches nothing else.
  This is what stops an administrator-set password from being a password the administrator
  knows for the life of the account.
- Administrators sign in at a separate page, `/admin/login`. It is a separate *door*, not a
  separate mechanism: same credential check, same signed cookie, same role read from the
  database. It cannot grant the role, and it answers a valid operator's credentials with the
  same sentence it gives a wrong password — otherwise the page would be an oracle for which
  accounts are administrators. No cookie is set on that path.
- A user may read only their own orders and predictions. Ownership is filtered in the
  query, not asserted after the fetch.
- Every input arriving from the browser is validated by a Pydantic model at the route
  boundary before it reaches the feature pipeline, the ORM, or the model.
- SQLAlchemy is used with bound parameters throughout. There is no string-built SQL.
- CORS is not enabled. The UI is server-rendered from the same origin, so there is no
  cross-origin case to permit.
- The app binds `127.0.0.1` by default. It has no TLS termination, no rate limiting, and
  no account-recovery flow; it is not built to face the public internet, and the README
  says so.

### What is not defended against

Stated plainly so nobody assumes otherwise.

**No brute-force lockout on login.** Nothing counts failed attempts or delays a repeat, so
an attacker with a candidate list is limited only by bcrypt's own cost.

**No audit log of model promotions.** Retraining is recorded in `training_runs` with the
administrator who triggered it and whether the guard allowed the promotion; cost-model edits
are append-only rows in `decision_config` carrying `updated_by` and `updated_at`; and role
changes are in `role_changes` naming both parties. A *model* promotion made on its own from
the registry page is still not separately recorded, so "who promoted version 4" is
answerable only when version 4 was promoted by the retrain that produced it.

One item previously listed here has been closed, and by construction rather than by a check:
**an operator cannot poison the retraining set through the UI**, because retraining reads
`CHAINSIGHT_DATASET` — a file on the server — and nothing entered through the application
ever reaches the training data. `orders` and `predictions` are written by the app and read by
nothing that fits a model.

## Secrets

There are none in this repository, and there is nothing here that needs one beyond the
session secret and an optional Kaggle credential, both read from the environment. CI runs
with no secrets configured. If you find a credential in the history, report it as a
vulnerability — do not open an issue.
