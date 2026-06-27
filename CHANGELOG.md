# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Decision record**: retrieval remains grep/FTS/Jaccard-first. Missing
  embedding-based semantic recall is an accepted local/no-daemon tradeoff, not
  current technical debt; future recall improvements should prefer query
  reformulation and candidate control before any vector service.
- **Decision record**: explicit validity / expiration semantics are a real
  lifecycle gap, but deferred to the future extractor-profile phase after the
  current corpus is cleaned and Gate A/B is rerun.
- Current DB ledger script (`tests/scripts/run_current_db_ledger.py`) that uses
  SQLite's backup API to snapshot the live memory store before read-only
  auditing. The generated report records current fact counts, document
  distribution, soft-delete counts, memory bank pressure, and candidate dirty
  facts without mutating the source DB.
- Project-document retain script (`tests/scripts/run_retain_project_docs.py`)
  for importing the repository's canonical docs into the live memory store.
  It supports dry-run listing, requires an LLM API key for writes, and creates
  a SQLite backup before mutating the live DB.
- Dirty/meta candidate report script
  (`tests/scripts/run_dirty_fact_candidates.py`) that snapshots the live DB,
  scans active facts read-only, and writes manual-review JSON/Markdown reports
  without mutating facts, schema, or provenance.
- Dirty verdict apply script (`tests/scripts/run_apply_dirty_fact_verdicts.py`)
  for backup-first soft deletion of confirmed dirty facts via
  `merged_into=999999`, with dry-run reports and category bank rebuilds.
- Local post-parse guardrails for LLM extraction output, rejecting common leaks
  such as dialogue state, sleep reminders, ammunition metaphors, memory slot
  chatter, motive inferences, and extractor self-talk before facts reach
  storage.
- Read-only scope gate audit that separates inserted rows, unique fact IDs,
  merge targets/events, extraction-meta candidates, Gate A sampling, and
  content-derived multi-label scope distribution without relying on
  `source_doc_id`.
- Retain extraction now reports per-chunk provider failures instead of
  silently returning zero facts; orphan documents remain retryable.
- Migration v10: add forward-only `fact_provenance` with
  `(fact_id, doc_id, source_fact_id)` uniqueness. New document retains record
  origin/merge provenance; legacy facts are not backfilled because historical
  merge direction was flattened by the `999999` soft-delete marker.
- Fact retrieval/list outputs now include a read-time `provenance` summary.
  Facts with no provenance rows return derived `legacy_unknown` without
  writing placeholder rows.
- Migration v8: add `facts.last_accessed_at`, separating factual recall time from content updates and feedback trust.
- Successful `search` / `probe` / `related` / `reason` retrievals now increment `retrieval_count` and refresh `last_accessed_at`.
- Cross-process write serialization for `add_fact` using `BEGIN IMMEDIATE`; concurrent near-duplicate writes are now checked and inserted atomically.
- GC uses a non-blocking SQLite writer claim: if another connection owns the
  write lock, maintenance returns `busy` without writing `gc_log`; a later
  retry can complete. Covered by
  `TestGarbageCollectorUnit::test_two_connections_busy_skip_writes_no_log_then_retries`.
- **Decision record**: P2 shared-entity graph edges vetoed after real-data measurement. On 380 active facts, entity avg fan-out was 0.811, 94% of entities hung on a single fact, and only 29 fact pairs shared any entity. Recorded in [ROADMAP.md](ROADMAP.md) with restart conditions.
- Lazy process-internal garbage collector (`memory_gc.py`) with `gc_log` table (migration v7). Runs at `initialize()` and `on_session_end()`; hermes-away intervals are backfilled by the timestamp check on startup.
- Initial v7 trust-decay implementation, superseded in v8 by query-time recency derived from `last_accessed_at`.
- New plugin config keys: `gc_interval_days`, `gc_decay_max_days`, `gc_decay_floor`.
- Migration v6: rebuild `facts_fts` to index **all** facts (including soft-deleted `merged_into IS NOT NULL`), fixing the v5 active-only coverage bug that broke reactivation.
- `_hrr_quality_audit.py` diagnostic script for side-by-side 3-way vs 2-way RRF evaluation on a live database.
- RRF (Reciprocal Rank Fusion) based `FactRetriever.search` combining FTS5, Jaccard token overlap, and HRR vector similarity using rank positions instead of raw scores.
- Multiplicative trust/recency boosts centered near 1.0 and bounded to roughly
  ±10%, so secondary signals cannot overpower RRF relevance.
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
- `AGENTS.md`, `TECH_DEBT.md`, `SESSION.md`, `ROADMAP.md`, and `docs/README.md` documenting architecture, decisions, and debt.

### Changed

- Refreshed `AGENTS.md` against the current constitution/session posture:
  migration status now says v10, P2 is documented as veto/frozen, periodic
  maintenance is described as any-live-instance with SQLite locking, and P1-4
  reflects Gate A GO while preserving its implementation guardrails.
- Realigned status documentation after the checkpoint commit: `SESSION.md`
  is now the single current-state source, `ROADMAP.md` reflects the current
  `schema v10` ledger / Gate A GO / Gate B NO-GO posture, and `TECH_DEBT.md`
  separates source provenance from scope-gate decisions.
- Consolidated assistant-facing documentation: `AGENTS.md` is now the single
  work entrypoint, project discipline formerly delegated to `SOUL.md` is folded
  into `AGENTS.md` / `docs/宪法.md`, including the external SOUL priority stack,
  Linus engineering lens, tool discipline, and authorization boundary.
  `docs/README.md` now points to the archived design documents under
  `docs/achieve/`.
- `retain_document` now delays category bank rebuilds during batch fact writes
  and rebuilds each changed category once after the document batch completes,
  avoiding repeated full-bank rebuilds for every extracted fact.
- LLM-backed retain now uses Hermes' centralized credential router while
  remaining pinned to DeepSeek (`deepseek-v4-flash` by default). It never
  silently substitutes the main provider; direct DeepSeek environment
  variables remain a standalone-script fallback.
- Restored real-data ingestion and manual library review as a hard gate before
  any category/scope schema design. The existing 50-fact review proves
  structural value, but not single-scope separability.
- RRF derives recency at query time from `last_accessed_at`; the derived score is not persisted and cannot become stale.
- `add_fact`, `update_fact`, `normalize_entities`, and each consolidation
  cluster now own a single atomic transaction covering facts, entity links,
  HRR vectors, and category banks.
- Query-time recency is mapped from its raw `0.1..1.0` freshness signal to a
  bounded `0.9..1.0` multiplier.
- Shutdown checkpointing now uses `PRAGMA wal_checkpoint(PASSIVE)` to avoid waiting on readers in multi-process use.
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
