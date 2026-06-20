"""Multi-strategy fact retrieval using Reciprocal Rank Fusion (RRF).

Combines FTS5 full-text search, Jaccard token overlap, and HRR vector
similarity by ranking position rather than raw score, avoiding the
"apples + oranges" problem of merging incomparable signals.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import MemoryStore

try:
    from . import holographic as hrr
except ImportError:
    import holographic as hrr  # type: ignore[no-redef]


# RRF smoothing constant (k=60 is the Hindsight production default).
_RRF_K = 60

# How many top-ranked facts each retrieval method contributes.
# Use a fixed floor so small-limit queries still get a meaningful overlap pool.
_CANDIDATE_POOL = 100


class FactRetriever:
    """Multi-strategy fact retrieval with RRF fusion and trust-weighted scoring."""

    def __init__(
        self,
        store: MemoryStore,
        temporal_decay_half_life: int = 0,  # days, 0 = disabled
        hrr_dim: int = 1024,
    ):
        self.store = store
        self.half_life = temporal_decay_half_life
        self.hrr_dim = hrr_dim

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

        pool = max(limit * 3, _CANDIDATE_POOL)

        # Independent rankings from each method.
        fts_ranking = self._fts_ranking(query, category, min_trust, pool)
        jaccard_ranking = self._jaccard_ranking(query, category, min_trust, pool)
        hrr_ranking = self._hrr_ranking(query, category, min_trust, pool)

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

            # Optional temporal decay.
            recency_boost = 1.0
            if self.half_life > 0:
                recency_boost = self._temporal_decay(
                    fact.get("updated_at") or fact.get("created_at")
                )

            fact["score"] = rrf_score * trust_boost * recency_boost
            scored.append(fact)

        scored.sort(key=lambda x: x["score"], reverse=True)
        results = scored[:limit]

        # Strip raw HRR bytes — callers expect JSON-serializable dicts.
        for fact in results:
            fact.pop("hrr_vector", None)
        return results

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

        # Encode entity as role-bound vector
        role_entity = hrr.encode_atom("__hrr_role_entity__", self.hrr_dim)
        entity_vec = hrr.encode_atom(entity.lower(), self.hrr_dim)
        probe_key = hrr.bind(entity_vec, role_entity)

        # Try category-specific bank first, then all facts
        if category:
            bank_name = f"cat:{category}"
            bank_row = conn.execute(
                "SELECT vector FROM memory_banks WHERE bank_name = ?",
                (bank_name,),
            ).fetchone()
            if bank_row:
                bank_vec = hrr.bytes_to_phases(bank_row["vector"])
                extracted = hrr.unbind(bank_vec, probe_key)
                # Use extracted signal to score individual facts
                return self._score_facts_by_vector(
                    extracted, category=category, limit=limit
                )

        # Score against individual fact vectors directly
        where = "WHERE hrr_vector IS NOT NULL"
        params: list = []
        if category:
            where += " AND category = ?"
            params.append(category)

        rows = conn.execute(
            f"""
            SELECT fact_id, content, category, tags, trust_score,
                   retrieval_count, helpful_count, created_at, updated_at,
                   hrr_vector
            FROM facts
            {where}
            """,
            params,
        ).fetchall()

        if not rows:
            # Final fallback: keyword search
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
        return scored[:limit]

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

        conn = self.store._conn

        # Encode entity as a bare atom (not role-bound — we want ANY structural match)
        entity_vec = hrr.encode_atom(entity.lower(), self.hrr_dim)

        # Get all facts with vectors
        where = "WHERE hrr_vector IS NOT NULL"
        params: list = []
        if category:
            where += " AND category = ?"
            params.append(category)

        rows = conn.execute(
            f"""
            SELECT fact_id, content, category, tags, trust_score,
                   retrieval_count, helpful_count, created_at, updated_at,
                   hrr_vector
            FROM facts
            {where}
            """,
            params,
        ).fetchall()

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
        return scored[:limit]

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

        conn = self.store._conn
        role_entity = hrr.encode_atom("__hrr_role_entity__", self.hrr_dim)

        # For each entity, compute what the bank "remembers" about it
        # by unbinding entity+role from each fact vector
        entity_residuals = []
        for entity in entities:
            entity_vec = hrr.encode_atom(entity.lower(), self.hrr_dim)
            probe_key = hrr.bind(entity_vec, role_entity)
            entity_residuals.append(probe_key)

        # Get all facts with vectors
        where = "WHERE hrr_vector IS NOT NULL"
        params: list = []
        if category:
            where += " AND category = ?"
            params.append(category)

        rows = conn.execute(
            f"""
            SELECT fact_id, content, category, tags, trust_score,
                   retrieval_count, helpful_count, created_at, updated_at,
                   hrr_vector
            FROM facts
            {where}
            """,
            params,
        ).fetchall()

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
        return scored[:limit]

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
        where = "WHERE f.hrr_vector IS NOT NULL"
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
    ) -> list[dict]:
        """Score facts by similarity to a target vector."""
        conn = self.store._conn

        where = "WHERE hrr_vector IS NOT NULL"
        params: list = []
        if category:
            where += " AND category = ?"
            params.append(category)

        rows = conn.execute(
            f"""
            SELECT fact_id, content, category, tags, trust_score,
                   retrieval_count, helpful_count, created_at, updated_at,
                   hrr_vector
            FROM facts
            {where}
            """,
            params,
        ).fetchall()

        scored = []
        for row in rows:
            fact = dict(row)
            fact_vec = hrr.bytes_to_phases(fact.pop("hrr_vector"))
            sim = hrr.similarity(target_vec, fact_vec)
            fact["score"] = (sim + 1.0) / 2.0 * fact["trust_score"]
            scored.append(fact)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

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

        params: list = []
        where_clauses = ["facts_fts MATCH ?", "f.trust_score >= ?"]
        params.append(query)
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
        """Return Jaccard token-overlap ranking as {fact_id: 1-indexed rank}."""
        conn = self.store._conn

        where = "WHERE trust_score >= ?"
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
        if not query_tokens:
            return {}

        scored = []
        for row in rows:
            fact_tokens = self._tokenize(row["content"]) | self._tokenize(row["tags"])
            similarity = self._jaccard_similarity(query_tokens, fact_tokens)
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

        where = "WHERE hrr_vector IS NOT NULL AND trust_score >= ?"
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

        where = f"WHERE fact_id IN ({placeholders}) AND trust_score >= ?"
        params.append(min_trust)

        if category:
            where += " AND category = ?"
            params.append(category)

        rows = conn.execute(
            f"""
            SELECT fact_id, content, category, tags, trust_score,
                   retrieval_count, helpful_count, created_at, updated_at,
                   hrr_vector
            FROM facts
            {where}
            """,
            params,
        ).fetchall()

        return [dict(r) for r in rows]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Simple whitespace tokenization with lowercasing.

        Strips common punctuation. No stemming/lemmatization (Phase 1).
        """
        if not text:
            return set()
        # Split on whitespace, lowercase, strip punctuation
        tokens = set()
        for word in text.lower().split():
            cleaned = word.strip(".,;:!?\"'()[]{}#@<>")
            if cleaned:
                tokens.add(cleaned)
        return tokens

    @staticmethod
    def _jaccard_similarity(set_a: set, set_b: set) -> float:
        """Jaccard similarity coefficient: |A ∩ B| / |A ∪ B|."""
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _temporal_decay(self, timestamp_str: str | None) -> float:
        """Exponential decay: 0.5^(age_days / half_life_days).

        Returns 1.0 if decay is disabled or timestamp is missing.
        """
        if not self.half_life or not timestamp_str:
            return 1.0

        try:
            if isinstance(timestamp_str, str):
                # Parse ISO format timestamp from SQLite
                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            else:
                ts = timestamp_str

            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
            if age_days < 0:
                return 1.0

            return math.pow(0.5, age_days / self.half_life)
        except (ValueError, TypeError):
            return 1.0
