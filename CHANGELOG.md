# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `scripts/fetch_data.py` and `data/dataset_manifest.json`: the dataset is downloaded into a
  gitignored directory and checked against a recorded SHA-256, row count and column count.
  The manifest also records that the file is latin-1 rather than UTF-8, that the archive's
  95 MB clickstream table is discarded because it shares no key with the order table, and
  that the licence is CC0-1.0.

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

[Unreleased]: https://github.com/Surge77/ChainSightAI/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Surge77/ChainSightAI/releases/tag/v0.1.0
