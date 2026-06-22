# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Lazy process-internal garbage collector (`memory_gc.py`) with `gc_log` table (migration v7). Runs trust-decay GC at `initialize()` and `on_session_end()`; hermes-away intervals are backfilled by the timestamp check on startup.
- Trust decay: `trust_score` is multiplied by a recency factor `clamp(1 - days/365, 0.1, 1.0)` based on `updated_at` (or `created_at`) for all active facts during GC.
- New plugin config keys: `gc_interval_days`, `gc_decay_max_days`, `gc_decay_floor`.
- Migration v6: rebuild `facts_fts` to index **all** facts (including soft-deleted `merged_into IS NOT NULL`), fixing the v5 active-only coverage bug that broke reactivation.
- `_hrr_quality_audit.py` diagnostic script for side-by-side 3-way vs 2-way RRF evaluation on a live database.
- RRF (Reciprocal Rank Fusion) based `FactRetriever.search` combining FTS5, Jaccard token overlap, and HRR vector similarity using rank positions instead of raw scores.
- Multiplicative trust/recency boosts centered at 1.0 (±10% for trust).
- Graceful fallback to FTS5 + Jaccard RRF when numpy is unavailable.
- `MemoryStore.normalize_entities()` for merging fragmented entity variants into canonical entities with aliases.
- Numeric/date/version signature gate in entity clustering to block hierarchical merges (e.g. "K2" vs "K2.7").
- Schema migration framework with `schema_version` table, automatic baseline detection, and pre-migration `.db.bak.v{n}` backups.
- Migration v1: formalized `hrr_vector` column addition.
- Migration v2: added `documents` table and nullable `facts.source_doc_id` foreign key.
- Migration v3: added `documents.text_hash` with UNIQUE index for raw-text deduplication.
- Migration v4: added `facts.merged_into` for soft-deletion/supersession during consolidation.
- Migration v5: added trigram tokenizer to `facts_fts` for native CJK/Chinese text search.
- Pure-Python zero-dependency CJK character segmenter (`tokenize_text` in `holographic.py`).
- `MemoryStore.retain_document(raw_text, source, category, extractor)`: stores the original article, deduplicates by SHA256 hash, extracts atomic facts via a pluggable extractor, and chunks long documents at paragraph/sentence boundaries.
- `FactExtractor` protocol with `_LocalFallbackExtractor` and `_LLMExtractor`.
- `fact_store(action='retain')` tool for retaining raw documents.
- `fact_store(action='normalize')` tool for entity normalization.
- `fact_store(action='consolidate')` tool for LLM-driven semantic consolidation.
- Write-time near-duplicate detection in `add_fact` using FTS5 coarse retrieval + Jaccard token overlap.
- `near_duplicate_threshold` plugin config option (default `0.8`).
- Local content specificity scoring when merging duplicates.
- HRR capacity warning when a single fact bundles too many content items + entities.
- `eval_retain_quality.py` for measuring extraction granularity and token cost.
- `batch_retain_eval.py` for scanning a directory of documents and producing aggregate statistics.
- Integration tests verifying soft-deleted facts are hidden from all read paths and reactivation works.
- `AGENTS.md`, `TECH_DEBT.md`, `SESSION.md`, `SOUL.md`, `ROADMAP.md`, and `docs/README.md` documenting architecture, decisions, and debt.

### Changed

- Refactored `MemoryStore.consolidate_facts` to use soft-deletion (`merged_into`) instead of physical `DELETE`.
- All read paths now strictly filter out superseded facts (`merged_into IS NULL`).
- Tightened default entity normalization thresholds (edit 0.85 / token 0.9).
- Removed `fts_weight`, `jaccard_weight`, and `hrr_weight` configuration options; RRF no longer uses raw-score weights.
- `__init__.py` no longer reads `hrr_weight` from plugin config.

### Fixed

- Split `store.py` into `entities.py` (extraction/resolution/name matching) and `consolidation.py` (candidate discovery and LLM-driven merging). `store.py` now holds storage orchestration and thin forwarding methods.
- Added missing `Callable` import in `__init__.py` (used by `_resolve_model_call` annotation).
- `_load_plugin_config` and `save_config` no longer swallow exceptions silently; they now log warnings/errors.
- `FactRetriever.probe`, `related`, and `reason` no longer perform full-table HRR scans. They pre-filter candidates by linked entities and cap the scan size at 1000 facts with a warning.
- `HolographicMemoryProvider.shutdown` now explicitly calls `store.close()` before dropping the reference.
- `MemoryStore.close()` now executes `PRAGMA wal_checkpoint(FULL)` before closing.
- `_resolve_entity` alias lookup now escapes SQLite `LIKE` wildcards so "K2_7" no longer matches "K2.7".
- Aligned HRR query encoding in search with the fact vector's content component.
- Migration framework guarantees `PRAGMA foreign_keys = ON` on every `_init_db` path.

### Removed

- `_auto_extract_facts` and the `on_session_end` regex extraction path.
- `auto_extract` plugin config key.
- A/B testing logs/instrumentation and the corresponding unit test.
