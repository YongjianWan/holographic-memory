"""Tests for semantic fact consolidation in MemoryStore."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from holographic.store import MemoryStore, _LLMConsolidator


@pytest.fixture
def store() -> MemoryStore:
    """Create a temporary MemoryStore for a single test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    _store = MemoryStore(db_path=db_path, default_trust=0.5, hrr_dim=256)
    yield _store
    _store.close()
    Path(db_path).unlink(missing_ok=True)


class TestCandidateGrouping:
    def test_find_candidates_filters_generic_entities(self, store: MemoryStore) -> None:
        # Use double quotes so the regex entity extractor picks them up as entities.
        # Generic entity "Aiden" (appears in 3 facts)
        # Non-generic entity "Quantum" (appears in 2 facts)
        # Non-generic entity "Django" (appears in 1 fact)
        fid1 = store.add_fact('"Aiden" works on "Quantum"', category="project")
        fid2 = store.add_fact('"Aiden" works on "Django"', category="project")
        fid3 = store.add_fact('"Aiden" is a coder', category="project")

        # Aiden is linked to 3 facts. If generic_threshold = 3, Aiden is generic.
        # Check candidates. There should be NO candidates since they only share generic "Aiden"
        # and none of them share non-generic entities or >= 2 entities.
        clusters = store._find_consolidation_candidates(
            category="project",
            generic_threshold=3,
            max_cluster_size=6,
            min_jaccard=1.0,  # disable Jaccard shortcut for this generic-only test
        )
        assert not clusters

        # Now add a fact that shares non-generic "Quantum" with fid1
        fid4 = store.add_fact('"Mia" works on "Quantum" too', category="project")
        # fid1 and fid4 share non-generic "Quantum" (which is linked to 2 facts: fid1, fid4)
        clusters = store._find_consolidation_candidates(
            category="project",
            generic_threshold=3,
            max_cluster_size=6,
            min_jaccard=1.0,
        )
        assert len(clusters) == 1
        cluster_fids = {f["fact_id"] for f in clusters[0]}
        assert fid1 in cluster_fids
        assert fid4 in cluster_fids

    def test_adaptive_generic_threshold_for_small_stores(self, store: MemoryStore) -> None:
        # With 6 active facts, adaptive threshold = max(3, min(15, 6 // 6)) = 3.
        # "API" appears in 3 facts, so it should be treated as generic and not
        # create candidates on its own.
        store.add_fact('"API" returns weather data', category="project")
        store.add_fact('"API" unrelated fact about robots', category="project")
        store.add_fact('"API" controls warehouse lighting', category="project")
        store.add_fact('"Redis" caches data', category="project")
        store.add_fact('"Postgres" stores data', category="project")
        store.add_fact('"Vue" renders UI', category="project")

        clusters = store._find_consolidation_candidates(category="project")
        assert not clusters

        # Adding a non-generic shared entity creates a real candidate.
        store.add_fact('"Redis" powers the session cache', category="project")
        clusters = store._find_consolidation_candidates(category="project")
        assert len(clusters) == 1
        cluster_fids = {f["fact_id"] for f in clusters[0]}
        assert any("Redis" in f["content"] for f in clusters[0])


class TestLLMConsolidator:
    def test_parse_markdown_json_response(self) -> None:
        response_text = (
            "Some conversational header...\n"
            "```json\n"
            "{\n"
            '  "consolidations": [\n'
            '    {"input_ids": [12, 15], "consolidated_content": "Mia is Principal Dev"}\n'
            "  ]\n"
            "}\n"
            "```\n"
            "Some footer..."
        )
        consolidator = _LLMConsolidator(model_call=lambda p: "")
        result = consolidator._parse_response(response_text)
        assert len(result) == 1
        assert result[0]["input_ids"] == [12, 15]
        assert result[0]["consolidated_content"] == "Mia is Principal Dev"


class TestConsolidationTransaction:
    def test_failure_rolls_back_new_fact_entities_and_soft_deletes(
        self, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fid1 = store.add_fact('"Mia" is a Senior Dev', category="project")
        fid2 = store.add_fact('"Mia" became a Principal Dev', category="project")

        def mock_model(_prompt: str) -> str:
            return json.dumps({
                "consolidations": [{
                    "input_ids": [fid1, fid2],
                    "consolidated_content": '"Mia" is a Principal Dev',
                }]
            })

        def fail_vector(*_args, **_kwargs):
            raise RuntimeError("vector generation failed")

        monkeypatch.setattr(store, "_compute_hrr_vector", fail_vector)
        report = store.consolidate_facts(
            model_call=mock_model,
            category="project",
            generic_threshold=15,
        )

        assert report["facts_created"] == 0
        rows = store._conn.execute(
            "SELECT fact_id, content, merged_into FROM facts ORDER BY fact_id"
        ).fetchall()
        assert [row["fact_id"] for row in rows] == [fid1, fid2]
        assert all(row["merged_into"] is None for row in rows)

    def test_consolidate_facts_success(self, store: MemoryStore) -> None:
        # Add source document
        store._conn.execute("INSERT INTO documents (raw_text, text_hash) VALUES ('Mia profile', 'hash1')")
        store._conn.execute("INSERT INTO documents (raw_text, text_hash) VALUES ('Mia promo', 'hash1b')")
        docs = store._conn.execute("SELECT doc_id FROM documents ORDER BY doc_id").fetchall()
        doc_id = docs[0]["doc_id"]
        doc_id_2 = docs[1]["doc_id"]

        # Double quote "Mia" to extract it as an entity
        fid1 = store.add_fact(
            '"Mia" works as Senior Dev',
            category="project",
            tags="work,dev",
            source_doc_id=doc_id,
            source_fact_id=1,
            trust=0.8,
        )
        fid2 = store.add_fact(
            '"Mia" is promoted to Principal Dev',
            category="project",
            tags="work,promo",
            source_doc_id=doc_id_2,
            source_fact_id=1,
            trust=0.6,
        )

        # Set retrieval/helpful counts
        store._conn.execute("UPDATE facts SET retrieval_count = 10, helpful_count = 5 WHERE fact_id = ?", (fid1,))
        store._conn.execute("UPDATE facts SET retrieval_count = 5, helpful_count = 2 WHERE fact_id = ?", (fid2,))
        store._conn.commit()

        # Mock LLM consolidator call
        def mock_model(prompt: str) -> str:
            return json.dumps({
                "consolidations": [
                    {"input_ids": [fid1, fid2], "consolidated_content": '"Mia" is a Principal Dev (previously Senior Dev)'}
                ]
            })

        # Run consolidation (Mia is non-generic, threshold=15)
        report = store.consolidate_facts(model_call=mock_model, category="project", generic_threshold=15)
        assert report["facts_merged"] == 2
        assert report["facts_created"] == 1

        # Check the newly created fact
        new_fact = store._conn.execute(
            "SELECT fact_id, content, trust_score, retrieval_count, helpful_count, tags, source_doc_id "
            "FROM facts WHERE content LIKE '%Mia%is a Principal%'"
        ).fetchone()

        assert new_fact is not None
        assert new_fact["trust_score"] == 0.8  # max(0.8, 0.6)
        assert new_fact["retrieval_count"] == 15  # 10 + 5
        assert new_fact["helpful_count"] == 7  # 5 + 2
        # Tags merged and sorted
        assert new_fact["tags"] == "dev, promo, work"
        assert new_fact["source_doc_id"] == doc_id

        # Verify old facts are soft-deleted/superseded instead of physically deleted
        old_facts = store._conn.execute("SELECT fact_id, merged_into FROM facts WHERE fact_id IN (?, ?)", (fid1, fid2)).fetchall()
        assert len(old_facts) == 2
        for f in old_facts:
            assert f["merged_into"] == new_fact["fact_id"]

        provenance_rows = store._conn.execute(
            """
            SELECT fact_id, doc_id, source_fact_id
            FROM fact_provenance
            WHERE fact_id = ?
            ORDER BY doc_id, source_fact_id
            """,
            (new_fact["fact_id"],),
        ).fetchall()
        assert [tuple(row) for row in provenance_rows] == [
            (new_fact["fact_id"], doc_id, 1),
            (new_fact["fact_id"], doc_id_2, 1),
        ]
        assert (
            store._conn.execute(
                "SELECT COUNT(*) FROM fact_provenance WHERE fact_id IN (?, ?)",
                (fid1, fid2),
            ).fetchone()[0]
            == 0
        )

        # Verify entity links in fact_entities are preserved
        old_links = store._conn.execute("SELECT COUNT(*) FROM fact_entities WHERE fact_id IN (?, ?)", (fid1, fid2)).fetchone()[0]
        assert old_links > 0

        # Verify old facts are not returned by list_facts or search_facts
        listed = store.list_facts(category="project")
        listed_ids = {lf["fact_id"] for lf in listed}
        assert fid1 not in listed_ids
        assert fid2 not in listed_ids

    def test_consolidate_facts_integrity_error_collision(self, store: MemoryStore) -> None:
        # Disable write-time duplicate detection so that very similar facts are not merged at write time
        store.near_duplicate_threshold = 1.0

        fid1 = store.add_fact('"Mia" is a Dev', category="project", trust=0.7)
        fid2 = store.add_fact('"Mia" is promoted to Senior', category="project", trust=0.5)
        # Pre-existing fact representing the target consolidated content
        fid3 = store.add_fact('"Mia" is a Senior Dev', category="project", trust=0.6)

        def mock_model(prompt: str) -> str:
            return json.dumps({
                "consolidations": [
                    {"input_ids": [fid1, fid2], "consolidated_content": '"Mia" is a Senior Dev'}
                ]
            })

        report = store.consolidate_facts(model_call=mock_model, category="project", generic_threshold=15)
        # fid1 and fid2 are soft-deleted (merged = 2), but no new row is created (created = 0)
        # because "Mia is a Senior Dev" already existed. Instead, its metadata was updated.
        assert report["facts_merged"] == 2
        assert report["facts_created"] == 0

        # Check pre-existing fact has inherited metadata
        existing_fact = store._conn.execute(
            "SELECT fact_id, trust_score, merged_into FROM facts WHERE fact_id = ?", (fid3,)
        ).fetchone()
        assert existing_fact["trust_score"] == 0.7  # max(0.7, 0.5, old_value=0.6)
        assert existing_fact["merged_into"] is None  # Remains active

        # Verify old facts have merged_into pointing to fid3
        old_facts = store._conn.execute("SELECT fact_id, merged_into FROM facts WHERE fact_id IN (?, ?)", (fid1, fid2)).fetchall()
        assert len(old_facts) == 2
        for f in old_facts:
            assert f["merged_into"] == fid3

    def test_reactivate_soft_deleted_fact(self, store: MemoryStore) -> None:
        # Add a fact
        fid = store.add_fact('"Mia" is a Senior Dev', category="project", trust=0.6)

        # Add a dummy fact to point merged_into to, to satisfy foreign key constraint
        dummy_id = store.add_fact('"Mia" is a Principal Dev', category="project", trust=0.7)

        # Soft delete it manually by pointing merged_into to dummy_id
        store._conn.execute("UPDATE facts SET merged_into = ? WHERE fact_id = ?", (dummy_id, fid))
        store._conn.commit()


        # Verify it is no longer listed
        assert fid not in {f["fact_id"] for f in store.list_facts(category="project")}

        # Add the exact same fact again
        new_fid = store.add_fact('"Mia" is a Senior Dev', category="project", trust=0.8)
        assert new_fid == fid

        # Verify it is reactivated (merged_into is NULL)
        row = store._conn.execute("SELECT merged_into, trust_score FROM facts WHERE fact_id = ?", (fid,)).fetchone()
        assert row["merged_into"] is None
        assert row["trust_score"] == 0.8

        # Verify it is listed again
        assert fid in {f["fact_id"] for f in store.list_facts(category="project")}

    def test_soft_deleted_facts_hidden_from_all_read_paths(self, store: MemoryStore) -> None:
        from holographic.retrieval import FactRetriever
        retriever = FactRetriever(store=store, hrr_dim=256)

        # 1. Add source document
        store._conn.execute("INSERT INTO documents (raw_text, text_hash) VALUES ('Mia profile', 'hash2')")
        doc_id = store._conn.execute("SELECT doc_id FROM documents").fetchone()["doc_id"]

        # 2. Add facts (with entities to trigger co-occurrence and retrieval math)
        fid1 = store.add_fact('"Mia" works as Senior Dev', category="project", tags="work,dev", source_doc_id=doc_id, trust=0.8)
        fid2 = store.add_fact('"Mia" is promoted to Principal Dev', category="project", tags="work,promo", trust=0.6)

        # Ensure we have another active fact for contradiction testing
        store.add_fact('"Mia" is doing frontend tasks', category="project", tags="work", trust=0.7)

        # 3. Consolidate them (fid1 & fid2 are soft-deleted, merged into new fact)
        def mock_model(prompt: str) -> str:
            return json.dumps({
                "consolidations": [
                    {"input_ids": [fid1, fid2], "consolidated_content": '"Mia" is a Principal Dev (previously Senior Dev)'}
                ]
            })

        report = store.consolidate_facts(model_call=mock_model, category="project", generic_threshold=15)
        assert report["facts_merged"] == 2
        assert report["facts_created"] == 1

        # Get the new consolidated fact id
        new_fact = store._conn.execute(
            "SELECT fact_id FROM facts WHERE content LIKE '%Mia%is a Principal%'"
        ).fetchone()
        assert new_fact is not None
        new_fid = new_fact["fact_id"]

        # Verify old facts have merged_into pointing to new_fid
        assert store._conn.execute("SELECT merged_into FROM facts WHERE fact_id = ?", (fid1,)).fetchone()["merged_into"] == new_fid
        assert store._conn.execute("SELECT merged_into FROM facts WHERE fact_id = ?", (fid2,)).fetchone()["merged_into"] == new_fid

        # 4. Check all read paths to ensure fid1 and fid2 NEVER appear, but new_fid does
        
        # Path 1: store.search_facts
        search_results = store.search_facts("Mia Senior Dev", category="project", min_trust=0.1)
        search_ids = {f["fact_id"] for f in search_results}
        assert fid1 not in search_ids
        assert fid2 not in search_ids

        # Path 2: store.list_facts
        list_results = store.list_facts(category="project", min_trust=0.1)
        list_ids = {f["fact_id"] for f in list_results}
        assert fid1 not in list_ids
        assert fid2 not in list_ids

        # Path 3: store._find_near_duplicate (used on write path)
        dup_id = store._find_near_duplicate('"Mia" works as Senior Dev', category="project", threshold=0.99)
        assert dup_id != fid1
        assert dup_id != fid2

        # Path 4: store._find_consolidation_candidates
        candidates = store._find_consolidation_candidates(category="project")
        for cluster in candidates:
            cluster_ids = {f["fact_id"] for f in cluster}
            assert fid1 not in cluster_ids
            assert fid2 not in cluster_ids

        # Path 5: retriever.search (RRF search)
        rrf_results = retriever.search("Mia Senior Dev", category="project", min_trust=0.1)
        rrf_ids = {f["fact_id"] for f in rrf_results}
        assert fid1 not in rrf_ids
        assert fid2 not in rrf_ids

        # Path 6: retriever.probe
        probe_results = retriever.probe("Mia", category="project")
        probe_ids = {f["fact_id"] for f in probe_results}
        assert fid1 not in probe_ids
        assert fid2 not in probe_ids

        # Path 7: retriever.related
        related_results = retriever.related("Mia", category="project")
        related_ids = {f["fact_id"] for f in related_results}
        assert fid1 not in related_ids
        assert fid2 not in related_ids

        # Path 8: retriever.reason
        reason_results = retriever.reason(["Mia"], category="project")
        reason_ids = {f["fact_id"] for f in reason_results}
        assert fid1 not in reason_ids
        assert fid2 not in reason_ids

        # Path 9: retriever.contradict
        contradict_results = retriever.contradict(category="project", threshold=0.01)
        for pair in contradict_results:
            assert pair["fact_a"]["fact_id"] not in (fid1, fid2)
            assert pair["fact_b"]["fact_id"] not in (fid1, fid2)
