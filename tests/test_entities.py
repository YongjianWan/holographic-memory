"""Direct unit tests for the entities helper module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from holographic import entities
from holographic.store import MemoryStore


class TestEntityExtraction:
    def test_extracts_quoted_terms(self) -> None:
        found = entities.extract_entities('"Python" is a language')
        assert "Python" in found

    def test_extracts_capitalised_multi_word_phrases(self) -> None:
        found = entities.extract_entities("John Doe works at Acme Corp")
        assert "John Doe" in found
        assert "Acme Corp" in found

    def test_rejects_long_quoted_phrases(self) -> None:
        long_quote = "a" * 50
        found = entities.extract_entities(f'"{long_quote}" is mentioned')
        assert long_quote not in found

    def test_numeric_signature_gate(self) -> None:
        # "K2" and "K2.7" share the digit 2 but have different version signatures.
        assert entities.numeric_signature("K2") != entities.numeric_signature("K2.7")


class TestEntityMatching:
    def test_exact_match(self) -> None:
        assert entities.entity_names_match("Python", "python", 0.85, 0.9)

    def test_punctuation_variants_match(self) -> None:
        assert entities.entity_names_match("K2.7", "K2_7", 0.85, 0.9)

    def test_hierarchical_names_do_not_match(self) -> None:
        # "K2" vs "K2.7" are series-vs-version, not writing variants.
        assert not entities.entity_names_match("K2", "K2.7", 0.85, 0.9)

    def test_unrelated_names_do_not_match(self) -> None:
        assert not entities.entity_names_match("Python", "JavaScript", 0.85, 0.9)


class TestEntityResolution:
    @pytest.fixture
    def store(self) -> MemoryStore:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        _store = MemoryStore(db_path=db_path)
        yield _store
        _store.close()
        Path(db_path).unlink(missing_ok=True)

    def test_resolve_entity_creates_new_row(self, store: MemoryStore) -> None:
        eid = entities.resolve_entity(store._conn, "Python")
        assert isinstance(eid, int)
        # Second call returns the same id.
        assert entities.resolve_entity(store._conn, "Python") == eid

    def test_resolve_entity_id_returns_none_for_unknown(self, store: MemoryStore) -> None:
        assert entities.resolve_entity_id(store._conn, "Rust") is None

    def test_resolve_entity_id_finds_by_alias(self, store: MemoryStore) -> None:
        eid = entities.resolve_entity(store._conn, "Python")
        store._conn.execute(
            "UPDATE entities SET aliases = ? WHERE entity_id = ?",
            ("Py, CPython", eid),
        )
        store._conn.commit()
        assert entities.resolve_entity_id(store._conn, "Py") == eid

    def test_link_fact_entity(self, store: MemoryStore) -> None:
        fact_id = store.add_fact('"Python" is great')
        eid = entities.resolve_entity(store._conn, "Python")
        entities.link_fact_entity(store._conn, fact_id, eid)
        row = store._conn.execute(
            "SELECT 1 FROM fact_entities WHERE fact_id = ? AND entity_id = ?",
            (fact_id, eid),
        ).fetchone()
        assert row is not None
