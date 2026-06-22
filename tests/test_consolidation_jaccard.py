"""Tests for Jaccard-assisted consolidation candidate discovery."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from holographic.store import MemoryStore


@pytest.fixture
def store() -> MemoryStore:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    _store = MemoryStore(db_path=db_path, default_trust=0.5, hrr_dim=256)
    yield _store
    _store.close()
    Path(db_path).unlink(missing_ok=True)


class TestJaccardCandidateFiltering:
    def test_generic_entity_plus_high_jaccard_forms_candidate(self, store: MemoryStore) -> None:
        # "API" is generic (3 facts). The two target facts share only API
        # but have high token overlap, so they should form a candidate cluster.
        store.add_fact('"API" v1 returns user data in JSON format', category="project")
        store.add_fact('"API" v2 returns user data in JSON format', category="project")
        store.add_fact('"API" unrelated fact about weather', category="project")

        clusters = store._find_consolidation_candidates(
            category="project",
            generic_threshold=3,
            min_jaccard=0.3,
        )
        assert len(clusters) == 1
        assert len(clusters[0]) == 2

    def test_generic_entity_plus_low_jaccard_is_filtered(self, store: MemoryStore) -> None:
        # "API" is generic (3 facts). The two target facts share only API
        # and have almost no token overlap, so they should NOT form a candidate.
        store.add_fact('"API" v1 returns user data in JSON format', category="project")
        store.add_fact('"API" controls industrial robot arm movements', category="project")
        store.add_fact('"API" unrelated fact about weather', category="project")

        clusters = store._find_consolidation_candidates(
            category="project",
            generic_threshold=3,
            min_jaccard=0.3,
        )
        assert not clusters

    def test_non_generic_shared_entity_ignores_jaccard(self, store: MemoryStore) -> None:
        # "Redis" appears in 2 facts (non-generic). Even with low Jaccard,
        # shared non-generic entity should create a candidate.
        fid1 = store.add_fact('"Redis" is used for caching user sessions', category="project")
        fid2 = store.add_fact('"Redis" also powers our leaderboard', category="project")

        clusters = store._find_consolidation_candidates(
            category="project",
            generic_threshold=3,
            min_jaccard=0.9,  # very strict
        )
        assert len(clusters) == 1
        cluster_fids = {f["fact_id"] for f in clusters[0]}
        assert fid1 in cluster_fids
        assert fid2 in cluster_fids

    def test_two_shared_entities_still_requires_jaccard(self, store: MemoryStore) -> None:
        # Two shared generic entities alone are not enough; content must also overlap.
        fid1 = store.add_fact('"Redis" and "Postgres" are used by service A', category="project")
        fid2 = store.add_fact('"Redis" and "Postgres" are used by service B', category="project")

        # With strict Jaccard but high content overlap, they should still cluster.
        clusters = store._find_consolidation_candidates(
            category="project",
            generic_threshold=5,
            min_jaccard=0.9,
        )
        assert len(clusters) == 1
        cluster_fids = {f["fact_id"] for f in clusters[0]}
        assert fid1 in cluster_fids
        assert fid2 in cluster_fids

    def test_two_shared_entities_low_jaccard_is_filtered(self, store: MemoryStore) -> None:
        # Two shared generic entities with unrelated content should not cluster.
        store.add_fact('"Redis" and "Postgres" power the e-commerce backend', category="project")
        store.add_fact('"Redis" and "Postgres" named my pet hamsters', category="project")

        clusters = store._find_consolidation_candidates(
            category="project",
            generic_threshold=1,  # treat Redis/Postgres as generic
            min_jaccard=0.3,
        )
        assert not clusters
