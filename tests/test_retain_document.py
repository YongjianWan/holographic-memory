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

    def test_retain_document_reports_llm_call_failure(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            def fail_call(_prompt: str) -> str:
                raise RuntimeError("provider authentication failed")

            extractor = _LLMExtractor(model_call=fail_call)
            result = store.retain_document(
                "Document text that should remain retryable.",
                extractor=extractor,
            )

            assert result["status"] == "document_stored_extraction_failed"
            assert result["facts_added"] == 0
            assert result["extraction_errors"] == [
                {
                    "chunk": 1,
                    "error_type": "RuntimeError",
                    "message": "provider authentication failed",
                }
            ]
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

    def test_llm_extractor_rejects_dialogue_noise_and_meta_leaks(self) -> None:
        response = "\n".join(
            [
                "Claude说很晚了让用户快去睡觉。",
                "用户存在用技术开发来逃避投递简历的心理避难模式。",
                "我需要确保每条事实都是自包含的。",
                "Claude指出如果心里想走，Offer的最佳用法是直接走，不是回神思谈薪。",
                "赵传帅需在2026年6月18日前完成税收金融原型。",
                "Claude stated the user is collecting ammunition including workspace-bridge.",
            ]
        )
        extractor = _LLMExtractor(model_call=lambda _prompt: response)

        facts = extractor.extract("raw text", "project")

        assert facts == [
            "Claude指出如果心里想走，Offer的最佳用法是直接走，不是回神思谈薪。",
            "赵传帅需在2026年6月18日前完成税收金融原型。",
        ]

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

    def test_add_fact_records_cross_document_provenance_for_merged_fact(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            store._conn.execute(
                "INSERT INTO documents (doc_id, raw_text, text_hash, source) VALUES (1, 'doc 1', ?, 'doc-1')",
                ("a" * 64,),
            )
            store._conn.execute(
                "INSERT INTO documents (doc_id, raw_text, text_hash, source) VALUES (2, 'doc 2', ?, 'doc-2')",
                ("b" * 64,),
            )
            store._conn.commit()

            fact_id = store.add_fact(
                "The provenance system stores merge lineage.",
                source_doc_id=1,
                source_fact_id=1,
            )
            merged_id = store.add_fact(
                "The provenance system stores merge lineage.",
                source_doc_id=2,
                source_fact_id=1,
            )

            assert merged_id == fact_id
            rows = store._conn.execute(
                """
                SELECT fact_id, doc_id, source_fact_id, relation
                FROM fact_provenance
                WHERE fact_id = ?
                ORDER BY doc_id, source_fact_id
                """,
                (fact_id,),
            ).fetchall()
            assert [dict(row) for row in rows] == [
                {
                    "fact_id": fact_id,
                    "doc_id": 1,
                    "source_fact_id": 1,
                    "relation": "origin",
                },
                {
                    "fact_id": fact_id,
                    "doc_id": 2,
                    "source_fact_id": 1,
                    "relation": "merge",
                },
            ]
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_add_fact_keeps_same_document_distinct_source_fact_provenance(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            store._conn.execute(
                "INSERT INTO documents (doc_id, raw_text, text_hash, source) VALUES (1, 'doc', ?, 'doc')",
                ("a" * 64,),
            )
            store._conn.commit()

            fact_id = store.add_fact(
                "The same document can mention one fact twice.",
                source_doc_id=1,
                source_fact_id=1,
            )
            store.add_fact(
                "The same document can mention one fact twice.",
                source_doc_id=1,
                source_fact_id=2,
            )

            rows = store._conn.execute(
                """
                SELECT doc_id, source_fact_id
                FROM fact_provenance
                WHERE fact_id = ?
                ORDER BY source_fact_id
                """,
                (fact_id,),
            ).fetchall()
            assert [tuple(row) for row in rows] == [(1, 1), (1, 2)]
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_merge_repoints_provenance_and_ignores_duplicate_source_triples(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            store._conn.execute(
                "INSERT INTO documents (doc_id, raw_text, text_hash, source) VALUES (1, 'doc', ?, 'doc')",
                ("a" * 64,),
            )
            store._conn.execute(
                "INSERT INTO facts (fact_id, content, source_doc_id) VALUES (10, 'survivor', 1)"
            )
            store._conn.execute(
                "INSERT INTO facts (fact_id, content, source_doc_id) VALUES (11, 'merged', 1)"
            )
            store._conn.execute(
                """
                INSERT INTO fact_provenance (fact_id, doc_id, source_fact_id, relation)
                VALUES (10, 1, 1, 'origin'), (11, 1, 1, 'origin'), (11, 1, 2, 'origin')
                """
            )
            store._conn.commit()

            store._repoint_fact_provenance(11, 10)

            rows = store._conn.execute(
                """
                SELECT fact_id, doc_id, source_fact_id
                FROM fact_provenance
                ORDER BY fact_id, doc_id, source_fact_id
                """
            ).fetchall()
            assert [tuple(row) for row in rows] == [(10, 1, 1), (10, 1, 2)]
            assert (
                store._conn.execute(
                    "SELECT COUNT(*) FROM fact_provenance WHERE fact_id = 11"
                ).fetchone()[0]
                == 0
            )
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_list_and_search_return_derived_provenance_status(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            store._conn.execute(
                "INSERT INTO documents (doc_id, raw_text, text_hash, source) VALUES (1, 'doc', ?, 'doc')",
                ("a" * 64,),
            )
            store._conn.commit()

            known_id = store.add_fact(
                "Visible provenance fact",
                source_doc_id=1,
                source_fact_id=7,
            )
            legacy_id = store.add_fact("Legacy unknown provenance fact")

            by_id = {fact["fact_id"]: fact for fact in store.list_facts(limit=10)}
            assert by_id[known_id]["provenance"] == {
                "status": "known",
                "sources": [
                    {
                        "doc_id": 1,
                        "source": "doc",
                        "source_fact_id": 7,
                        "relation": "origin",
                    }
                ],
            }
            assert by_id[legacy_id]["provenance"] == {
                "status": "legacy_unknown",
                "sources": [],
            }
            assert (
                store._conn.execute(
                    "SELECT COUNT(*) FROM fact_provenance WHERE fact_id = ?",
                    (legacy_id,),
                ).fetchone()[0]
                == 0
            )

            search_results = store.search_facts("Visible provenance", min_trust=0.0)
            assert search_results[0]["fact_id"] == known_id
            assert search_results[0]["provenance"]["status"] == "known"
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

    def test_retain_document_rebuilds_category_bank_once_per_batch(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            calls: list[tuple[str, bool]] = []
            original_rebuild = store._rebuild_bank

            def spy_rebuild(category: str, *, commit: bool = True) -> None:
                calls.append((category, commit))
                original_rebuild(category, commit=commit)

            store._rebuild_bank = spy_rebuild  # type: ignore[method-assign]

            def fake_llm(_prompt: str) -> str:
                return "\n".join(
                    [
                        "Alpha service uses Redis cache.",
                        "Beta platform stores facts in SQLite.",
                        "Gamma client calls APIs through Axios.",
                    ]
                )

            result = store.retain_document(
                "Prompt text.",
                category="project",
                extractor=_LLMExtractor(model_call=fake_llm),
            )

            assert result["facts_added"] == 3
            assert calls == [("project", True)]
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

    def test_llm_extractor_propagates_provider_failure(self) -> None:
        def boom(_: str) -> str:
            raise RuntimeError("api down")

        extractor = _LLMExtractor(model_call=boom)
        with pytest.raises(RuntimeError, match="api down"):
            extractor.extract("prompt", "general")


class TestExtractionRuns:
    def test_retain_document_creates_and_tracks_run(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            text = "First long sentence to extract. Second long sentence to extract."
            # Fallback extractor returns sentence splits as facts.
            result = store.retain_document(text, source="doc-1")
            run_id = result.get("extraction_run_id")
            assert run_id is not None

            # Verify extraction run record
            run = store._conn.execute(
                "SELECT * FROM extraction_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            assert run is not None
            assert run["source_doc_id"] == result["doc_id"]
            assert run["extractor_version"] == "fallback-v1"
            assert len(run["prompt_hash"]) == 64
            assert run["status"] == "success"
            assert run["facts_returned"] == 2
            assert run["facts_added"] == 2
            assert run["facts_merged"] == 0

            # Verify fact association
            facts = store._conn.execute(
                "SELECT fact_id, content, extraction_run_id FROM facts WHERE extraction_run_id = ?",
                (run_id,),
            ).fetchall()
            assert len(facts) == 2
            for fact in facts:
                assert fact["extraction_run_id"] == run_id
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_retain_document_tracks_merges(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            text = "Unique fact statement that will be retained once."
            res1 = store.retain_document(text, source="doc-1")
            run_id_1 = res1["extraction_run_id"]

            run1 = store._conn.execute(
                "SELECT * FROM extraction_runs WHERE run_id = ?", (run_id_1,)
            ).fetchone()
            assert run1["facts_added"] == 1
            assert run1["facts_merged"] == 0

            # Retain again - exact duplicate triggers unique constraint and updates/merges.
            res2 = store.retain_document(text, source="doc-2")
            run_id_2 = res2["extraction_run_id"]

            run2 = store._conn.execute(
                "SELECT * FROM extraction_runs WHERE run_id = ?", (run_id_2,)
            ).fetchone()
            assert run2["facts_added"] == 0
            assert run2["facts_merged"] == 1
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_extraction_runs_failed(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            def boom(_: str) -> str:
                raise RuntimeError("forced extraction failure")

            extractor = _LLMExtractor(model_call=boom)
            result = store.retain_document("Some text", extractor=extractor)
            assert result["status"] == "document_stored_extraction_failed"
            assert len(result["extraction_errors"]) == 1

            # Check that a failed run was recorded
            run = store._conn.execute(
                "SELECT * FROM extraction_runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
            assert run is not None
            assert run["status"] == "failed"
            assert run["extractor_version"] == "llm-v1"
            assert run["facts_added"] == 0
            assert run["facts_merged"] == 0
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)
