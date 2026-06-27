"""Tests for RRF-based search in FactRetriever."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from holographic import holographic as hrr
from holographic.retrieval import FactRetriever
from holographic.store import MemoryStore


@pytest.fixture
def store() -> MemoryStore:
    """Create a temporary MemoryStore for a single test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    _store = MemoryStore(db_path=db_path, default_trust=0.5, hrr_dim=256)
    yield _store
    _store.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def retriever(store: MemoryStore) -> FactRetriever:
    return FactRetriever(store=store, hrr_dim=256)


class TestRRFSearch:
    def test_search_returns_sorted_results(self, retriever: FactRetriever) -> None:
        retriever.store.add_fact("Python is a programming language", tags="language")
        retriever.store.add_fact("Python snakes are non-venomous", tags="animal")
        retriever.store.add_fact("I prefer Python for data science", tags="preference")

        results = retriever.search("Python programming", limit=5)

        assert len(results) == 3
        # Scores should be descending.
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)
        # The most relevant fact should be first.
        assert "programming language" in results[0]["content"]

    def test_rrf_uses_rank_not_raw_score(self, retriever: FactRetriever) -> None:
        """RRF score is bounded by the sum of reciprocal rank terms."""
        retriever.store.add_fact("Python is a programming language")
        retriever.store.add_fact("Java is a programming language")

        results = retriever.search("Python", limit=5)
        assert results
        # Three methods max contribution: 3 * 1/60 = 0.05 (plus boosts).
        # Any score should be positive and reasonably small for a small corpus.
        for r in results:
            assert 0.0 < r["score"] < 1.0

    def test_fact_ranked_high_by_single_method_is_recovered(
        self, retriever: FactRetriever
    ) -> None:
        """A fact that only HRR likes (same words, different order) should still appear."""
        retriever.store.add_fact("language programming Python is a")
        retriever.store.add_fact("completely unrelated astronomy fact")

        results = retriever.search("Python programming language", limit=5)
        contents = {r["content"] for r in results}
        assert "language programming Python is a" in contents

    def test_min_trust_filter(self, retriever: FactRetriever) -> None:
        fid = retriever.store.add_fact("Python is great")
        retriever.store.update_fact(fid, trust_delta=-0.5)  # trust drops to 0.0

        results = retriever.search("Python", min_trust=0.3)
        assert not results

    def test_numpy_unavailable_fallback(
        self, retriever: FactRetriever, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        retriever.store.add_fact("Python is a programming language")
        retriever.store.add_fact("I love Python")

        monkeypatch.setattr(hrr, "_HAS_NUMPY", False)
        # Re-encode query will fail if HRR path is taken; search must still work.
        results = retriever.search("Python", limit=5)
        assert len(results) == 2

    def test_category_filter(self, retriever: FactRetriever) -> None:
        retriever.store.add_fact("Python is a language", category="project")
        retriever.store.add_fact("Python snakes are reptiles", category="general")

        results = retriever.search("Python", category="project")
        assert len(results) == 1
        assert "language" in results[0]["content"]

    def test_search_records_retrieval_and_access_time(
        self, retriever: FactRetriever
    ) -> None:
        fact_id = retriever.store.add_fact("Python is a programming language")
        before = retriever.store._conn.execute(
            "SELECT retrieval_count, last_accessed_at FROM facts WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        assert before["retrieval_count"] == 0
        assert before["last_accessed_at"] is None

        results = retriever.search("Python programming", limit=5)
        assert results

        after = retriever.store._conn.execute(
            "SELECT retrieval_count, last_accessed_at FROM facts WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        assert after["retrieval_count"] == 1
        assert datetime.fromisoformat(after["last_accessed_at"]) is not None

    def test_search_results_include_provenance_summary(
        self, retriever: FactRetriever
    ) -> None:
        retriever.store._conn.execute(
            "INSERT INTO documents (doc_id, raw_text, text_hash, source) VALUES (1, 'doc', ?, 'doc')",
            ("a" * 64,),
        )
        retriever.store._conn.commit()
        fact_id = retriever.store.add_fact(
            "Python provenance is visible",
            source_doc_id=1,
            source_fact_id=3,
        )

        results = retriever.search("Python provenance", min_trust=0.0, limit=5)
        result = next(r for r in results if r["fact_id"] == fact_id)
        assert result["provenance"] == {
            "status": "known",
            "sources": [
                {
                    "doc_id": 1,
                    "source": "doc",
                    "source_fact_id": 3,
                    "relation": "origin",
                }
            ],
        }

    def test_recency_boost_is_derived_live_from_last_accessed_at(
        self, retriever: FactRetriever
    ) -> None:
        now = datetime.now(timezone.utc)
        recent = now.isoformat()
        old = (now - timedelta(days=180)).isoformat()
        expired = (now - timedelta(days=500)).isoformat()

        assert retriever._recency_boost(recent) == pytest.approx(1.0, abs=0.01)
        assert retriever._recency_boost(old) == pytest.approx(0.945, abs=0.01)
        assert retriever._recency_boost(expired) == pytest.approx(0.9, abs=0.01)
        assert retriever._recency_boost(None) == pytest.approx(0.9)

    def test_rrf_score_uses_live_recency_signal(
        self, retriever: FactRetriever, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recent_id = retriever.store.add_fact("recent candidate")
        old_id = retriever.store.add_fact("old candidate")
        now = datetime.now(timezone.utc)
        retriever.store._conn.execute(
            "UPDATE facts SET last_accessed_at = ? WHERE fact_id = ?",
            (now.isoformat(), recent_id),
        )
        retriever.store._conn.execute(
            "UPDATE facts SET last_accessed_at = ? WHERE fact_id = ?",
            ((now - timedelta(days=180)).isoformat(), old_id),
        )
        retriever.store._conn.commit()

        monkeypatch.setattr(
            retriever, "_fts_ranking",
            lambda *_args, **_kwargs: {recent_id: 1},
        )
        monkeypatch.setattr(
            retriever, "_jaccard_ranking",
            lambda *_args, **_kwargs: {old_id: 1},
        )
        monkeypatch.setattr(
            retriever, "_hrr_ranking",
            lambda *_args, **_kwargs: {},
        )

        results = retriever.search("candidate", min_trust=0.0, limit=2)
        assert [row["fact_id"] for row in results] == [recent_id, old_id]
        assert results[0]["score"] > results[1]["score"]


class TestEntityPrefilteredQueries:
    """probe/related/reason should pre-filter by linked entities to avoid full scans."""

    def test_probe_only_returns_linked_facts(self, retriever: FactRetriever) -> None:
        # Quoted terms become linked entities.
        retriever.store.add_fact('"Python" is a programming language', category='project')
        retriever.store.add_fact('"Coffee" is a morning drink', category='project')

        results = retriever.probe('Python', category='project')
        contents = {r['content'] for r in results}
        assert any('Python' in c for c in contents)
        assert all('Coffee' not in c for c in contents)

    def test_related_only_returns_linked_facts(self, retriever: FactRetriever) -> None:
        retriever.store.add_fact('"Python" is a programming language', category='project')
        retriever.store.add_fact('"Coffee" is a morning drink', category='project')

        results = retriever.related('Python', category='project')
        contents = {r['content'] for r in results}
        assert any('Python' in c for c in contents)
        assert all('Coffee' not in c for c in contents)

    def test_reason_prefers_facts_linked_to_all_entities(
        self, retriever: FactRetriever
    ) -> None:
        retriever.store.add_fact('"Python" and "Java" are languages', category='project')
        retriever.store.add_fact('"Python" is great', category='project')
        retriever.store.add_fact('"Java" runs everywhere', category='project')

        results = retriever.reason(['Python', 'Java'], category='project')
        assert results
        # The fact linked to both entities should rank first.
        assert '"Python" and "Java" are languages' in results[0]['content']

    def test_probe_unknown_entity_falls_back_to_search(
        self, retriever: FactRetriever
    ) -> None:
        retriever.store.add_fact('"Python" is a programming language', category='project')

        # Unknown entity falls back to RRF search without raising.
        results = retriever.probe('Rust', category='project')
        assert isinstance(results, list)


class TestRRFInternals:
    def test_ftsr_ranking_returns_one_indexed_ranks(
        self, retriever: FactRetriever
    ) -> None:
        retriever.store.add_fact("alpha beta gamma")
        retriever.store.add_fact("alpha beta delta")
        retriever.store.add_fact("unrelated")

        ranking = retriever._fts_ranking("alpha beta", None, 0.0, 10)
        assert len(ranking) == 2
        assert all(rank >= 1 for rank in ranking.values())

    def test_jaccard_ranking_ignores_zero_overlap(
        self, retriever: FactRetriever
    ) -> None:
        retriever.store.add_fact("foo bar baz")
        retriever.store.add_fact("qux quux corge")

        ranking = retriever._jaccard_ranking("foo bar", None, 0.0, 10)
        assert len(ranking) == 1
        assert retriever.store._conn.execute(
            "SELECT fact_id FROM facts WHERE content LIKE '%qux%'"
        ).fetchone()["fact_id"] not in ranking

    def test_hrr_ranking_empty_when_numpy_unavailable(
        self, retriever: FactRetriever, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hrr, "_HAS_NUMPY", False)
        assert retriever._hrr_ranking("anything", None, 0.0, 10) == {}
