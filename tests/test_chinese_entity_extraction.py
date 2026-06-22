"""Tests for Chinese entity extraction improvements."""

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


class TestChineseEntityExtraction:
    def test_extracts_chinese_quoted_terms(self, store: MemoryStore) -> None:
        store.add_fact('「全息记忆」使用 HRR 向量。')
        rows = store._conn.execute("SELECT name FROM entities").fetchall()
        names = {r["name"] for r in rows}
        assert "全息记忆" in names

    def test_extracts_tech_suffix_entities(self, store: MemoryStore) -> None:
        store.add_fact('AI 智能检索与公文写作系统使用 Vue.js 前端。')
        rows = store._conn.execute("SELECT name FROM entities").fetchall()
        names = {r["name"] for r in rows}
        assert any(name.endswith("系统") for name in names)
        assert "Vue.js" in names

    def test_extracts_english_acronyms(self, store: MemoryStore) -> None:
        store.add_fact('We use FTS5 for search and HRR for vectors.')
        rows = store._conn.execute("SELECT name FROM entities").fetchall()
        names = {r["name"] for r in rows}
        assert "FTS5" in names
        assert "HRR" in names

    def test_does_not_extract_bare_generic_prefix(self, store: MemoryStore) -> None:
        store.add_fact('这个系统很好，那个平台也不错。')
        rows = store._conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()
        assert rows["c"] == 0

    def test_preserves_existing_english_behavior(self, store: MemoryStore) -> None:
        store.add_fact('"Python" is used with "Django" framework.')
        rows = store._conn.execute("SELECT name FROM entities").fetchall()
        names = {r["name"] for r in rows}
        assert "Python" in names
        assert "Django" in names
