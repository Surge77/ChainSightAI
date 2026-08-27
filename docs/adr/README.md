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
| [0009](0009-no-default-session-secret.md) | No default session secret | accepted |
