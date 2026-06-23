"""Tests for write-time near-duplicate detection and merge."""

from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from holographic.store import MemoryStore


@pytest.fixture
def store() -> MemoryStore:
    """Create a temporary MemoryStore for a single test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    _store = MemoryStore(
        db_path=db_path,
        default_trust=0.5,
        hrr_dim=256,
        near_duplicate_threshold=0.8,
    )
    yield _store
    _store.close()
    Path(db_path).unlink(missing_ok=True)


class TestWriteDeduplication:
    def test_update_fact_rolls_back_content_and_entities_on_vector_failure(
        self, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fact_id = store.add_fact('"Python" is used for scripting')

        def fail_vector(*_args, **_kwargs):
            raise RuntimeError("vector generation failed")

        monkeypatch.setattr(store, "_compute_hrr_vector", fail_vector)
        with pytest.raises(RuntimeError, match="vector generation failed"):
            store.update_fact(fact_id, content='"Rust" is used for systems work')

        row = store._conn.execute(
            "SELECT content FROM facts WHERE fact_id = ?", (fact_id,)
        ).fetchone()
        assert row["content"] == '"Python" is used for scripting'
        entities = {
            row["name"]
            for row in store._conn.execute(
                """
                SELECT e.name
                FROM entities e
                JOIN fact_entities fe ON fe.entity_id = e.entity_id
                WHERE fe.fact_id = ?
                """,
                (fact_id,),
            ).fetchall()
        }
        assert entities == {"Python"}

    def test_two_connections_atomically_deduplicate_near_duplicate_writes(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "shared.db"
        store_a = MemoryStore(db_path=db_path, hrr_dim=256)
        store_b = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        store_a.add_fact,
                        "Python is a great programming language",
                    ),
                    pool.submit(
                        store_b.add_fact,
                        "Python is a great programming language indeed",
                    ),
                ]
                ids = [future.result(timeout=10) for future in futures]

            assert ids[0] == ids[1]
            assert store_a._conn.execute(
                "SELECT COUNT(*) FROM facts"
            ).fetchone()[0] == 1
        finally:
            store_a.close()
            store_b.close()

    def test_add_fact_rolls_back_all_rows_when_vector_generation_fails(
        self, store: MemoryStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_vector(*_args, **_kwargs):
            raise RuntimeError("vector generation failed")

        monkeypatch.setattr(store, "_compute_hrr_vector", fail_vector)

        with pytest.raises(RuntimeError, match="vector generation failed"):
            store.add_fact('"Python" is used for scripting')

        assert store._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM fact_entities").fetchone()[0] == 0

    def test_near_duplicate_wording_is_merged(self, store: MemoryStore) -> None:
        id1 = store.add_fact("Python is a great programming language")
        id2 = store.add_fact("Python is a great programming language indeed")

        assert id1 == id2
        count = store._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        assert count == 1

    def test_different_content_creates_new_fact(self, store: MemoryStore) -> None:
        id1 = store.add_fact("Python is a programming language")
        id2 = store.add_fact("Rust is a systems programming language")

        assert id1 != id2
        count = store._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        assert count == 2

    def test_exact_duplicate_returns_existing_id(self, store: MemoryStore) -> None:
        content = "Exact duplicate content"
        id1 = store.add_fact(content)
        id2 = store.add_fact(content)

        assert id1 == id2
        count = store._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        assert count == 1

    def test_low_trust_duplicate_still_merged(self, store: MemoryStore) -> None:
        id1 = store.add_fact("Python is a programming language")
        store.update_fact(id1, trust_delta=-0.5)  # trust drops to 0.0

        id2 = store.add_fact("Python is a programming language indeed")

        assert id1 == id2
        row = store._conn.execute(
            "SELECT trust_score FROM facts WHERE fact_id = ?", (id1,)
        ).fetchone()
        # trust should recover to at least default_trust after merge
        assert row["trust_score"] == pytest.approx(0.5)

    def test_find_near_duplicate_does_not_increment_retrieval_count(
        self, store: MemoryStore
    ) -> None:
        id1 = store.add_fact("Python is a programming language")
        store.add_fact("Python is a great programming language")

        row = store._conn.execute(
            "SELECT retrieval_count FROM facts WHERE fact_id = ?", (id1,)
        ).fetchone()
        # Only the merge increments retrieval_count by 1.
        assert row["retrieval_count"] == 1

    def test_tags_are_union_merged(self, store: MemoryStore) -> None:
        id1 = store.add_fact(
            "Python is a great programming language", tags="python, language"
        )
        store.add_fact(
            "Python is a great programming language indeed", tags="language, favorite"
        )

        row = store._conn.execute(
            "SELECT tags FROM facts WHERE fact_id = ?", (id1,)
        ).fetchone()
        assert set(row["tags"].split(", ")) == {"favorite", "language", "python"}

    def test_more_specific_content_replaces_old_wording(self, store: MemoryStore) -> None:
        id1 = store.add_fact('I use "python" for scripting')
        store.add_fact('I use "python" 3.12 for scripting')

        row = store._conn.execute(
            "SELECT content FROM facts WHERE fact_id = ?", (id1,)
        ).fetchone()
        assert "3.12" in row["content"]

    def test_merge_recomputes_entities_and_hrr(self, store: MemoryStore) -> None:
        id1 = store.add_fact('I use "python" for scripting and other tasks')
        store.add_fact('I use "python" and "rust" for scripting and other tasks')

        entity_count = store._conn.execute(
            """
            SELECT COUNT(*) AS c FROM fact_entities fe
            JOIN entities e ON e.entity_id = fe.entity_id
            WHERE fe.fact_id = ?
            """,
            (id1,),
        ).fetchone()["c"]
        assert entity_count == 2

        # HRR vector should have been recomputed (non-null when numpy available).
        from holographic import holographic as hrr
        if hrr._HAS_NUMPY:
            row = store._conn.execute(
                "SELECT hrr_vector FROM facts WHERE fact_id = ?", (id1,)
            ).fetchone()
            assert row["hrr_vector"] is not None

    def test_content_uniqueness_collision_falls_back_to_metadata_only_merge(
        self, store: MemoryStore
    ) -> None:
        # Set up two facts with different content.
        id_a = store.add_fact("Python is great")
        id_b = store.add_fact("Python 3.12 is great")

        # Directly attempt to merge id_a into the exact content of id_b.
        # This simulates a race/edge case where _find_near_duplicate returned id_a
        # but the new wording collides with id_b's UNIQUE content.
        store._merge_into(id_a, "Python 3.12 is great", "extra")

        row_a = store._conn.execute(
            "SELECT content, tags FROM facts WHERE fact_id = ?", (id_a,)
        ).fetchone()
        # Content must stay as id_a's original wording to avoid UNIQUE violation.
        assert row_a["content"] == "Python is great"
        # Metadata should still have been merged.
        assert "extra" in row_a["tags"]

    def test_malformed_or_empty_content_does_not_crash(
        self, store: MemoryStore
    ) -> None:
        # Content that tokenizes to nothing should simply not match anything.
        id1 = store.add_fact("!!! ???")
        id2 = store.add_fact("??? !!!")

        # These are not near-duplicates because they have no tokens.
        assert id1 != id2
