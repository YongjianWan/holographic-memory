"""Tests for entity normalization in MemoryStore."""

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


class TestEntityNormalization:
    def test_no_entities_returns_empty_report(self, store: MemoryStore) -> None:
        report = store.normalize_entities()
        assert report["clusters_merged"] == 0
        assert report["entities_merged"] == 0
        assert report["facts_reindexed"] == 0

    def test_single_entity_returns_empty_report(self, store: MemoryStore) -> None:
        store.add_fact('I use "python" for scripting')
        report = store.normalize_entities()
        assert report["clusters_merged"] == 0

    def test_case_variants_already_resolved_at_write_time(
        self, store: MemoryStore
    ) -> None:
        """_resolve_entity is case-insensitive, so case variants never become
        separate entity rows in the first place."""
        store.add_fact('I use "python" for scripting')
        store.add_fact('"Python" is great')
        store.add_fact('"PYTHON" has many libraries')

        rows = store._conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()
        assert rows["c"] == 1

        report = store.normalize_entities()
        assert report["clusters_merged"] == 0
        assert report["entities_merged"] == 0

    def test_merge_punctuation_variants(self, store: MemoryStore) -> None:
        store.add_fact('"K2.7" is the model')
        store.add_fact('I prefer "K2_7"')
        store.add_fact('"K2-7" works well')

        report = store.normalize_entities()

        assert report["clusters_merged"] == 1
        assert report["entities_merged"] == 2

        canonical = store._conn.execute(
            "SELECT name, aliases FROM entities"
        ).fetchone()
        assert canonical is not None
        aliases = {a.strip().lower() for a in canonical["aliases"].split(",")}
        assert len(aliases) == 2
        assert "k2_7" in aliases or "k2-7" in aliases

    def test_does_not_merge_unrelated_entities(self, store: MemoryStore) -> None:
        store.add_fact('"Python" is a language')
        store.add_fact('"Rust" is fast')

        report = store.normalize_entities()

        assert report["clusters_merged"] == 0
        assert report["entities_merged"] == 0

        rows = store._conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()
        assert rows["c"] == 2

    def test_idempotent_second_run(self, store: MemoryStore) -> None:
        store.add_fact('"K2.7" is the model')
        store.add_fact('I prefer "K2_7"')

        first = store.normalize_entities()
        assert first["clusters_merged"] == 1

        second = store.normalize_entities()
        assert second["clusters_merged"] == 0
        assert second["entities_merged"] == 0

    def test_hrr_vectors_recomputed_after_merge(self, store: MemoryStore) -> None:
        store.add_fact('"K2.7" is the model')
        store.add_fact('I prefer "K2_7"')

        # Capture pre-merge HRR bytes.
        pre_rows = {
            r["fact_id"]: r["hrr_vector"]
            for r in store._conn.execute("SELECT fact_id, hrr_vector FROM facts").fetchall()
        }

        store.normalize_entities()

        post_rows = {
            r["fact_id"]: r["hrr_vector"]
            for r in store._conn.execute("SELECT fact_id, hrr_vector FROM facts").fetchall()
        }

        # After merge, both facts should share the same single entity and
        # at least one HRR vector should have changed (the fact whose entity
        # was renamed to the canonical name).
        changed = any(
            pre_rows[fid] != post_rows[fid] for fid in pre_rows
        )
        assert changed

    def test_canonical_selection_prefers_most_linked(self, store: MemoryStore) -> None:
        # Create many facts about "Python-Lang" and one about "Python_Lang".
        for _ in range(3):
            store.add_fact('"Python-Lang" is popular')
        store.add_fact('"Python_Lang" is easy to read')

        store.normalize_entities()

        canonical = store._conn.execute("SELECT name FROM entities").fetchone()
        assert canonical["name"] == "Python-Lang"
