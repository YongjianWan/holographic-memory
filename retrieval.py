"""Multi-strategy fact retrieval using Reciprocal Rank Fusion (RRF).

Default search combines FTS5 full-text search, Jaccard token overlap, and HRR
vector similarity by ranking position rather than raw score, avoiding the
"apples + oranges" problem of merging incomparable signals.

HRR is deliberately retained as a local weak semantic/structural signal in the
absence of an embedding service. It is not equivalent to embedding-based
semantic recall, but removing it leaves only lexical matching.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .store import MemoryStore

try:
    from . import holographic as hrr
    from .memory_gc import recency_factor
except ImportError:
    import holographic as hrr  # type: ignore[no-redef]
    from memory_gc import recency_factor  # type: ignore[no-redef]


# RRF smoothing constant (k=60 is the Hindsight production default).
_RRF_K = 60

# How many top-ranked facts each retrieval method contributes.
# Use a fixed floor so small-limit queries still get a meaningful overlap pool.
_CANDIDATE_POOL = 100

# Guard against scanning huge HRR tables in compositional queries.
# Above this many candidate facts we truncate to the most recently updated.
_MAX_HRR_SCAN_FACTS = 1000


class FactRetriever:
    """Multi-strategy fact retrieval with RRF fusion and trust-weighted scoring."""

    def __init__(
        self,
        store: MemoryStore,
        hrr_dim: int = 1024,
        recency_max_days: float = 365.0,
        recency_floor: float = 0.1,
    ):
        self.store = store
        self.hrr_dim = hrr_dim
        self.recency_max_days = max(1.0, recency_max_days)
        self.recency_floor = max(0.0, min(1.0, recency_floor))

    def search(
        self,
        query: str,
        category: str | None = None,
        min_trust: float = 0.3,
        limit: int = 10,
    ) -> list[dict]:
        """RRF fusion search across FTS5, Jaccard, and HRR signals.

        Pipeline:
        1. Each method independently returns a ranked list of top facts.
        2. RRF merges the lists using only rank position:
           score(fact) = Σ 1 / (_RRF_K + rank_i)
        3. Multiplicative boosts are applied for trust and recency.

        Returns list of dicts with fact data + 'score' field, sorted by score desc.
        """
        query = query.strip()
        if not query:
            return []
        expanded_query = self._expand_query_with_equivalences(query)

        pool = max(limit * 3, _CANDIDATE_POOL)

        # Independent rankings from each method.
        fts_ranking = self._fts_ranking(expanded_query, category, min_trust, pool)
        jaccard_ranking = self._jaccard_ranking(expanded_query, category, min_trust, pool)
        hrr_ranking = self._hrr_ranking(expanded_query, category, min_trust, pool)

        if not (fts_ranking or jaccard_ranking or hrr_ranking):
            return []

        # Union of candidate fact IDs.
        candidate_ids = set(fts_ranking) | set(jaccard_ranking) | set(hrr_ranking)

        # Fetch full rows for the candidate set.
        rows = self._fetch_facts(candidate_ids, category, min_trust)
        if not rows:
            return []

        # Compute RRF scores and apply multiplicative boosts.
        scored = []
        for fact in rows:
            fid = fact["fact_id"]
            rrf_score = 0.0
            if fid in fts_ranking:
                rrf_score += 1.0 / (_RRF_K + fts_ranking[fid])
            if fid in jaccard_ranking:
                rrf_score += 1.0 / (_RRF_K + jaccard_ranking[fid])
            if fid in hrr_ranking:
                rrf_score += 1.0 / (_RRF_K + hrr_ranking[fid])

            # Trust boost: centered at 1.0, ±10% over [0, 1].
            trust_boost = 1.0 + 0.2 * (fact["trust_score"] - 0.5)

            recency_boost = self._recency_boost(
                fact.get("last_accessed_at") or fact.get("created_at")
            )

            # Speaker penalty: reduce score of raw diarized chitchat (starts with "说话人X说" etc.)
            speaker_penalty = 0.85 if re.match(r"^说话人\s*\d+", fact["content"]) else 1.0

            fact["score"] = rrf_score * trust_boost * recency_boost * speaker_penalty
            scored.append(fact)

        scored.sort(key=lambda x: x["score"], reverse=True)
        results = scored[:limit]

        # Strip raw HRR bytes — callers expect JSON-serializable dicts.
        for fact in results:
            fact.pop("hrr_vector", None)
        self.store.attach_provenance(results)
        self.store.record_retrievals({fact["fact_id"] for fact in results})
        return results

    def _expand_query_with_equivalences(self, query: str, *, limit: int = 24) -> str:
        """Expand a query using local semantic-equivalence lookup tables."""
        conn = self.store._conn
        try:
            table = conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'semantic_equivalence_terms'
                """
            ).fetchone()
        except sqlite3.Error:
            return query
        if table is None:
            return query

        tokens = {token.lower() for token in hrr.tokenize_text(query)}
        if not tokens:
            return query
        candidates = set(tokens)
        candidates.add(query.strip().lower())

        expansions: list[str] = []
        seen = {query.lower()}
        for candidate in sorted(candidates, key=len, reverse=True):
            rows = conn.execute(
                """
                SELECT DISTINCT peer.term
                FROM semantic_equivalence_terms seed
                JOIN semantic_equivalence_terms peer
                  ON peer.group_id = seed.group_id
                WHERE seed.normalized_term = ?
                ORDER BY peer.confidence DESC, LENGTH(peer.term) DESC, peer.term
                LIMIT ?
                """,
                (candidate, limit),
            ).fetchall()
            for row in rows:
                term = str(row["term"]).strip()
                key = term.lower()
                if term and key not in seen:
                    seen.add(key)
                    expansions.append(term)
                    if len(expansions) >= limit:
                        return " ".join([query, *expansions])

        return " ".join([query, *expansions]) if expansions else query

    # ------------------------------------------------------------------
    # HRR candidate helpers (avoid full-table scans)
    # ------------------------------------------------------------------

    def _resolve_entity_fact_ids(self, entity_name: str) -> set[int] | None:
        """Return fact IDs linked to an entity by canonical name or alias.

        Returns None if the entity is not known.
        """
        entity_id = self.store._resolve_entity_id(entity_name)
        if entity_id is None:
            return None
        rows = self.store._conn.execute(
            "SELECT fact_id FROM fact_entities WHERE entity_id = ?", (entity_id,)
        ).fetchall()
        return {r["fact_id"] for r in rows}

    def _fetch_hrr_candidates(
        self,
        fact_ids: set[int] | None,
        category: str | None = None,
    ) -> list:
        """Fetch facts with HRR vectors, optionally restricted to a fact-id set.

        Applies a hard ceiling to keep compositional queries responsive on
        large stores.  If the candidate set exceeds the ceiling, the most
        recently updated facts are kept and a warning is logged.
        """
        conn = self.store._conn
        where = "WHERE hrr_vector IS NOT NULL AND merged_into IS NULL"
        params: list = []
        if category:
            where += " AND category = ?"
            params.append(category)
        if fact_ids is not None:
            if not fact_ids:
                return []
            placeholders = ",".join("?" * len(fact_ids))
            where += f" AND fact_id IN ({placeholders})"
            params.extend(fact_ids)

        rows = conn.execute(
            f"""
            SELECT fact_id, content, category, tags, trust_score,
                   retrieval_count, helpful_count, created_at, updated_at,
                   last_accessed_at, hrr_vector
            FROM facts
            {where}
            """,
            params,
        ).fetchall()

        if len(rows) > _MAX_HRR_SCAN_FACTS:
            logger.warning(
                "HRR scan candidate set (%d) exceeds %d; truncating to most recent",
                len(rows),
                _MAX_HRR_SCAN_FACTS,
            )
            rows = sorted(
                rows, key=lambda r: r["updated_at"] or r["created_at"], reverse=True
            )[:_MAX_HRR_SCAN_FACTS]

        return rows

    def probe(
        self,
        entity: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Compositional entity query using HRR algebra.

        Unbinds entity from memory bank to extract associated content.
        This is NOT keyword search — it uses algebraic structure to find facts
        where the entity plays a structural role.

        Falls back to FTS5 search if numpy unavailable.
        """
        if not hrr._HAS_NUMPY:
            # Fallback to keyword search on entity name
            return self.search(entity, category=category, limit=limit)

        conn = self.store._conn

        # Pre-filter: only score facts explicitly linked to this entity.
        entity_fact_ids = self._resolve_entity_fact_ids(entity)
        if not entity_fact_ids:
            return self.search(entity, category=category, limit=limit)

        # Encode entity as role-bound vector
        role_entity = hrr.encode_atom("__hrr_role_entity__", self.hrr_dim)
        entity_vec = hrr.encode_atom(entity.lower(), self.hrr_dim)
        probe_key = hrr.bind(entity_vec, role_entity)

        # Try category-specific sharded banks first, then linked facts directly.
        # Banks are sharded by source_doc_id (see store._rebuild_bank), so we
        # only need the shards covering this entity's own facts — bundling
        # just those keeps the unbind signal localized instead of unbinding
        # against the whole (noisier) category-wide superposition.
        if category:
            placeholders = ",".join("?" * len(entity_fact_ids))
            doc_ids = {
                row["source_doc_id"]
                for row in conn.execute(
                    f"SELECT DISTINCT source_doc_id FROM facts "
                    f"WHERE category = ? AND fact_id IN ({placeholders})",
                    (category, *entity_fact_ids),
                ).fetchall()
            }
            bank_names = self.store._bank_names_for_docs(category, doc_ids)
            if bank_names:
                bank_placeholders = ",".join("?" * len(bank_names))
                bank_rows = conn.execute(
                    f"SELECT vector FROM memory_banks WHERE bank_name IN ({bank_placeholders})",
                    bank_names,
                ).fetchall()
                bank_vectors = [hrr.bytes_to_phases(r["vector"]) for r in bank_rows]
                bank_vec = hrr.bundle(*bank_vectors)
                extracted = hrr.unbind(bank_vec, probe_key)
                results = self._score_facts_by_vector(
                    extracted, category=category, limit=limit, fact_ids=entity_fact_ids
                )
                self.store.record_retrievals({r["fact_id"] for r in results})
                return results

        rows = self._fetch_hrr_candidates(entity_fact_ids, category=category)
        if not rows:
            return self.search(entity, category=category, limit=limit)

        scored = []
        for row in rows:
            fact = dict(row)
            fact_vec = hrr.bytes_to_phases(fact.pop("hrr_vector"))
            # Unbind probe key from fact to see if entity is structurally present
            residual = hrr.unbind(fact_vec, probe_key)
            # Compare residual against content signal
            role_content = hrr.encode_atom("__hrr_role_content__", self.hrr_dim)
            content_vec = hrr.bind(hrr.encode_text(fact["content"], self.hrr_dim), role_content)
            sim = hrr.similarity(residual, content_vec)
            fact["score"] = (sim + 1.0) / 2.0 * fact["trust_score"]
            scored.append(fact)

        scored.sort(key=lambda x: x["score"], reverse=True)
        results = scored[:limit]
        self.store.attach_provenance(results)
        self.store.record_retrievals({r["fact_id"] for r in results})
        return results

    def related(
        self,
        entity: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Discover facts that share structural connections with an entity.

        Unlike probe (which finds facts *about* an entity), related finds
        facts that are connected through shared context — e.g., other entities
        mentioned alongside this one, or content that overlaps structurally.

        Falls back to FTS5 search if numpy unavailable.
        """
        if not hrr._HAS_NUMPY:
            return self.search(entity, category=category, limit=limit)

        # Pre-filter: only score facts explicitly linked to this entity.
        entity_fact_ids = self._resolve_entity_fact_ids(entity)
        if not entity_fact_ids:
            return self.search(entity, category=category, limit=limit)

        # Encode entity as a bare atom (not role-bound — we want ANY structural match)
        entity_vec = hrr.encode_atom(entity.lower(), self.hrr_dim)

        rows = self._fetch_hrr_candidates(entity_fact_ids, category=category)
        if not rows:
            return self.search(entity, category=category, limit=limit)

        # Score each fact by how much the entity's atom appears in its vector
        # This catches both role-bound entity matches AND content word matches
        scored = []
        for row in rows:
            fact = dict(row)
            fact_vec = hrr.bytes_to_phases(fact.pop("hrr_vector"))

            # Check structural similarity: unbind entity from fact
            residual = hrr.unbind(fact_vec, entity_vec)
            # A high-similarity residual to ANY known role vector means this entity
            # plays a structural role in the fact
            role_entity = hrr.encode_atom("__hrr_role_entity__", self.hrr_dim)
            role_content = hrr.encode_atom("__hrr_role_content__", self.hrr_dim)

            entity_role_sim = hrr.similarity(residual, role_entity)
            content_role_sim = hrr.similarity(residual, role_content)
            # Take the max — entity could appear in either role
            best_sim = max(entity_role_sim, content_role_sim)

            fact["score"] = (best_sim + 1.0) / 2.0 * fact["trust_score"]
            scored.append(fact)

        scored.sort(key=lambda x: x["score"], reverse=True)
        results = scored[:limit]
        self.store.attach_provenance(results)
        self.store.record_retrievals({r["fact_id"] for r in results})
        return results

    def reason(
        self,
        entities: list[str],
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Multi-entity compositional query — vector-space JOIN.

        Given multiple entities, algebraically intersects their structural
        connections to find facts related to ALL of them simultaneously.
        This is compositional reasoning that no embedding DB can do.

        Example: reason(["peppi", "backend"]) finds facts where peppi AND
        backend both play structural roles — without keyword matching.

        Falls back to FTS5 search if numpy unavailable.
        """
        if not hrr._HAS_NUMPY or not entities:
            # Fallback: search with all entities as keywords
            query = " ".join(entities)
            return self.search(query, category=category, limit=limit)

        role_entity = hrr.encode_atom("__hrr_role_entity__", self.hrr_dim)

        # Pre-filter: only score facts linked to the query entities.
        entity_fact_sets: list[set[int]] = []
        for entity in entities:
            fact_ids = self._resolve_entity_fact_ids(entity)
            if fact_ids is None:
                # Unknown entity -> fall back to keyword search.
                query = " ".join(entities)
                return self.search(query, category=category, limit=limit)
            entity_fact_sets.append(fact_ids)

        # Prefer facts linked to ALL entities; fall back to union if empty.
        candidate_ids = set.intersection(*entity_fact_sets)
        if not candidate_ids:
            candidate_ids = set.union(*entity_fact_sets)
        if not candidate_ids:
            query = " ".join(entities)
            return self.search(query, category=category, limit=limit)

        # For each entity, compute what the bank "remembers" about it
        # by unbinding entity+role from each fact vector
        entity_residuals = []
        for entity in entities:
            entity_vec = hrr.encode_atom(entity.lower(), self.hrr_dim)
            probe_key = hrr.bind(entity_vec, role_entity)
            entity_residuals.append(probe_key)

        rows = self._fetch_hrr_candidates(candidate_ids, category=category)
        if not rows:
            query = " ".join(entities)
            return self.search(query, category=category, limit=limit)

        # Score each fact by how much EACH entity is structurally present.
        # A fact scores high only if ALL entities have structural presence
        # (AND semantics via min, vs OR which would use mean/max).
        role_content = hrr.encode_atom("__hrr_role_content__", self.hrr_dim)

        scored = []
        for row in rows:
            fact = dict(row)
            fact_vec = hrr.bytes_to_phases(fact.pop("hrr_vector"))

            entity_scores = []
            for probe_key in entity_residuals:
                residual = hrr.unbind(fact_vec, probe_key)
                sim = hrr.similarity(residual, role_content)
                entity_scores.append(sim)

            min_sim = min(entity_scores)
            fact["score"] = (min_sim + 1.0) / 2.0 * fact["trust_score"]
            scored.append(fact)

        scored.sort(key=lambda x: x["score"], reverse=True)
        results = scored[:limit]
        self.store.attach_provenance(results)
        self.store.record_retrievals({r["fact_id"] for r in results})
        return results

    def contradict(
        self,
        category: str | None = None,
        threshold: float = 0.3,
        limit: int = 10,
    ) -> list[dict]:
        """Find potentially contradictory facts via entity overlap + content divergence.

        Two facts contradict when they share entities (same subject) but have
        low content-vector similarity (different claims). This is automated
        memory hygiene — no other memory system does this.

        Returns pairs of facts with a contradiction score.
        Falls back to empty list if numpy unavailable.
        """
        if not hrr._HAS_NUMPY:
            return []

        conn = self.store._conn

        # Get all facts with vectors and their linked entities
        where = "WHERE f.hrr_vector IS NOT NULL AND f.merged_into IS NULL"
        params: list = []
        if category:
            where += " AND f.category = ?"
            params.append(category)

        rows = conn.execute(
            f"""
            SELECT f.fact_id, f.content, f.category, f.tags, f.trust_score,
                   f.created_at, f.updated_at, f.hrr_vector
            FROM facts f
            {where}
            """,
            params,
        ).fetchall()

        if len(rows) < 2:
            return []

        # Guard against O(n²) explosion on large fact stores.
        # At 500 facts, that's ~125K comparisons — acceptable.
        # Above that, only check the most recently updated facts.
        _MAX_CONTRADICT_FACTS = 500
        if len(rows) > _MAX_CONTRADICT_FACTS:
            rows = sorted(rows, key=lambda r: r["updated_at"] or r["created_at"], reverse=True)
            rows = rows[:_MAX_CONTRADICT_FACTS]

        # Build entity sets per fact
        fact_entities: dict[int, set[str]] = {}
        for row in rows:
            fid = row["fact_id"]
            entity_rows = conn.execute(
                """
                SELECT e.name FROM entities e
                JOIN fact_entities fe ON fe.entity_id = e.entity_id
                WHERE fe.fact_id = ?
                """,
                (fid,),
            ).fetchall()
            fact_entities[fid] = {r["name"].lower() for r in entity_rows}

        # Compare all pairs: high entity overlap + low content similarity = contradiction
        facts = [dict(r) for r in rows]
        contradictions = []

        for i in range(len(facts)):
            for j in range(i + 1, len(facts)):
                f1, f2 = facts[i], facts[j]
                ents1 = fact_entities.get(f1["fact_id"], set())
                ents2 = fact_entities.get(f2["fact_id"], set())

                if not ents1 or not ents2:
                    continue

                # Entity overlap (Jaccard)
                entity_overlap = len(ents1 & ents2) / len(ents1 | ents2) if (ents1 | ents2) else 0.0

                if entity_overlap < 0.3:
                    continue  # Not enough entity overlap to be contradictory

                # Content similarity via HRR vectors
                v1 = hrr.bytes_to_phases(f1["hrr_vector"])
                v2 = hrr.bytes_to_phases(f2["hrr_vector"])
                content_sim = hrr.similarity(v1, v2)

                # High entity overlap + low content similarity = potential contradiction
                # contradiction_score: higher = more contradictory
                contradiction_score = entity_overlap * (1.0 - (content_sim + 1.0) / 2.0)

                if contradiction_score >= threshold:
                    # Strip hrr_vector from output (not JSON serializable)
                    f1_clean = {k: v for k, v in f1.items() if k != "hrr_vector"}
                    f2_clean = {k: v for k, v in f2.items() if k != "hrr_vector"}
                    self.store.attach_provenance([f1_clean, f2_clean])
                    contradictions.append({
                        "fact_a": f1_clean,
                        "fact_b": f2_clean,
                        "entity_overlap": round(entity_overlap, 3),
                        "content_similarity": round(content_sim, 3),
                        "contradiction_score": round(contradiction_score, 3),
                        "shared_entities": sorted(ents1 & ents2),
                    })

        contradictions.sort(key=lambda x: x["contradiction_score"], reverse=True)
        return contradictions[:limit]

    def _score_facts_by_vector(
        self,
        target_vec: "np.ndarray",
        category: str | None = None,
        limit: int = 10,
        fact_ids: set[int] | None = None,
    ) -> list[dict]:
        """Score facts by similarity to a target vector.

        If ``fact_ids`` is provided, only facts in that set are considered,
        avoiding a full-table scan.
        """
        rows = self._fetch_hrr_candidates(fact_ids, category=category)

        scored = []
        for row in rows:
            fact = dict(row)
            fact_vec = hrr.bytes_to_phases(fact.pop("hrr_vector"))
            sim = hrr.similarity(target_vec, fact_vec)
            fact["score"] = (sim + 1.0) / 2.0 * fact["trust_score"]
            scored.append(fact)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return self.store.attach_provenance(scored[:limit])

    def _fts_ranking(
        self,
        query: str,
        category: str | None,
        min_trust: float,
        top_n: int,
    ) -> dict[int, int]:
        """Return FTS5 ranking as {fact_id: 1-indexed rank}.

        Uses SQLite FTS5 MATCH ordering (lower rank = better match).
        """
        conn = self.store._conn

        words = re.findall(r"[\u4e00-\u9fff0-9a-zA-Z]+", query.lower())
        terms = []
        stop_patterns = {"是什么", "当时卡", "卡在哪", "在哪", "我上次", "上次纠", "结论是", "的结论", "的定义"}
        for word in words:
            has_cjk = any('\u4e00' <= c <= '\u9fff' for c in word)
            if has_cjk:
                if len(word) >= 3:
                    for i in range(len(word) - 2):
                        t = word[i:i+3]
                        if t in stop_patterns:
                            continue
                        terms.append(t)
                else:
                    terms.append(word)
            else:
                if len(word) >= 3:
                    terms.append(word)

        if not terms:
            fts_query = query
        else:
            fts_query = " OR ".join(f'"{t}"' for t in terms)

        params: list = []
        where_clauses = ["facts_fts MATCH ?", "f.trust_score >= ?", "f.merged_into IS NULL"]
        params.append(fts_query)
        params.append(min_trust)

        if category:
            where_clauses.append("f.category = ?")
            params.append(category)

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT f.fact_id
            FROM facts_fts
            JOIN facts f ON f.fact_id = facts_fts.rowid
            WHERE {where_sql}
            ORDER BY facts_fts.rank
            LIMIT ?
        """
        params.append(top_n)

        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            # FTS5 MATCH can fail on malformed queries — fall back to empty
            return {}

        return {row["fact_id"]: rank for rank, row in enumerate(rows, start=1)}

    def _jaccard_ranking(
        self,
        query: str,
        category: str | None,
        min_trust: float,
        top_n: int,
    ) -> dict[int, int]:
        """Return token-overlap ranking (using Overlap Coefficient) as {fact_id: 1-indexed rank}."""
        conn = self.store._conn

        where = "WHERE trust_score >= ? AND merged_into IS NULL"
        params: list = [min_trust]
        if category:
            where += " AND category = ?"
            params.append(category)

        rows = conn.execute(
            f"""
            SELECT fact_id, content, tags
            FROM facts
            {where}
            """,
            params,
        ).fetchall()

        query_tokens = self._tokenize(query)
        # Filter out common query question/stop words to suppress chitchat noise
        stop_tokens = {'我', '你', '的', '是', '在', '了', '和', '有', '及', '与', '这', '那', '哪', '什么', '怎么', '谁', '个', '是哪', '是什么', '在哪', '上次', '我上次'}
        query_tokens = {t for t in query_tokens if t not in stop_tokens}

        if not query_tokens:
            return {}

        scored = []
        for row in rows:
            fact_tokens = self._tokenize(row["content"]) | self._tokenize(row["tags"])
            # Overlap Coefficient (intersection / query_length) to eliminate long-document penalty
            intersection = len(query_tokens & fact_tokens)
            similarity = intersection / len(query_tokens)
            if similarity > 0.0:
                scored.append((row["fact_id"], similarity))

        scored.sort(key=lambda x: x[1], reverse=True)
        return {fact_id: rank for rank, (fact_id, _) in enumerate(scored[:top_n], start=1)}

    def _hrr_ranking(
        self,
        query: str,
        category: str | None,
        min_trust: float,
        top_n: int,
    ) -> dict[int, int]:
        """Return HRR vector similarity ranking as {fact_id: 1-indexed rank}.

        Returns an empty dict if numpy is unavailable.
        """
        if not hrr._HAS_NUMPY:
            return {}

        conn = self.store._conn

        where = "WHERE hrr_vector IS NOT NULL AND trust_score >= ? AND merged_into IS NULL"
        params: list = [min_trust]
        if category:
            where += " AND category = ?"
            params.append(category)

        rows = conn.execute(
            f"""
            SELECT fact_id, hrr_vector
            FROM facts
            {where}
            """,
            params,
        ).fetchall()

        # Align query vector with the content component of encode_fact.
        # See probe() for the same pattern: bind(encode_text(...), ROLE_CONTENT).
        role_content = hrr.encode_atom("__hrr_role_content__", self.hrr_dim)
        query_vec = hrr.bind(hrr.encode_text(query, self.hrr_dim), role_content)

        scored = []
        for row in rows:
            fact_vec = hrr.bytes_to_phases(row["hrr_vector"])
            sim = hrr.similarity(query_vec, fact_vec)
            # Shift from [-1, 1] to [0, 1] for ranking consistency.
            norm_sim = (sim + 1.0) / 2.0
            scored.append((row["fact_id"], norm_sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return {fact_id: rank for rank, (fact_id, _) in enumerate(scored[:top_n], start=1)}

    def _fetch_facts(
        self,
        fact_ids: set[int],
        category: str | None,
        min_trust: float,
    ) -> list[dict]:
        """Fetch full fact rows for a set of IDs, applying filters."""
        if not fact_ids:
            return []

        conn = self.store._conn
        placeholders = ",".join("?" * len(fact_ids))
        params: list = list(fact_ids)

        where = f"WHERE fact_id IN ({placeholders}) AND trust_score >= ? AND merged_into IS NULL"
        params.append(min_trust)

        if category:
            where += " AND category = ?"
            params.append(category)

        rows = conn.execute(
            f"""
            SELECT fact_id, content, category, tags, trust_score,
                   retrieval_count, helpful_count, created_at, updated_at,
                   last_accessed_at, hrr_vector
            FROM facts
            {where}
            """,
            params,
        ).fetchall()

        return [dict(r) for r in rows]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Segment CJK characters and alphanumeric words for Jaccard matching."""
        return set(hrr.tokenize_text(text))

    @staticmethod
    def _jaccard_similarity(set_a: set, set_b: set) -> float:
        """Jaccard similarity coefficient: |A ∩ B| / |A ∪ B|."""
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _recency_boost(self, timestamp_str: str | None) -> float:
        """Derive a bounded secondary boost from the factual access timestamp.

        ``recency_factor`` expresses freshness on its natural 0.1..1.0 scale.
        Retrieval maps that signal to 0.9..1.0 so age can break close RRF ties
        without overpowering relevance.
        """
        if not timestamp_str:
            return 0.9
        try:
            ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_days = max(
                0.0,
                (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0,
            )
            freshness = recency_factor(
                age_days,
                max_days=self.recency_max_days,
                floor=self.recency_floor,
            )
            freshness_range = 1.0 - self.recency_floor
            if freshness_range <= 0.0:
                return 1.0
            normalized = (freshness - self.recency_floor) / freshness_range
            return 0.9 + 0.1 * normalized
        except (ValueError, TypeError):
            return 0.9
