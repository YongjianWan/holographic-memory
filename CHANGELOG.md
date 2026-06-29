# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### HRR bank sharding and default search

- **HRR bank sharding**: `store._rebuild_bank` now writes `cat:{category}|doc:{doc}|shard:{nn}`
  banks instead of one flat `cat:{category}` bundle, per the
  `category_source_doc_shard256` scheme measured in
  `reports/hrr_bank_partition_audit.md`. `probe()` resolves the shards
  covering an entity's own facts and bundles only those before unbinding,
  instead of unbinding against the whole (noisier) category bank. No scope
  schema introduced. Live DB resharded via
  `tests/scripts/run_hrr_bank_resharding.py --yes`: `project` bank max
  fact_count dropped from 2083 (SNR 0.701) to 256 (SNR 2.0), 0 banks over
  capacity.
- **Default search keeps 3-way RRF**: added
  `tests/scripts/run_rrf_ab_audit.py` and `reports/rrf_ab_audit.md` for a
  read-only fixed-query comparison of FTS5+Jaccard+HRR vs FTS5+Jaccard
  ablation. The live snapshot showed median top5 overlap 0.8 and 12/20 top1
  changes, so HRR materially affects ranking. Per user decision, HRR remains
  in default `FactRetriever.search()` as the only local weak semantic/structural
  signal under the no-embedding-service constraint.
- **RRF A/B audit script fixes**: `tests/scripts/run_rrf_ab_audit.py` now runs
  standalone outside hermes (hermes stubs injected) and applies the same query
  expansion as `FactRetriever.search()`, so the audit mirrors current default
  search behavior. Regenerated `reports/rrf_ab_audit.{json,md}`.
- `_hrr_quality_audit.py` diagnostic script for side-by-side 3-way vs 2-way RRF evaluation on a live database.
- RRF (Reciprocal Rank Fusion) based `FactRetriever.search` combines FTS5, Jaccard token overlap, and HRR vector similarity using rank positions instead of raw scores.
- Multiplicative trust/recency boosts centered near 1.0 and bounded to roughly
  ±10%, so secondary signals cannot overpower RRF relevance.
- Graceful fallback to FTS5 + Jaccard RRF when numpy is unavailable.

#### Provenance and read-only audit tooling

- **Recall audit**: added `tests/scripts/run_recall_audit.py`, a read-only
  SQLite-backup based audit that runs synonym/jargon probes against the default
  3-way RRF ranking (without `search()` side effects) and reports HITs vs MISSes.
  Each probe phrases a known fact with a different term, so a MISS surfaces a
  lexical recall gap to hand-label (黑话 / 通用同义 / absent) — the seed source
  for the lexicon and the input to the word2vec cost/benefit question. Pass a
  real probe set with `--probes`; the built-in `SEED_PROBES` is illustrative only.
  Unit tests: `tests/test_recall_audit.py`.
- **Provenance audit report**: added `tests/scripts/run_provenance_audit.py`, a
  read-only SQLite-backup based report for `fact_provenance` coverage. The
  current live snapshot writes `reports/provenance_audit.md` / `.json` and
  shows `2195 active / 1162 known provenance / 1033 legacy_unknown`, with 2
  multi-document active facts proving merge provenance is visible without
  treating `source_doc_id` as complete provenance.
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
- HRR bank partition audit (`tests/scripts/run_hrr_bank_partition_audit.py`)
  that snapshots the live DB and compares category, source-doc, document-family,
  and source-doc shard partitions without writing schema or memory banks.
- Read-only scope gate audit that separates inserted rows, unique fact IDs,
  merge targets/events, extraction-meta candidates, Gate A sampling, and
  content-derived multi-label scope distribution without relying on
  `source_doc_id`.

#### Data quality and extraction guardrails

- Dirty-fact human review, batch 1: of the 49 review candidates, 34 came
  from the project-document import (doc 15-25). 30 verdicted `keep` under
  §6.4; 4 verdicted `dirty` and soft-deleted via
  `tests/scripts/run_apply_dirty_fact_verdicts.py --yes` (backup-first,
  `merged_into=999999`) because their content was independently wrong, not
  because of where they came from — two (`1001480`, `1001455`) asserted a
  "current" HRR bank fact_count/SNR snapshot already falsified by the same
  day's resharding, two (`1001935`, `1001953`) were trigger-conditioned
  to-dos ("rerun Gate A/B after the DB changes") miscategorized as facts
  per §6.1. The remaining 15 candidates (doc=None, legacy Hindsight-era,
  flagged `long_atomicity_check`) are unrelated history debt left pending
  for a separate review pass.
- Dirty-fact human review, batch 2: the remaining 15 doc=None legacy
  Hindsight-era candidates were human-reviewed and verdicted `keep`. They are
  valid historical architecture/configuration/migration facts, but too coarse
  as atomic facts; this is tracked as a legacy granularity debt rather than
  dirty data. The dirty candidate report now records `45 keep / 4 dirty / 0
  pending`. No additional soft-delete/write-to-live-DB action was needed.
- Local post-parse guardrails for LLM extraction output, rejecting common leaks
  such as dialogue state, sleep reminders, ammunition metaphors, memory slot
  chatter, motive inferences, and extractor self-talk before facts reach
  storage.
- Retain extraction now reports per-chunk provider failures instead of
  silently returning zero facts; orphan documents remain retryable.

#### Schema migrations

- **Migration v11**: added local `semantic_equivalence_groups` and
  `semantic_equivalence_terms` tables for importing trained synonym/equivalence
  lexicons. Search expands queries from this SQLite table before FTS5/Jaccard/HRR
  ranking; this is a local lookup, not an embedding service or daemon.
- **Migration v10**: add forward-only `fact_provenance` with
  `(fact_id, doc_id, source_fact_id)` uniqueness. New document retains record
  origin/merge provenance; legacy facts are not backfilled because historical
  merge direction was flattened by the `999999` soft-delete marker.
- **Migration v8**: add `facts.last_accessed_at`, separating factual recall time from content updates and feedback trust.
- **Migration v7**: lazy process-internal garbage collector (`memory_gc.py`) with `gc_log` table. Runs at `initialize()` and `on_session_end()`; hermes-away intervals are backfilled by the timestamp check on startup.
- Initial v7 trust-decay implementation, superseded in v8 by query-time recency derived from `last_accessed_at`.
- **Migration v6**: rebuild `facts_fts` to index **all** facts (including soft-deleted `merged_into IS NOT NULL`), fixing the v5 active-only coverage bug that broke reactivation.
- **Migration v5**: added trigram tokenizer to `facts_fts` for native CJK/Chinese text search.
- **Migration v4**: added `facts.merged_into` for soft-deletion/supersession during consolidation.
- **Migration v3**: added `documents.text_hash` with UNIQUE index for raw-text deduplication.
- **Migration v2**: added `documents` table and nullable `facts.source_doc_id` foreign key.
- **Migration v1**: formalized `hrr_vector` column addition.
- Schema migration framework with `schema_version` table, automatic baseline detection, and pre-migration `.db.bak.v{n}` backups.
- New plugin config keys: `gc_interval_days`, `gc_decay_max_days`, `gc_decay_floor`.

#### Core retrieval, ranking, and entity features

- Fact retrieval/list outputs now include a read-time `provenance` summary.
  Facts with no provenance rows return derived `legacy_unknown` without
  writing placeholder rows.
- Successful `search` / `probe` / `related` / `reason` retrievals now increment `retrieval_count` and refresh `last_accessed_at`.
- Cross-process write serialization for `add_fact` using `BEGIN IMMEDIATE`; concurrent near-duplicate writes are now checked and inserted atomically.
- GC uses a non-blocking SQLite writer claim: if another connection owns the
  write lock, maintenance returns `busy` without writing `gc_log`; a later
  retry can complete. Covered by
  `TestGarbageCollectorUnit::test_two_connections_busy_skip_writes_no_log_then_retries`.
- `MemoryStore.normalize_entities()` for merging fragmented entity variants into canonical entities with aliases.
- Numeric/date/version signature gate in entity clustering to block hierarchical merges (e.g. "K2" vs "K2.7").
- `MemoryStore.retain_document(raw_text, source, category, extractor)`: stores the original article, deduplicates by SHA256 hash, extracts atomic facts via a pluggable extractor, and chunks long documents at paragraph/sentence boundaries.
- `FactExtractor` protocol with `_LocalFallbackExtractor` and `_LLMExtractor`.
- `fact_store(action='retain')` tool for retaining raw documents.
- `fact_store(action='normalize')` tool for entity normalization.
- `fact_store(action='consolidate')` tool for LLM-driven semantic consolidation.
- Write-time near-duplicate detection in `add_fact` using FTS5 coarse retrieval + Jaccard token overlap.
- `near_duplicate_threshold` plugin config option (default `0.8`).
- Local content specificity scoring when merging duplicates.
- HRR capacity warning when a single fact bundles too many content items + entities.
- Pure-Python zero-dependency CJK character segmenter (`tokenize_text` in `holographic.py`).

#### Evaluation and quality scripts

- `eval_retain_quality.py` for measuring extraction granularity and token cost.
- `batch_retain_eval.py` for scanning a directory of documents and producing aggregate statistics.

#### Tests and documentation

- Integration tests verifying soft-deleted facts are hidden from all read paths and reactivation works.
- `AGENTS.md`, `TECH_DEBT.md`, `SESSION.md`, `ROADMAP.md`, and `docs/README.md` documenting architecture, decisions, and debt.
- `AGENTS.md` §阅读顺序 now points new agents at the ROADMAP "防重提清单" before
  proposing new work, to cut the cost of re-raising vetoed directions (P2 / scope
  / embedding / resident workers).
- Merged the 2026-06-29 decision patch (`docs/决议补丁_lexicon与word2vec射程.md`)
  into the current doc structure (宪法.md slow-spec, ROADMAP, SESSION); the patch
  file is kept with an "已并入" banner as a merge trail.

#### Decision records

- Project's own meta-documents (宪法.md, AGENTS.md,
  CHANGELOG.md, ROADMAP.md, SESSION.md, TECH_DEBT.md) may be retained into
  Holo as atomized facts; the prior §6.3 exclusion only bars storing their
  raw verbatim text as instructions/changelog entries, not running them
  through the same atomic-extraction pipeline as any other document.
  Recorded as `docs/宪法.md` §6.4.
- Retrieval remains grep/FTS/Jaccard-first. Missing
  embedding-based semantic recall is an accepted local/no-daemon tradeoff, not
  current technical debt; future recall improvements should prefer query
  reformulation and candidate control before any vector service.
- Explicit validity / expiration semantics are a real
  lifecycle gap, but deferred to the future extractor-profile phase after the
  current corpus is cleaned and Gate A/B is rerun.
- P2 shared-entity graph edges vetoed after real-data measurement. On 380 active facts, entity avg fan-out was 0.811, 94% of entities hung on a single fact, and only 29 fact pairs shared any entity. Recorded in [ROADMAP.md](ROADMAP.md) with restart conditions.
- **Gate A human audit passed and officially GO (2026-06-24)**: a stratified sample of 50 facts was human-reviewed; 40 PASS / 10 FAIL yielded an 80.0% real GO rate. Rules straightened: meeting speech events count as objective event records (PASS, including 1000901/1000818), decontextualized subjectless generalizations (970) count as FAIL, and 1000023 ("do not show zero in report PPT") is locked as a cross-version presentation rule (PASS). Gate A is now officially passed.
- **Gate B first audit judged NO-GO (2026-06-24)**: `scope` is moved to **veto / wait-for-evidence** status (isomorphic to P2). Reasons: (1) the classifier ruler is not trustworthy (rough bucketing mixed with noise), and (2) no real query has been observed that can only be answered with domain filtering. Restart condition: a real usage query that is impossible without domain filtering (demand-driven), not "more data" or "taxonomy refactoring".
- **Control Group baseline locked at 27 facts**: the previous shrink from 27 to 26 was root-caused as an earlier assistant manually removing Fact ID 40 ("algorithm scores are not limited to five, maybe ten or twenty a day") from `_control_fact_ids.txt` to manufacture 100% consistency. ID 40 has been restored; the Control Group is now physically fixed at the original 27 facts to measure evaluator measurement noise (~96.3% consistency). Manual baseline adjustment is prohibited.
- **Evaluator jitter and over-extraction rate accepted**: stop chasing away the ~3.7% jitter on the evaluator's subjective/objective boundary and the ~26.6% over-extraction rate; rely on the exit gate instead. Focus on physically locking and aligning the baseline.
- **Scope irreversibility gate**: do not add `facts.scope`, `fact_scopes`, or scope-driven bank schema until a real domain-filtering need appears.
- **`source_doc_id` boundary**: `source_doc_id` is single-value attribution, not complete provenance; after a merge it cannot be used to derive full origin.
- **Provenance decoupled from scope Gate B**: `fact_provenance` exists to make post-merge origin auditable, not to enable scope domain filtering. v10 is landed and does not wait for Gate B.
- **Legacy provenance not backfilled**: the historical merge chain has been flattened by the `999999` soft-delete marker; old active facts having no provenance rows is an honest state. `legacy_unknown` must be derived at read time; writing placeholder rows is prohibited.
- **Validity/expiration semantics deferred**: `trust` decay only means "older = less certain", not a hard expiration point. "Due this week"-style information belongs to a future extractor-profile / lifecycle design; do not write schema for it now.
- **Fact / noise discrimination rule**: the LLM extraction prompt must objectively distinguish facts from conversational noise, rejecting pure social fluff, chat-state descriptions, consolation, and metaphorical statements.
- **P1-4 positioning and red line finalized**: cross-topic chaining is induction-only (extract structure, not people); deduction and abduction (especially motive inference) are forbidden. A hard gate of `source_fact_ids >= 2` is required. Acknowledge the generic model quality ceiling; do not introduce embedding, self-trained models, or any daemon dependency. Gated on Gate A audit.
- **Production DB test discipline**: any action that writes the real `memory_store.db` must first create a backup and use that backup as the before/after diff baseline.
- **Synonym/jargon lexicon spec (2026-06-29)**: the `semantic_equivalence_*`
  tables double as a synonym/jargon lexicon. Jargon synonym arrows can only be
  filled by the LLM reading your own corpus (word2vec and general thesauri are
  blind to self-coined terms), so the lexicon is a *byproduct* of the existing
  P1-2 / P1-4 LLM pass — no new component, no new daemon. It is a derived
  projection (not a fact), gated by inheriting the P1-2 / P1-4 gates. Recorded
  in `docs/宪法.md` slow-spec section. Named explicitly **not** an edge, to avoid
  reviving the vetoed P2.
- **word2vec射程 clarified, suspended, not ratified (2026-06-29)**: the two walls
  used to veto pretrained word vectors (word2vec / GloVe / fastText) — "needs a
  resident embedding service" and "needs heavy external resources" — both fall:
  a one-shot vector lookup is shutdown-is-a-file with no startup sequence (the
  Hindsight knife's edge is *residency*, not file size). The only red line still
  standing is unratified and constitution-layer: whether "no semantic recall"
  means "no daemon" or "Holo's semantic judgment must not depend on external
  trained sediment / the recall chain must be reproducible". Even if relaxed, it
  stays gated on recall-audit numbers. Status: suspended (neither vetoed nor
  greenlit). Recorded in [ROADMAP.md](ROADMAP.md).
- **P2 restart trigger gets a data scale (2026-06-29)**: P2's unfreeze condition
  is now "a real query only a graph can answer, **or fan-out ≥ 1.5 / shared
  pairs rising materially**". Trigger on data, never on a schedule. A working
  lexicon may further *defer* P2 by collapsing pseudo-fragmentation.
- **Recall audit is the only non-gated next step (2026-06-29)**: it simultaneously
  (1) measures the jargon-vs-common-synonym split among misses, (2) hand-labels
  jargon pairs as lexicon seeds without waiting on P1-2, and (3) yields a P1-2
  validation baseline. Everything downstream (lexicon production, word2vec
  decision) queues behind it. Recorded in [SESSION.md](SESSION.md) next-step 0.

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
- `fact_store(action='consolidate')` no longer reports a misleading "DEEPSEEK_API_KEY
  or OPENAI_API_KEY not found" error when no LLM is available. `_resolve_model_call`
  is intentionally pinned to DeepSeek and never reads `OPENAI_API_KEY`, so the old
  message sent users down a dead end. The error now names only the DeepSeek route.
  Regression test: `tests/test_model_routing.py::test_consolidate_without_llm_reports_deepseek_only`.

### Removed

- `_auto_extract_facts` and the `on_session_end` regex extraction path.
- `auto_extract` plugin config key.
- A/B testing logs/instrumentation and the corresponding unit test.
