# Architecture decision records

One file per decision that would be expensive to reverse or surprising to inherit. Each
records what was decided, what it cost, and — where the project measured it — the number that
settled the argument.

The format is deliberately short. An ADR nobody reads is worth less than a paragraph
somebody does.

| | decision | status |
|---|---|---|
| [0001](0001-build-from-one-curriculum.md) | Build from one curriculum, and enforce it | accepted |
| [0002](0002-split-by-time.md) | Split by time, not at random | accepted |
| [0003](0003-drop-post-dispatch-columns.md) | Drop every post-dispatch column, and show the cost | accepted |
| [0004](0004-do-not-model-margin.md) | Do not model margin; compute it | accepted |
| [0005](0005-select-on-ranking.md) | Select the production model on ranking, not accuracy | accepted, supersedes part of 0002's rationale |
| [0006](0006-derive-the-threshold.md) | Derive the decision threshold from costs | accepted |
| [0007](0007-json-registry.md) | A JSON registry with a compare-then-promote guard, not MLflow | accepted |
| [0008](0008-server-rendered-sqlite.md) | Server-rendered pages over SQLite, not an SPA | accepted |
| [0009](0009-no-default-session-secret.md) | No default session secret | accepted, amended for role management |
| [0010](0010-csrf-tokens.md) | CSRF tokens, checked globally rather than per route | accepted |
| [0011](0011-one-set-of-books.md) | Keep the threshold and the ranking on one set of books | accepted, corrects 0006 |
| [0012](0012-name-the-currency.md) | Name the currency, once, for the whole deployment | accepted |
| [0013](0013-count-attempts-per-address.md) | Count attempts per address, not per account | accepted, closes an item in SECURITY.md |
