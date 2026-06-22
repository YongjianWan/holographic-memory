"""
SQLite-backed fact store with entity resolution and trust scoring.
Single-user Hermes memory store plugin.
"""

import logging
import math
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

try:
    from . import holographic as hrr
except ImportError:
    import holographic as hrr  # type: ignore[no-redef]

try:
    from . import consolidation
    from . import entities
    from . import memory_gc as gc_module
    from .extractors import FactExtractor, _LocalFallbackExtractor, _LLMConsolidator, _LLMExtractor, split_sentences
    from .store_migrations import _SCHEMA, _run_migrations, _text_hash
except ImportError:
    import consolidation  # type: ignore[no-redef]
    import entities  # type: ignore[no-redef]
    import memory_gc as gc_module  # type: ignore[no-redef]
    from extractors import FactExtractor, _LocalFallbackExtractor, _LLMConsolidator, _LLMExtractor, split_sentences  # type: ignore[no-redef]
    from store_migrations import _SCHEMA, _run_migrations, _text_hash  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

# Optional tiktoken for a more realistic content-item count in HRR capacity
# warnings. If unavailable we fall back to the same whitespace split used by
# encode_text(). The core package does not depend on tiktoken.
try:
    import tiktoken

    _CONTENT_ITEM_ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover - tiktoken is optional
    _CONTENT_ITEM_ENCODING = None


def _content_item_count(content: str) -> int:
    """Count discrete content items for HRR capacity estimation.

    Mirrors encode_text tokenisation when tiktoken is unavailable. When
    tiktoken is present we use its token count, which is much more meaningful
    for Chinese text where whitespace split would treat a whole sentence as one
    item.
    """
    if _CONTENT_ITEM_ENCODING is not None:
        return len(_CONTENT_ITEM_ENCODING.encode(content))
    return len(hrr.tokenize_text(content))


def _hard_split_text(text: str, max_tokens: int) -> list[str]:
    """Emergency split when a single sentence exceeds max_tokens."""
    chunks: list[str] = []
    while text:
        if _CONTENT_ITEM_ENCODING is not None:
            # Binary search the longest prefix that fits within the budget.
            low, high = 1, len(text)
            while low < high:
                mid = (low + high + 1) // 2
                if _content_item_count(text[:mid]) <= max_tokens:
                    low = mid
                else:
                    high = mid - 1
            split_at = low
        else:
            # Roughly 4 chars per token for CJK; 6 for Latin.
            split_at = max_tokens * 4
        chunk = text[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        text = text[split_at:].strip()
    return chunks


def _chunk_text(raw_text: str, max_tokens: int) -> list[str]:
    """Split a long document into LLM-friendly chunks.

    Splits first at paragraph boundaries, then at sentence boundaries, and only
    performs hard splits when a single sentence is still too long. Preserves as
    much context as possible while staying under the token budget.
    """
    if _content_item_count(raw_text) <= max_tokens:
        return [raw_text]

    paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    current_tokens = 0

    for para in paragraphs:
        para_tokens = _content_item_count(para)
        if para_tokens > max_tokens:
            # Flush whatever is currently buffered.
            if current:
                chunks.append(current)
                current = ""
                current_tokens = 0
            # Split oversized paragraph by sentence.
            for sent in split_sentences(para):
                sent_tokens = _content_item_count(sent)
                if sent_tokens > max_tokens:
                    if current:
                        chunks.append(current)
                        current = ""
                        current_tokens = 0
                    chunks.extend(_hard_split_text(sent, max_tokens))
                elif current_tokens + sent_tokens > max_tokens:
                    chunks.append(current)
                    current = sent
                    current_tokens = sent_tokens
                else:
                    current = f"{current} {sent}".strip() if current else sent
                    current_tokens += sent_tokens
        elif current_tokens + para_tokens > max_tokens:
            if current:
                chunks.append(current)
            current = para
            current_tokens = para_tokens
        else:
            current = f"{current}\n\n{para}".strip() if current else para
            current_tokens += para_tokens

    if current:
        chunks.append(current)
    return chunks


# Trust adjustment constants
_HELPFUL_DELTA   =  0.05
_UNHELPFUL_DELTA = -0.10
_TRUST_MIN       =  0.0
_TRUST_MAX       =  1.0
_FALLBACK_TRUST  =  0.25  # trust score for fallback-extracted facts

def _clamp_trust(value: float) -> float:
    return max(_TRUST_MIN, min(_TRUST_MAX, value))


def _tokenize(text: str) -> set[str]:
    """Segment CJK characters and alphanumeric words for Jaccard matching."""
    return set(hrr.tokenize_text(text))


def _snr(dim: int, n_items: int) -> float:
    """HRR signal-to-noise ratio for n_items bundled into dim dimensions."""
    if n_items <= 0:
        return float("inf")
    return math.sqrt(dim / n_items)


class MemoryStore:
    """SQLite-backed fact store with entity resolution and trust scoring."""

    def __init__(
        self,
        db_path: "str | Path | None" = None,
        default_trust: float = 0.5,
        hrr_dim: int = 1024,
        near_duplicate_threshold: float = 0.8,
        *,
        gc_interval_days: float = 7.0,
        gc_decay_max_days: float = 365.0,
        gc_decay_floor: float = 0.1,
    ) -> None:
        if db_path is None:
            from hermes_constants import get_hermes_home
            db_path = str(get_hermes_home() / "memory_store.db")
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_trust = _clamp_trust(default_trust)
        self.near_duplicate_threshold = max(0.0, min(1.0, near_duplicate_threshold))
        self.hrr_dim = hrr_dim
        self._hrr_available = hrr._HAS_NUMPY
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        self._gc = gc_module.GarbageCollector(
            self._conn,
            interval_days=gc_interval_days,
            decay_max_days=gc_decay_max_days,
            decay_floor=gc_decay_floor,
        )

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create tables, indexes, and triggers if they do not exist, then run migrations."""
        # Use the shared WAL-fallback helper so memory_store.db degrades
        # gracefully on NFS/SMB/FUSE-mounted HERMES_HOME (same issue as
        # state.db / kanban.db — see hermes_state._WAL_INCOMPAT_MARKERS).
        from hermes_state import apply_wal_with_fallback
        apply_wal_with_fallback(self._conn, db_label="memory_store.db (holographic)")
        self._conn.executescript(_SCHEMA)
        _run_migrations(self._conn, self.db_path)
        self._conn.commit()

    def _warn_hrr_capacity(self, content: str, entity_names: list[str]) -> None:
        """Warn when a single fact bundles too many items for its HRR dimension.

        The HRR vector for a fact stores one bound component per content item
        (token) plus one per entity. For dim=1024 the SNR drops below 2.0 once
        the total exceeds dim/4 (256 items), which is a hard signal that the
        fact should be split into smaller atomic facts.
        """
        n_content = _content_item_count(content)
        n_entities = len(entity_names)
        n_items = n_content + n_entities
        if n_items > self.hrr_dim // 4:
            snr = _snr(self.hrr_dim, n_items)
            logger.warning(
                "HRR capacity warning: fact bundles %d content items + %d entities = %d "
                "items (dim=%d, SNR=%.2f). Split into atomic facts for reliable retrieval.",
                n_content,
                n_entities,
                n_items,
                self.hrr_dim,
                snr,
            )

    # ------------------------------------------------------------------
    # Near-duplicate detection / merge
    # ------------------------------------------------------------------

    def _find_near_duplicate(
        self,
        content: str,
        category: str,
        threshold: float | None = None,
    ) -> int | None:
        """Find a lexically near-duplicate fact in the same category.

        Uses FTS5 for coarse retrieval and Jaccard token overlap for the
        final decision. Does not update retrieval_count and ignores trust
        filters so that low-trust duplicates are still detected.
        """
        if threshold is None:
            threshold = self.near_duplicate_threshold

        query_tokens = _tokenize(content)
        if not query_tokens:
            return None

        # Build an OR-ed FTS5 query from content tokens. Quoting each token
        # avoids FTS5 syntax errors from punctuation/reserved words.
        match_query = " OR ".join(f'"{tok}"' for tok in query_tokens)

        try:
            rows = self._conn.execute(
                """
                SELECT f.fact_id, f.content, f.tags
                FROM facts_fts
                JOIN facts f ON f.fact_id = facts_fts.rowid
                WHERE facts_fts MATCH ?
                  AND f.category = ?
                  AND f.merged_into IS NULL
                ORDER BY facts_fts.rank
                LIMIT 100
                """,
                (match_query, category),
            ).fetchall()
        except sqlite3.Error:
            # Malformed FTS5 query or transient error — fall back to no match.
            return None

        if not rows:
            return None

        new_tokens = _tokenize(content)
        best_id: int | None = None
        best_score = 0.0

        for row in rows:
            candidate_tokens = _tokenize(row["content"]) | _tokenize(row["tags"])
            if not candidate_tokens:
                continue
            intersection = len(new_tokens & candidate_tokens)
            union = len(new_tokens | candidate_tokens)
            score = intersection / union if union else 0.0
            if score > best_score:
                best_score = score
                best_id = int(row["fact_id"])

        if best_id is not None and best_score >= threshold:
            return best_id
        return None

    def _merge_into(
        self,
        existing_id: int,
        content: str,
        tags: str,
        source_doc_id: int | None = None,
    ) -> int:
        """Merge a newly seen fact into an existing one.

        Returns the existing fact_id. Content may be replaced if the new
        wording is more specific; metadata (tags, trust, retrieval_count) is
        always merged. The source document link is kept if already set,
        otherwise the new one is applied.
        """
        row = self._conn.execute(
            "SELECT fact_id, content, tags, trust_score, category, source_doc_id "
            "FROM facts WHERE fact_id = ?",
            (existing_id,),
        ).fetchone()
        if row is None:
            return existing_id

        old_content: str = row["content"]
        old_tags: str = row["tags"] or ""
        old_trust: float = row["trust_score"]
        category: str = row["category"]
        old_source_doc_id: int | None = row["source_doc_id"]

        # Keep an existing source link; otherwise adopt the new one.
        merged_source_doc_id = old_source_doc_id if old_source_doc_id is not None else source_doc_id

        # Entity count for the existing fact (new content entities extracted below).
        old_entity_count = self._conn.execute(
            "SELECT COUNT(*) FROM fact_entities WHERE fact_id = ?",
            (existing_id,),
        ).fetchone()[0]
        new_entity_count = len(self._extract_entities(content))

        old_score = entities.content_specificity(old_content, old_entity_count)
        new_score = entities.content_specificity(content, new_entity_count)
        replace_content = new_score > old_score

        # Merge tags.
        merged_tags_set = set(t.strip() for t in old_tags.split(",") if t.strip())
        merged_tags_set.update(t.strip() for t in tags.split(",") if t.strip())
        merged_tags = ", ".join(sorted(merged_tags_set))

        new_trust = max(old_trust, self.default_trust)

        if replace_content:
            try:
                self._conn.execute(
                    """
                    UPDATE facts
                    SET content = ?,
                        tags = ?,
                        trust_score = ?,
                        source_doc_id = ?,
                        retrieval_count = retrieval_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE fact_id = ?
                    """,
                    (content, merged_tags, new_trust, merged_source_doc_id, existing_id),
                )
                self._conn.commit()
                # Re-extract entities and recompute HRR for the new wording.
                self._conn.execute(
                    "DELETE FROM fact_entities WHERE fact_id = ?",
                    (existing_id,),
                )
                new_entity_names = entities.extract_entities(content)
                for name in new_entity_names:
                    entity_id = entities.resolve_entity(self._conn, name)
                    entities.link_fact_entity(self._conn, existing_id, entity_id)
                self._warn_hrr_capacity(content, new_entity_names)
                self._compute_hrr_vector(existing_id, content)
                self._rebuild_bank(category)
                return existing_id
            except sqlite3.IntegrityError:
                # New content collides with another row; fall through to metadata-only merge.
                self._conn.rollback()

        # Metadata-only merge (content unchanged or UNIQUE collision).
        self._conn.execute(
            """
            UPDATE facts
            SET tags = ?,
                trust_score = ?,
                source_doc_id = ?,
                retrieval_count = retrieval_count + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE fact_id = ?
            """,
            (merged_tags, new_trust, merged_source_doc_id, existing_id),
        )
        self._conn.commit()
        return existing_id

    def _find_consolidation_candidates(
        self,
        category: str | None = None,
        generic_threshold: int | None = None,
        max_cluster_size: int = 6,
        min_jaccard: float = 0.3,
    ) -> list[list[dict]]:
        """Find clusters of facts that share entities and are candidates for consolidation.

        Thin wrapper around :func:`consolidation.find_consolidation_candidates`.
        The actual graph algorithm lives there so ``store.py`` stays focused on
        storage orchestration.
        """
        with self._lock:
            return consolidation.find_consolidation_candidates(
                conn=self._conn,
                category=category,
                generic_threshold=generic_threshold,
                max_cluster_size=max_cluster_size,
                min_jaccard=min_jaccard,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_fact(
        self,
        content: str,
        category: str = "general",
        tags: str = "",
        source_doc_id: int | None = None,
        trust: float | None = None,
    ) -> int:
        """Insert a fact and return its fact_id.

        Checks for near-duplicates (lexical overlap) before INSERT and merges
        into an existing fact when similarity exceeds the configured threshold.
        Falls back to the UNIQUE constraint for exact duplicates.
        """
        with self._lock:
            content = content.strip()
            if not content:
                raise ValueError("content must not be empty")

            initial_trust = _clamp_trust(trust) if trust is not None else self.default_trust

            # First line of defence: lexical near-duplicate detection.
            dup_id = self._find_near_duplicate(content, category)
            if dup_id is not None:
                return self._merge_into(dup_id, content, tags, source_doc_id)

            # Exact duplicate fallback (UNIQUE constraint).
            try:
                cur = self._conn.execute(
                    """
                    INSERT INTO facts (content, category, tags, trust_score, source_doc_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (content, category, tags, initial_trust, source_doc_id),
                )
                self._conn.commit()
                fact_id: int = cur.lastrowid  # type: ignore[assignment]
            except sqlite3.IntegrityError:
                # Duplicate content — return existing id
                row = self._conn.execute(
                    "SELECT fact_id, merged_into FROM facts WHERE content = ?", (content,)
                ).fetchone()
                existing_id = int(row["fact_id"])
                # If it was soft-deleted, reactivate it!
                if row["merged_into"] is not None:
                    self._conn.execute(
                        "UPDATE facts SET merged_into = NULL, trust_score = ?, updated_at = CURRENT_TIMESTAMP WHERE fact_id = ?",
                        (initial_trust, existing_id)
                    )
                    self._conn.commit()
                return existing_id

            # Entity extraction and linking
            entity_names = entities.extract_entities(content)
            for name in entity_names:
                entity_id = entities.resolve_entity(self._conn, name)
                entities.link_fact_entity(self._conn, fact_id, entity_id)

            # Capacity warning before committing the vector.
            self._warn_hrr_capacity(content, entity_names)

            # Compute HRR vector after entity linking
            self._compute_hrr_vector(fact_id, content)
            self._rebuild_bank(category)

            return fact_id

    def retain_document(
        self,
        raw_text: str,
        source: str = "",
        category: str = "general",
        extractor: FactExtractor | None = None,
        max_chunk_tokens: int = 6000,
    ) -> dict:
        """Store a raw document and extract atomic facts from it.

        The document is always persisted first (deduplicated by SHA256 of the
        raw text). Extraction is a separate success/failure unit: if the
        extractor returns nothing, the document remains as an orphan row and
        can be re-extracted later.

        Long documents are chunked before extraction so that LLM-based
        extractors stay within context-window limits without losing paragraph/
        sentence boundaries.

        Returns a dict with ``doc_id``, ``facts_added``, ``extractor_kind``,
        ``fact_ids``, and ``chunks_processed``.
        """
        if extractor is None:
            extractor = _LocalFallbackExtractor()

        raw_text = raw_text.strip()
        if not raw_text:
            raise ValueError("raw_text must not be empty")

        text_hash = _text_hash(raw_text)

        with self._lock:
            # Deduplicate by hash: repeated retains of the same text return the
            # same doc_id without creating a new row.
            self._conn.execute(
                """
                INSERT OR IGNORE INTO documents (raw_text, text_hash, source)
                VALUES (?, ?, ?)
                """,
                (raw_text, text_hash, source),
            )
            self._conn.commit()

            row = self._conn.execute(
                "SELECT doc_id FROM documents WHERE text_hash = ?",
                (text_hash,),
            ).fetchone()
            assert row is not None
            doc_id: int = row["doc_id"]

        # Chunk before extraction so LLM prompts don't overflow. Fallback
        # extractors also benefit from avoiding pathological whole-document
        # splits on Chinese text.
        chunks = _chunk_text(raw_text, max_chunk_tokens)

        fact_ids: list[int] = []
        is_fallback = extractor.kind == "fallback"
        fact_trust = _FALLBACK_TRUST if is_fallback else None

        for chunk in chunks:
            try:
                chunk_facts = extractor.extract(chunk, category)
            except Exception:
                # A failed chunk should not kill the whole document.
                continue
            for fact in chunk_facts:
                fact = fact.strip()
                if not fact:
                    continue
                try:
                    fact_id = self.add_fact(
                        fact,
                        category=category,
                        source_doc_id=doc_id,
                        trust=fact_trust,
                    )
                    fact_ids.append(fact_id)
                except Exception:
                    # A single bad fact should not kill the whole batch.
                    continue

        status = "document_stored_no_facts" if not fact_ids else "ok"
        return {
            "doc_id": doc_id,
            "facts_added": len(fact_ids),
            "extractor_kind": extractor.kind,
            "fact_ids": fact_ids,
            "chunks_processed": len(chunks),
            "status": status,
        }

    def search_facts(
        self,
        query: str,
        category: str | None = None,
        min_trust: float = 0.3,
        limit: int = 10,
    ) -> list[dict]:
        """Full-text search over facts using FTS5.

        Returns a list of fact dicts ordered by FTS5 rank, then trust_score
        descending. Also increments retrieval_count for matched facts.
        """
        with self._lock:
            query = query.strip()
            if not query:
                return []

            params: list = [query, min_trust]
            category_clause = ""
            if category is not None:
                category_clause = "AND f.category = ?"
                params.append(category)
            params.append(limit)

            sql = f"""
                SELECT f.fact_id, f.content, f.category, f.tags,
                       f.trust_score, f.retrieval_count, f.helpful_count,
                       f.created_at, f.updated_at
                FROM facts f
                JOIN facts_fts fts ON fts.rowid = f.fact_id
                WHERE facts_fts MATCH ?
                  AND f.trust_score >= ?
                  AND f.merged_into IS NULL
                  {category_clause}
                ORDER BY fts.rank, f.trust_score DESC
                LIMIT ?
            """

            rows = self._conn.execute(sql, params).fetchall()
            results = [self._row_to_dict(r) for r in rows]

            if results:
                ids = [r["fact_id"] for r in results]
                placeholders = ",".join("?" * len(ids))
                self._conn.execute(
                    f"UPDATE facts SET retrieval_count = retrieval_count + 1 WHERE fact_id IN ({placeholders})",
                    ids,
                )
                self._conn.commit()

            return results

    def update_fact(
        self,
        fact_id: int,
        content: str | None = None,
        trust_delta: float | None = None,
        tags: str | None = None,
        category: str | None = None,
    ) -> bool:
        """Partially update a fact. Trust is clamped to [0, 1].

        Returns True if the row existed, False otherwise.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT fact_id, trust_score FROM facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()
            if row is None:
                return False

            assignments: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
            params: list = []

            if content is not None:
                assignments.append("content = ?")
                params.append(content.strip())
            if tags is not None:
                assignments.append("tags = ?")
                params.append(tags)
            if category is not None:
                assignments.append("category = ?")
                params.append(category)
            if trust_delta is not None:
                new_trust = _clamp_trust(row["trust_score"] + trust_delta)
                assignments.append("trust_score = ?")
                params.append(new_trust)

            params.append(fact_id)
            self._conn.execute(
                f"UPDATE facts SET {', '.join(assignments)} WHERE fact_id = ?",
                params,
            )
            self._conn.commit()

            # If content changed, re-extract entities
            if content is not None:
                self._conn.execute(
                    "DELETE FROM fact_entities WHERE fact_id = ?", (fact_id,)
                )
                for name in self._extract_entities(content):
                    entity_id = self._resolve_entity(name)
                    self._link_fact_entity(fact_id, entity_id)
                self._conn.commit()

            # Recompute HRR vector if content changed
            if content is not None:
                self._compute_hrr_vector(fact_id, content)
            # Rebuild bank for relevant category
            cat = category or self._conn.execute(
                "SELECT category FROM facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()["category"]
            self._rebuild_bank(cat)

            return True

    def remove_fact(self, fact_id: int) -> bool:
        """Delete a fact and its entity links. Returns True if the row existed."""
        with self._lock:
            row = self._conn.execute(
                "SELECT fact_id, category FROM facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()
            if row is None:
                return False

            self._conn.execute(
                "DELETE FROM fact_entities WHERE fact_id = ?", (fact_id,)
            )
            self._conn.execute("DELETE FROM facts WHERE fact_id = ?", (fact_id,))
            self._conn.commit()
            self._rebuild_bank(row["category"])
            return True

    def list_facts(
        self,
        category: str | None = None,
        min_trust: float = 0.0,
        limit: int = 50,
    ) -> list[dict]:
        """Browse facts ordered by trust_score descending.

        Optionally filter by category and minimum trust score.
        """
        with self._lock:
            params: list = [min_trust]
            category_clause = ""
            if category is not None:
                category_clause = "AND category = ?"
                params.append(category)
            params.append(limit)

            sql = f"""
                SELECT fact_id, content, category, tags, trust_score,
                       retrieval_count, helpful_count, created_at, updated_at
                FROM facts
                WHERE trust_score >= ?
                  AND merged_into IS NULL
                  {category_clause}
                ORDER BY trust_score DESC
                LIMIT ?
            """
            rows = self._conn.execute(sql, params).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def record_feedback(self, fact_id: int, helpful: bool) -> dict:
        """Record user feedback and adjust trust asymmetrically.

        helpful=True  -> trust += 0.05, helpful_count += 1
        helpful=False -> trust -= 0.10

        Returns a dict with fact_id, old_trust, new_trust, helpful_count.
        Raises KeyError if fact_id does not exist.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT fact_id, trust_score, helpful_count FROM facts WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"fact_id {fact_id} not found")

            old_trust: float = row["trust_score"]
            delta = _HELPFUL_DELTA if helpful else _UNHELPFUL_DELTA
            new_trust = _clamp_trust(old_trust + delta)

            helpful_increment = 1 if helpful else 0
            self._conn.execute(
                """
                UPDATE facts
                SET trust_score    = ?,
                    helpful_count  = helpful_count + ?,
                    updated_at     = CURRENT_TIMESTAMP
                WHERE fact_id = ?
                """,
                (new_trust, helpful_increment, fact_id),
            )
            self._conn.commit()

            return {
                "fact_id":      fact_id,
                "old_trust":    old_trust,
                "new_trust":    new_trust,
                "helpful_count": row["helpful_count"] + helpful_increment,
            }

    def normalize_entities(
        self,
        edit_threshold: float = 0.85,
        token_threshold: float = 0.9,
    ) -> dict:
        """Merge fragmented entity variants into canonical entities.

        Uses conservative string edit distance and token overlap to cluster
        near-duplicate entity names (e.g. "K2.7", "K2_7", "k2.7"). A
        numeric/date/version signature gate blocks hierarchical pairs such as
        "K2" vs "K2.7" from being treated as writing variants. For each
        cluster, keeps the most specific entity as canonical, moves the other
        names into `aliases`, repoints `fact_entities` foreign keys, and
        recomputes HRR vectors for affected facts.

        Returns a report dict with clusters_merged, entities_merged,
        facts_reindexed, categories_rebuilt.
        """
        with self._lock:
            # Load all entities.
            rows = self._conn.execute(
                "SELECT entity_id, name, aliases, created_at FROM entities"
            ).fetchall()
            if len(rows) < 2:
                return {
                    "clusters_merged": 0,
                    "entities_merged": 0,
                    "facts_reindexed": 0,
                    "categories_rebuilt": [],
                }

            entity_rows = [dict(r) for r in rows]
            entity_ids = [e["entity_id"] for e in entity_rows]
            entities_by_id: dict[int, dict] = {e["entity_id"]: e for e in entity_rows}

            # Fact-link counts per entity (for canonical selection).
            fact_counts: dict[int, int] = {}
            for r in self._conn.execute(
                "SELECT entity_id, COUNT(*) AS c FROM fact_entities GROUP BY entity_id"
            ).fetchall():
                fact_counts[int(r["entity_id"])] = r["c"]

            # Pairwise similarity clustering.
            n = len(entity_rows)
            uf = entities._UnionFind(entity_ids)

            for i in range(n):
                for j in range(i + 1, n):
                    name_a = entity_rows[i]["name"]
                    name_b = entity_rows[j]["name"]

                    if entities.entity_names_match(
                        name_a, name_b, edit_threshold, token_threshold
                    ):
                        uf.union(entity_rows[i]["entity_id"], entity_rows[j]["entity_id"])

            clusters: dict[int, set[int]] = {}
            for eid in entity_ids:
                root = uf.find(eid)
                clusters.setdefault(root, set()).add(eid)

            # Filter to clusters with more than one member.
            merge_clusters = {
                root: members for root, members in clusters.items() if len(members) > 1
            }

            if not merge_clusters:
                return {
                    "clusters_merged": 0,
                    "entities_merged": 0,
                    "facts_reindexed": 0,
                    "categories_rebuilt": [],
                }

            affected_fact_ids: set[int] = set()
            categories_to_rebuild: set[str] = set()
            entities_merged = 0

            for root, members in merge_clusters.items():
                # Sort members to choose canonical:
                # 1. most specific name (digits/punctuation/length)
                # 2. most fact links
                # 3. earliest created
                # 4. lowest entity_id
                sorted_members = sorted(
                    members,
                    key=lambda eid: (
                        -entities.entity_specificity(entities_by_id[eid]["name"]),
                        -fact_counts.get(eid, 0),
                        entities_by_id[eid]["created_at"] or "",
                        eid,
                    )
                )
                canonical_id = sorted_members[0]
                canonical_entity = entities_by_id[canonical_id]

                # Collect all unique names in the cluster (case-insensitive dedup).
                unique_names: dict[str, str] = {}  # lowercase -> original
                for eid in sorted_members:
                    ent = entities_by_id[eid]
                    for raw_name in [ent["name"]] + entities._split_aliases(
                        ent["aliases"]
                    ):
                        key = raw_name.strip().lower()
                        if key and key not in unique_names:
                            unique_names[key] = raw_name.strip()

                # Aliases = all unique names except the canonical display name.
                canonical_key = canonical_entity["name"].strip().lower()
                alias_names = [
                    name for key, name in unique_names.items() if key != canonical_key
                ]
                alias_str = ", ".join(alias_names)

                # Update canonical entity aliases.
                self._conn.execute(
                    "UPDATE entities SET aliases = ? WHERE entity_id = ?",
                    (alias_str, canonical_id),
                )

                # Repoint fact_entities and track affected facts.
                for eid in sorted_members[1:]:
                    fact_rows = self._conn.execute(
                        "SELECT fact_id FROM fact_entities WHERE entity_id = ?",
                        (eid,),
                    ).fetchall()
                    for fr in fact_rows:
                        affected_fact_ids.add(int(fr["fact_id"]))

                    # Move links to canonical, ignoring duplicates.
                    self._conn.execute(
                        """
                        INSERT OR IGNORE INTO fact_entities (fact_id, entity_id)
                        SELECT fact_id, ? FROM fact_entities WHERE entity_id = ?
                        """,
                        (canonical_id, eid),
                    )
                    self._conn.execute(
                        "DELETE FROM fact_entities WHERE entity_id = ?",
                        (eid,),
                    )
                    self._conn.execute(
                        "DELETE FROM entities WHERE entity_id = ?",
                        (eid,),
                    )
                    entities_merged += 1

            self._conn.commit()

            # Recompute HRR vectors for affected facts.
            if affected_fact_ids and self._hrr_available:
                for fact_id in affected_fact_ids:
                    row = self._conn.execute(
                        "SELECT content, category FROM facts WHERE fact_id = ?",
                        (fact_id,),
                    ).fetchone()
                    if row is None:
                        continue
                    self._compute_hrr_vector(fact_id, row["content"])
                    categories_to_rebuild.add(row["category"])

                for category in categories_to_rebuild:
                    self._rebuild_bank(category)

            return {
                "clusters_merged": len(merge_clusters),
                "entities_merged": entities_merged,
                "facts_reindexed": len(affected_fact_ids),
                "categories_rebuilt": sorted(categories_to_rebuild),
            }

    def consolidate_facts(
        self,
        model_call: Callable[[str], str],
        category: str | None = None,
        generic_threshold: int | None = None,
        max_cluster_size: int = 6,
        min_jaccard: float = 0.3,
        clusters: list[list[dict]] | None = None,
    ) -> dict:
        """Run semantic consolidation using LLM on clusters of facts.

        Thin wrapper around :func:`consolidation.consolidate_facts`. The heavy
        lifting (candidate discovery, LLM merging, soft-deletion) lives there
        so ``store.py`` stays focused on storage orchestration.
        """
        return consolidation.consolidate_facts(
            store=self,
            model_call=model_call,
            category=category,
            generic_threshold=generic_threshold,
            max_cluster_size=max_cluster_size,
            min_jaccard=min_jaccard,
            clusters=clusters,
        )

    def _entity_names_match(
        self,
        name_a: str,
        name_b: str,
        edit_threshold: float,
        token_threshold: float,
    ) -> bool:
        """Thin wrapper around :func:`entities.entity_names_match`."""
        return entities.entity_names_match(
            name_a, name_b, edit_threshold, token_threshold
        )

    # ------------------------------------------------------------------
    # Entity helpers (delegated to entities.py)
    # ------------------------------------------------------------------

    def _extract_entities(self, text: str) -> list[str]:
        """Extract entity candidates from text."""
        return entities.extract_entities(text)

    def _resolve_entity(self, name: str) -> int:
        """Find or create an entity and return its id."""
        return entities.resolve_entity(self._conn, name)

    def _resolve_entity_id(self, name: str) -> int | None:
        """Find an existing entity by name or alias (read-only)."""
        return entities.resolve_entity_id(self._conn, name)

    def _link_fact_entity(self, fact_id: int, entity_id: int) -> None:
        """Link a fact to an entity."""
        entities.link_fact_entity(self._conn, fact_id, entity_id)

    def _compute_hrr_vector(self, fact_id: int, content: str) -> None:
        """Compute and store HRR vector for a fact. No-op if numpy unavailable."""
        with self._lock:
            if not self._hrr_available:
                return

            # Get entities linked to this fact
            rows = self._conn.execute(
                """
                SELECT e.name FROM entities e
                JOIN fact_entities fe ON fe.entity_id = e.entity_id
                WHERE fe.fact_id = ?
                """,
                (fact_id,),
            ).fetchall()
            entity_names = [row["name"] for row in rows]
            vector = hrr.encode_fact(content, entity_names, self.hrr_dim)
            self._conn.execute(
                "UPDATE facts SET hrr_vector = ? WHERE fact_id = ?",
                (hrr.phases_to_bytes(vector), fact_id),
            )
            self._conn.commit()

    def _rebuild_bank(self, category: str) -> None:
        """Full rebuild of a category's memory bank from all its fact vectors."""
        with self._lock:
            if not self._hrr_available:
                return

            bank_name = f"cat:{category}"
            rows = self._conn.execute(
                "SELECT hrr_vector FROM facts WHERE category = ? AND hrr_vector IS NOT NULL AND merged_into IS NULL",
                (category,),
            ).fetchall()

            if not rows:
                self._conn.execute("DELETE FROM memory_banks WHERE bank_name = ?", (bank_name,))
                self._conn.commit()
                return

            vectors = [hrr.bytes_to_phases(row["hrr_vector"]) for row in rows]
            bank_vector = hrr.bundle(*vectors)
            fact_count = len(vectors)

            # Check SNR
            hrr.snr_estimate(self.hrr_dim, fact_count)

            self._conn.execute(
                """
                INSERT INTO memory_banks (bank_name, vector, dim, fact_count, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(bank_name) DO UPDATE SET
                    vector = excluded.vector,
                    dim = excluded.dim,
                    fact_count = excluded.fact_count,
                    updated_at = excluded.updated_at
                """,
                (bank_name, hrr.phases_to_bytes(bank_vector), self.hrr_dim, fact_count),
            )
            self._conn.commit()

    def rebuild_all_vectors(self, dim: int | None = None) -> int:
        """Recompute all HRR vectors + banks from text. For recovery/migration.

        Returns the number of facts processed.
        """
        with self._lock:
            if not self._hrr_available:
                return 0

            if dim is not None:
                self.hrr_dim = dim

            rows = self._conn.execute(
                "SELECT fact_id, content, category FROM facts"
            ).fetchall()

            categories: set[str] = set()
            for row in rows:
                self._compute_hrr_vector(row["fact_id"], row["content"])
                categories.add(row["category"])

            for category in categories:
                self._rebuild_bank(category)

            return len(rows)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a sqlite3.Row to a plain dict."""
        return dict(row)

    def run_gc(self, force: bool = False) -> dict:
        """Run lazy garbage collection (currently trust-decay).

        This is a thin forwarder to ``GarbageCollector.maybe_run`` so that
        callers in __init__.py do not need to import memory_gc.py directly.
        """
        return self._gc.maybe_run(force=force)

    def close(self) -> None:
        """Checkpoint WAL and close the database connection."""
        try:
            self._conn.execute("PRAGMA wal_checkpoint(FULL)")
            self._conn.commit()
        except Exception:
            pass
        self._conn.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
