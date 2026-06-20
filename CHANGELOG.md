# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- RRF (Reciprocal Rank Fusion) based `FactRetriever.search` combining FTS5, Jaccard token overlap, and HRR vector similarity using rank positions instead of raw scores.
- Multiplicative trust/recency boosts centered at 1.0 (±10% for trust).
- Graceful fallback to FTS5 + Jaccard RRF when numpy is unavailable.
- Unit tests for RRF search under `tests/test_retrieval_rrf.py`.
- `tests/conftest.py` with minimal stubs for hermes internal modules so tests can run standalone.
- `AGENTS.md` documenting architecture constraints, development rules, and roadmap.

### Fixed
- Aligned HRR query encoding in search with the fact vector's content component: query text is now `bind(encode_text(...), ROLE_CONTENT)` before comparison, matching the pattern used in `probe()`.

### Changed
- Removed `fts_weight`, `jaccard_weight`, and `hrr_weight` configuration options and constructor parameters.
- `__init__.py` no longer reads `hrr_weight` from plugin config.

### Fixed
- Eliminated unstable raw-score weighting of incomparable signals (FTS5 rank, Jaccard ratio, HRR cosine).
