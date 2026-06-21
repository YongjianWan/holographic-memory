# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Migration v4: added `merged_into` column in `facts` table for soft-delete/supersession of consolidated facts, keeping original facts and relations fully auditable.
- reactivation logic in `add_fact`: automatically clears `merged_into` to reactivate a fact if the same exact content is inserted again.
- Integration tests in `tests/test_consolidation.py` verifying that soft-deleted facts are fully hidden from all 9 query/read paths, and that reactivation works.

### Changed
- Refactored `MemoryStore.consolidate_facts` to perform `UPDATE` (setting `merged_into` to the target consolidated fact ID) instead of physical `DELETE` of source facts.
- Updated all 9 read paths (`search_facts`, `list_facts`, `_find_consolidation_candidates`, `_fetch_facts`, `probe`, `related`, `reason`, `contradict`, and FTS5 JOIN) to strictly filter out superseded facts (`merged_into IS NULL`).
- Decommissioned the HRR ranking leg from `FactRetriever.search` RRF fusion, simplifying search to a 2-way FTS5 + Jaccard RRF fusion. This decision was based on real-world A/B testing on a 343-fact corpus showing HRR is noise for unmatched queries and redundant for matched ones.
- Removed A/B testing logs/instrumentation and the corresponding `test_rrf_ab_testing_logs` unit test.

- RRF (Reciprocal Rank Fusion) based `FactRetriever.search` combining FTS5, Jaccard token overlap, and HRR vector similarity using rank positions instead of raw scores.
- Multiplicative trust/recency boosts centered at 1.0 (±10% for trust).
- Graceful fallback to FTS5 + Jaccard RRF when numpy is unavailable.
- `MemoryStore.normalize_entities()` for merging fragmented entity variants (e.g. "K2.7" / "K2_7") into canonical entities with aliases; canonical selection prefers the most specific name (digits/punctuation/length) to avoid collapsing into vague forms.
- Numeric/date/version signature gate in entity clustering: "K2" and "K2.7" (series vs version) are no longer merged even when string similarity is high.
- Tightened default entity normalization thresholds (edit 0.85 / token 0.9) to further reduce false merges while still catching spacing/punctuation variants.
- Schema migration framework with `schema_version` table, automatic baseline detection for legacy databases, and pre-migration `.db.bak.v{n}` backups (WAL checkpoint before copy; foreign keys disabled during migrations and re-enabled/check afterwards).
- Migration v2: added `documents` table and nullable `facts.source_doc_id` foreign key (ON DELETE SET NULL) for storing source documents alongside extracted facts.
- Migration v3: added `documents.text_hash` with UNIQUE index for raw-text deduplication.
- `MemoryStore.retain_document(raw_text, source, category, extractor)`: stores the original article, deduplicates by SHA256 hash, and extracts atomic facts via a pluggable extractor.
- `FactExtractor` protocol with `_LocalFallbackExtractor` (sentence split, marked as fallback) and `_LLMExtractor` (injected `model_call`, no SDK dependency in core).
- `fact_store(action='retain')` tool for retaining raw documents from the agent tool surface.
- `fact_store` tool `normalize` action to trigger entity normalization.
- Write-time near-duplicate detection in `add_fact` using FTS5 coarse retrieval + Jaccard token overlap; merges wording variants before INSERT.
- `near_duplicate_threshold` plugin config option (default `0.8`) to tune write-time dedup sensitivity.
- Local content specificity scoring when merging duplicates: prefers content with more linked entities and numeric/date/version details.
- HRR capacity warning in `add_fact` / `_merge_into` when a single fact bundles more than `hrr_dim / 4` content items + entities; uses tiktoken when available for CJK text and falls back to the same whitespace split used by HRR encoding.
- `eval_retain_quality.py` diagnostic script for measuring extraction granularity, estimated LLM token cost, and HRR SNR warnings against a real document.
- `batch_retain_eval.py` for scanning a directory of `.txt`/`.md`/`.docx`/`.pdf` files, running `retain_document` on each, and producing aggregate granularity / token-cost / SNR-warning statistics.
- Document chunking in `retain_document`: long documents are split at paragraph/sentence boundaries before extraction so LLM prompts stay within context windows; default `max_chunk_tokens=6000`, configurable via `retain_max_chunk_tokens`.
- Hardened `_LLMExtractor` prompt with explicit atomicity rules, Chinese-aware splitting instructions, and good/bad examples.
- Unit tests for RRF search, entity normalization, and write-time dedup under `tests/`.
- `tests/conftest.py` with minimal stubs for hermes internal modules so tests can run standalone.
- `AGENTS.md`, `PATCHES.md`, and scaffold files (`TECH_DEBT.md`, `SESSION.md`, `SOUL.md`) documenting architecture, decisions, and debt.

### Fixed
- Aligned HRR query encoding in search with the fact vector's content component: query text is now `bind(encode_text(...), ROLE_CONTENT)` before comparison, matching the pattern used in `probe()`.
- Fixed `_resolve_entity` alias lookup: SQLite `LIKE` treated `_` and `%` as wildcards, causing incorrect entity matches (e.g. "K2_7" matching "K2.7"). Now uses case-insensitive equality for names and escaped LIKE for aliases.

### Changed
- Removed `fts_weight`, `jaccard_weight`, and `hrr_weight` configuration options and constructor parameters.
- `__init__.py` no longer reads `hrr_weight` from plugin config.

### Fixed
- Migration framework now guarantees `PRAGMA foreign_keys = ON` on every `_init_db` path by removing the early `return` inside the migration `try` block and using a guarded `if current < target:` body; added `test_document_delete_cascades_to_source_doc_id` to verify `ON DELETE SET NULL` is actually enforced.
- Eliminated unstable raw-score weighting of incomparable signals (FTS5 rank, Jaccard ratio, HRR cosine).
