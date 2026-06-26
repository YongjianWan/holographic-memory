"""Semantic fact consolidation.

Finds clusters of facts that likely describe the same subject and uses an
LLM to merge them. The merged fact replaces the old ones via soft-deletion
(``merged_into``) so that no history is lost.

Why this is separate from ``store.py``:
- Consolidation is a higher-level memory-hygiene operation, not core CRUD.
- It mixes graph algorithms (candidate discovery) with LLM calls, making it
  a natural boundary for a dedicated module.
- It lets ``MemoryStore`` expose only thin forwarding methods.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from .store import MemoryStore

logger = logging.getLogger(__name__)

try:
    from . import entities
    from .extractors import _LLMConsolidator
    from . import holographic as hrr
except ImportError:  # pragma: no cover - supports standalone import during dev
    import entities  # type: ignore[no-redef]
    from extractors import _LLMConsolidator  # type: ignore[no-redef]
    import holographic as hrr  # type: ignore[no-redef]


def find_consolidation_candidates(
    conn: sqlite3.Connection,
    category: str | None = None,
    generic_threshold: int | None = None,
    max_cluster_size: int = 6,
    min_jaccard: float = 0.3,
) -> list[list[dict]]:
    """Find clusters of facts that share entities and are candidates for consolidation.

    Excludes high-frequency generic entities from generating single-entity matches
    unless the facts share at least 2 entities total or have sufficient token overlap.

    When ``generic_threshold`` is None, it is computed adaptively as
    ``max(3, min(15, active_facts // 6))`` so small memory stores are not
    dominated by a few moderately frequent terms.

    For pairs that only share a single generic entity, an additional
    Jaccard token-overlap check (default 0.3) filters out semantically
    unrelated facts.
    """
    # 1. Fetch all fact-entity associations.
    params: list = []
    where_clauses = ["f.merged_into IS NULL"]
    if category is not None:
        where_clauses.append("f.category = ?")
        params.append(category)

    sql = f"""
        SELECT fe.fact_id, fe.entity_id, f.content, f.category, f.tags, f.trust_score
        FROM fact_entities fe
        JOIN facts f ON fe.fact_id = f.fact_id
        WHERE {" AND ".join(where_clauses)}
    """
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return []

    # 2. Build mapping and entity frequencies.
    fact_to_entities: dict[int, set[int]] = defaultdict(set)
    entity_to_facts: dict[int, set[int]] = defaultdict(set)
    fact_data: dict[int, dict] = {}

    for row in rows:
        fid = row["fact_id"]
        eid = row["entity_id"]
        fact_to_entities[fid].add(eid)
        entity_to_facts[eid].add(fid)
        if fid not in fact_data:
            fact_data[fid] = {
                "fact_id": fid,
                "content": row["content"],
                "category": row["category"],
                "tags": row["tags"],
                "trust_score": row["trust_score"],
            }

    # Identify generic entities.
    if generic_threshold is None:
        active_facts = len(fact_data)
        generic_threshold = max(3, min(15, active_facts // 6))
    generic_entities = {
        eid for eid, fids in entity_to_facts.items() if len(fids) >= generic_threshold
    }

    # Pre-compute token sets for Jaccard filtering (exclude stop-words).
    fact_tokens: dict[int, set[str]] = {}
    for fid, data in fact_data.items():
        fact_tokens[fid] = {
            t for t in hrr.tokenize_text(data["content"])
            if t not in entities._ENGLISH_STOPWORDS
        }

    def _jaccard(a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    # 3. Find candidate pairs based on co-occurrence rules.
    shared_entities_count: dict[tuple[int, int], int] = defaultdict(int)
    for eid, fids in entity_to_facts.items():
        fids_list = sorted(fids)
        for i in range(len(fids_list)):
            for j in range(i + 1, len(fids_list)):
                pair = (fids_list[i], fids_list[j])
                shared_entities_count[pair] += 1

    candidate_pairs = set()
    for (f1, f2), shared_count in shared_entities_count.items():
        shared_ents = fact_to_entities[f1] & fact_to_entities[f2]
        shared_non_generic = shared_ents - generic_entities
        # Strong signal: sharing >= 1 non-generic entity always qualifies.
        if len(shared_non_generic) >= 1:
            candidate_pairs.add((f1, f2))
            continue
        # Generic-only signals require enough token overlap to avoid
        # clustering unrelated facts that merely mention the same buzzwords.
        if _jaccard(fact_tokens[f1], fact_tokens[f2]) >= min_jaccard:
            candidate_pairs.add((f1, f2))

    # 4. Group candidate pairs into connected components (BFS).
    adj = defaultdict(list)
    for f1, f2 in candidate_pairs:
        adj[f1].append(f2)
        adj[f2].append(f1)

    visited = set()
    clusters: list[list[dict]] = []

    for start_node in sorted(adj.keys()):
        if start_node not in visited:
            component = []
            queue = [start_node]
            visited.add(start_node)
            while queue:
                node = queue.pop(0)
                component.append(node)
                for neighbor in adj[node]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            # Sort to make clustering output deterministic.
            component.sort()
            for i in range(0, len(component), max_cluster_size):
                chunk = component[i : i + max_cluster_size]
                # Convert fact IDs to full fact dicts.
                clusters.append([fact_data[fid] for fid in chunk])

    return clusters


def consolidate_facts(
    store: MemoryStore,
    model_call: Callable[[str], str],
    category: str | None = None,
    generic_threshold: int | None = None,
    max_cluster_size: int = 6,
    min_jaccard: float = 0.3,
    clusters: list[list[dict]] | None = None,
) -> dict:
    """Run semantic consolidation using LLM on clusters of facts.

    When ``clusters`` is provided, it is used directly instead of running
    the internal entity-based discovery. This is useful for controlled
    trials or external clusterers.
    """
    if clusters is None:
        clusters = find_consolidation_candidates(
            conn=store._conn,
            category=category,
            generic_threshold=generic_threshold,
            max_cluster_size=max_cluster_size,
            min_jaccard=min_jaccard,
        )
    if not clusters:
        return {
            "clusters_processed": 0,
            "facts_processed": 0,
            "facts_merged": 0,
            "facts_created": 0,
            "status": "no_candidates",
        }

    consolidator = _LLMConsolidator(model_call)
    facts_processed = sum(len(c) for c in clusters)
    facts_merged = 0
    facts_created = 0
    affected_categories: set[str] = set()

    for cluster in clusters:
        consolidations = consolidator.consolidate(cluster)
        if not consolidations:
            continue

        with store._lock:
            cluster_facts_merged = 0
            cluster_facts_created = 0
            cluster_categories: set[str] = set()
            try:
                if store._conn.in_transaction:
                    store._conn.commit()
                store._conn.execute("BEGIN IMMEDIATE")

                for item in consolidations:
                    input_ids: list[int] = item.get("input_ids", [])
                    consolidated_content: str = item.get("consolidated_content", "").strip()

                    if not input_ids or not consolidated_content:
                        continue

                    # Load input facts details from database to verify and merge metadata.
                    placeholders = ",".join("?" * len(input_ids))
                    rows = store._conn.execute(
                        f"SELECT fact_id, trust_score, retrieval_count, helpful_count, category, tags, source_doc_id "
                        f"FROM facts WHERE fact_id IN ({placeholders})",
                        input_ids,
                    ).fetchall()

                    if not rows:
                        continue

                    # Check category and build merged metadata.
                    fact_category = rows[0]["category"]
                    cluster_categories.add(fact_category)

                    merged_trust = max(r["trust_score"] for r in rows)
                    merged_retrieval_count = sum(r["retrieval_count"] for r in rows)
                    merged_helpful_count = sum(r["helpful_count"] for r in rows)

                    # Merge tags.
                    tags_set: set[str] = set()
                    for r in rows:
                        if r["tags"]:
                            tags_set.update(t.strip() for t in r["tags"].split(",") if t.strip())
                    merged_tags = ", ".join(sorted(tags_set))

                    # Source doc id.
                    merged_source_doc_id = None
                    for r in rows:
                        if r["source_doc_id"] is not None:
                            merged_source_doc_id = r["source_doc_id"]
                            break

                    # Insert consolidated fact.
                    new_fact_id = None
                    try:
                        cur = store._conn.execute(
                            """
                            INSERT INTO facts (content, category, tags, trust_score, retrieval_count, helpful_count, source_doc_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                consolidated_content,
                                fact_category,
                                merged_tags,
                                merged_trust,
                                merged_retrieval_count,
                                merged_helpful_count,
                                merged_source_doc_id,
                            ),
                        )
                        new_fact_id = cur.lastrowid
                        cluster_facts_created += 1
                    except sqlite3.IntegrityError:
                        # Consolidated content already exists, merge metadata into the existing row.
                        row = store._conn.execute(
                            "SELECT fact_id, trust_score, retrieval_count, helpful_count, tags, source_doc_id, merged_into "
                            "FROM facts WHERE content = ?",
                            (consolidated_content,),
                        ).fetchone()
                        if row:
                            new_fact_id = row["fact_id"]
                            updated_trust = max(row["trust_score"], merged_trust)
                            updated_ret_count = row["retrieval_count"] + merged_retrieval_count
                            updated_help_count = row["helpful_count"] + merged_helpful_count

                            existing_tags = set(t.strip() for t in (row["tags"] or "").split(",") if t.strip())
                            existing_tags.update(tags_set)
                            updated_tags = ", ".join(sorted(existing_tags))

                            store._conn.execute(
                                """
                                UPDATE facts
                                SET trust_score = ?, retrieval_count = ?, helpful_count = ?, tags = ?, source_doc_id = ?, merged_into = NULL, updated_at = CURRENT_TIMESTAMP
                                WHERE fact_id = ?
                                """,
                                (
                                    updated_trust,
                                    updated_ret_count,
                                    updated_help_count,
                                    updated_tags,
                                    row["source_doc_id"] or merged_source_doc_id,
                                    new_fact_id,
                                ),
                            )

                    # Extract entities and link them to the new fact.
                    if new_fact_id is not None:
                        entity_names = entities.extract_entities(consolidated_content)
                        for name in entity_names:
                            entity_id = entities.resolve_entity(
                                store._conn, name, commit=False
                            )
                            entities.link_fact_entity(
                                store._conn, new_fact_id, entity_id, commit=False
                            )
                        # Warn and generate HRR vector.
                        store._warn_hrr_capacity(consolidated_content, entity_names)
                        store._compute_hrr_vector(
                            new_fact_id, consolidated_content, commit=False
                        )

                    # Set merged_into for old facts instead of deleting them.
                    # Preserve entity links in fact_entities.
                    for old_id in input_ids:
                        # Don't merge if the old id is actually the new_fact_id.
                        if old_id == new_fact_id:
                            continue
                        store._conn.execute(
                            "UPDATE facts SET merged_into = ? WHERE fact_id = ?",
                            (new_fact_id, old_id),
                        )
                        store._repoint_fact_provenance(old_id, new_fact_id)
                        cluster_facts_merged += 1

                for cat in cluster_categories:
                    store._rebuild_bank(cat, commit=False)
                store._conn.commit()
            except Exception as e:
                store._conn.rollback()
                logger.error("Consolidation batch failed and was rolled back: %s", e)
                continue

            facts_created += cluster_facts_created
            facts_merged += cluster_facts_merged
            affected_categories.update(cluster_categories)

    return {
        "clusters_processed": len(clusters),
        "facts_processed": facts_processed,
        "facts_merged": facts_merged,
        "facts_created": facts_created,
        "status": "ok",
    }
