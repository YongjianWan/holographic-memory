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

        # Aiden is linked to 3 facts. If generic_threshold = 2, Aiden is generic.
        # Check candidates. There should be NO candidates since they only share generic "Aiden"
        # and none of them share non-generic entities or >= 2 entities.
        clusters = store._find_consolidation_candidates(
            category="project",
            generic_threshold=2,
            max_cluster_size=6,
        )
        assert not clusters

        # Now add a fact that shares non-generic "Quantum" with fid1
        fid4 = store.add_fact('"Mia" works on "Quantum" too', category="project")
        # fid1 and fid4 share non-generic "Quantum" (which is linked to 2 facts: fid1, fid4)
        clusters = store._find_consolidation_candidates(
            category="project",
            generic_threshold=2,
            max_cluster_size=6,
        )
        assert len(clusters) == 1
        cluster_fids = {f["fact_id"] for f in clusters[0]}
        assert fid1 in cluster_fids
        assert fid4 in cluster_fids


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
    def test_consolidate_facts_success(self, store: MemoryStore) -> None:
        # Add source document
        store._conn.execute("INSERT INTO documents (raw_text, text_hash) VALUES ('Mia profile', 'hash1')")
        doc_id = store._conn.execute("SELECT doc_id FROM documents").fetchone()["doc_id"]

        # Double quote "Mia" to extract it as an entity
        fid1 = store.add_fact('"Mia" works as Senior Dev', category="project", tags="work,dev", source_doc_id=doc_id, trust=0.8)
        fid2 = store.add_fact('"Mia" is promoted to Principal Dev', category="project", tags="work,promo", trust=0.6)

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
        report = store.consolidate_facts(model_call=mock_model, category="project")
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

        report = store.consolidate_facts(model_call=mock_model, category="project")
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

