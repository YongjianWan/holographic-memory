"""Tests for document retention and atomic-fact extraction."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from holographic.store import (
    MemoryStore,
    _LLMExtractor,
    _LocalFallbackExtractor,
    _text_hash,
)


class TestRetainDocument:
    def test_retain_document_stores_raw_text_and_links_facts(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            text = "Python 3.12 was released in October 2023. It includes improved error messages."
            result = store.retain_document(text, source="test-doc")

            assert result["status"] == "ok"
            assert result["facts_added"] > 0
            assert result["extractor_kind"] == "fallback"
            assert len(result["fact_ids"]) == result["facts_added"]

            doc = store._conn.execute(
                "SELECT * FROM documents WHERE doc_id = ?", (result["doc_id"],)
            ).fetchone()
            assert doc is not None
            assert doc["raw_text"] == text
            assert doc["source"] == "test-doc"
            assert doc["text_hash"] == _text_hash(text)

            for fact_id in result["fact_ids"]:
                row = store._conn.execute(
                    "SELECT source_doc_id FROM facts WHERE fact_id = ?", (fact_id,)
                ).fetchone()
                assert row["source_doc_id"] == result["doc_id"]
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_retain_document_deduplicates_by_hash(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            text = "The quick brown fox jumps over the lazy dog."
            first = store.retain_document(text)
            second = store.retain_document(text)

            assert first["doc_id"] == second["doc_id"]

            count = store._conn.execute(
                "SELECT COUNT(*) FROM documents WHERE text_hash = ?",
                (_text_hash(text),),
            ).fetchone()[0]
            assert count == 1
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_retain_document_fallback_extractor_tags_facts(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            text = "A. First sentence here. B. Second sentence here."
            result = store.retain_document(text)

            assert result["facts_added"] >= 1
            for fact_id in result["fact_ids"]:
                row = store._conn.execute(
                    "SELECT trust_score FROM facts WHERE fact_id = ?", (fact_id,)
                ).fetchone()
                assert row["trust_score"] < store.default_trust
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_retain_document_orphan_on_extractor_failure(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            failing_extractor = _LLMExtractor(model_call=lambda _prompt: "")
            text = "Some article text that the LLM fails to extract."
            result = store.retain_document(text, extractor=failing_extractor)

            assert result["status"] == "document_stored_no_facts"
            assert result["facts_added"] == 0

            doc = store._conn.execute(
                "SELECT doc_id FROM documents WHERE text_hash = ?",
                (_text_hash(text),),
            ).fetchone()
            assert doc is not None
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_retain_document_llm_extractor_injection(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            def fake_llm(prompt: str) -> str:
                return "Fact one line.\nFact two line.\nshort"

            extractor = _LLMExtractor(model_call=fake_llm)
            text = "Prompt text."
            result = store.retain_document(text, extractor=extractor)

            assert result["extractor_kind"] == "llm"
            assert result["facts_added"] == 2

            for fact_id in result["fact_ids"]:
                row = store._conn.execute(
                    "SELECT source_doc_id, trust_score FROM facts WHERE fact_id = ?",
                    (fact_id,),
                ).fetchone()
                assert row["source_doc_id"] == result["doc_id"]
                assert row["trust_score"] == pytest.approx(store.default_trust)
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_add_fact_with_source_doc_id(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            store._conn.execute(
                "INSERT INTO documents (raw_text, text_hash) VALUES (?, ?)",
                ("doc", "d" * 64),
            )
            store._conn.commit()
            doc_id = store._conn.execute(
                "SELECT doc_id FROM documents WHERE text_hash = ?", ("d" * 64,)
            ).fetchone()["doc_id"]

            fact_id = store.add_fact("linked fact", source_doc_id=doc_id)
            row = store._conn.execute(
                "SELECT source_doc_id FROM facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()
            assert row["source_doc_id"] == doc_id
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_add_fact_warns_when_hrr_capacity_exceeded(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=64)
        try:
            with caplog.at_level(logging.WARNING, logger="store"):
                store.add_fact("word " * 20)
            assert any("HRR capacity warning" in m for m in caplog.messages)
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_add_fact_no_warning_for_small_fact(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=1024)
        try:
            with caplog.at_level(logging.WARNING, logger="store"):
                store.add_fact("short atomic fact")
            assert not any("HRR capacity warning" in m for m in caplog.messages)
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_retain_document_chunks_long_text(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            calls: list[int] = []

            def fake_llm(prompt: str) -> str:
                calls.append(1)
                return f"Chunk {len(calls)} fact."

            extractor = _LLMExtractor(model_call=fake_llm)
            # Repeating Chinese sentence with spaces; enough tokens to require >1 chunk.
            text = "这是一个测试句子。 " * 200
            result = store.retain_document(
                text, extractor=extractor, max_chunk_tokens=100
            )

            assert result["chunks_processed"] > 1
            assert result["facts_added"] > 1
            assert result["facts_added"] == result["chunks_processed"]
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)


class TestExtractors:
    def test_local_fallback_extractor_splits_sentences(self) -> None:
        extractor = _LocalFallbackExtractor(min_length=10)
        text = "First fact here. Second fact here! Third fact here?"
        facts = extractor.extract(text, "general")
        assert len(facts) == 3
        assert all(len(f) >= 10 for f in facts)

    def test_local_fallback_extractor_drops_short_and_duplicates(self) -> None:
        extractor = _LocalFallbackExtractor(min_length=10)
        text = "OK. Duplicate here. Duplicate here."
        facts = extractor.extract(text, "general")
        assert len(facts) == 1

    def test_llm_extractor_parses_lines(self) -> None:
        def fake(prompt: str) -> str:
            return "- First atomic fact.\n• Second atomic fact.\nno"

        extractor = _LLMExtractor(model_call=fake)
        facts = extractor.extract("prompt", "general")
        assert facts == ["First atomic fact.", "Second atomic fact."]

    def test_llm_extractor_returns_empty_on_failure(self) -> None:
        def boom(_: str) -> str:
            raise RuntimeError("api down")

        extractor = _LLMExtractor(model_call=boom)
        facts = extractor.extract("prompt", "general")
        assert facts == []
