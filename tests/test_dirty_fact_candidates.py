"""Tests for the read-only dirty fact candidate report."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


SCRIPT = Path(__file__).parent / "scripts" / "run_dirty_fact_candidates.py"
SPEC = importlib.util.spec_from_file_location("dirty_fact_candidates", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dirty = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dirty)


def test_detect_candidate_reasons_marks_extractor_self_talk() -> None:
    reasons = dirty.detect_candidate_reasons("我需要确保每条事实都是自包含的。")

    assert any(reason["severity"] == "likely_dirty" for reason in reasons)
    assert any("extraction_meta" in reason["reason"] for reason in reasons)


def test_detect_candidate_reasons_keeps_short_domain_fact_clean() -> None:
    reasons = dirty.detect_candidate_reasons(
        "招商匹配包括落地区域、政策、人才、科技支撑。"
    )

    assert reasons == []


def test_detect_candidate_reasons_marks_long_fact_for_review_only() -> None:
    content = (
        "Policy evaluation platform uses user entry, business process, Agent "
        "application, self-developed Agent Factory core, and underlying data "
        "resource layers while preserving implemented pre-evaluation and report "
        "Q&A modules for traceable project architecture decisions."
    )

    reasons = dirty.detect_candidate_reasons(content, review_length=120)

    assert {reason["severity"] for reason in reasons} == {"review"}
    assert any("long_atomicity_check" in reason["reason"] for reason in reasons)


def test_build_report_scans_active_facts_only(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE documents (
                doc_id INTEGER PRIMARY KEY,
                source TEXT
            );
            CREATE TABLE facts (
                fact_id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                trust_score REAL DEFAULT 0.5,
                source_doc_id INTEGER,
                merged_into INTEGER
            );
            INSERT INTO documents(doc_id, source) VALUES (1, 'doc.md');
            INSERT INTO facts(fact_id, content, source_doc_id, merged_into)
            VALUES
                (1, '我需要确保每条事实都是自包含的。', 1, NULL),
                (2, '招商匹配包括落地区域、政策、人才、科技支撑。', 1, NULL),
                (3, 'Claude说很晚了让用户快去睡觉。', 1, 999999);
            """
        )
        conn.commit()
    finally:
        conn.close()

    report = dirty.build_report(db_path, db_path)

    assert report["active_facts_scanned"] == 2
    assert report["candidate_count"] == 1
    assert report["candidates"][0]["fact_id"] == 1


def test_write_reports_includes_manual_verdict_column(tmp_path: Path) -> None:
    report = {
        "generated_at": "2026-06-27T18:30:00",
        "source_db": "source.db",
        "snapshot_db": "snapshot.db",
        "read_only": True,
        "review_length": 240,
        "active_facts_scanned": 1,
        "candidate_count": 1,
        "by_disposition": {"likely_dirty": 1},
        "by_doc": {"1": 1},
        "candidates": [
            {
                "fact_id": 1,
                "source_doc_id": 1,
                "source": "doc.md",
                "category": "project",
                "trust_score": 0.5,
                "length": 18,
                "disposition": "likely_dirty",
                "reasons": [{"severity": "likely_dirty", "reason": "extraction_meta"}],
                "content": "我需要确保每条事实都是自包含的。",
            }
        ],
    }

    _json_path, md_path = dirty.write_reports(report, tmp_path)
    markdown = md_path.read_text(encoding="utf-8")

    assert "| fact_id | verdict | disposition | doc | length | reasons | content |" in markdown
    assert "| 1 |  | likely_dirty | 1 | 18 | extraction_meta |" in markdown
