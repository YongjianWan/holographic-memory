"""Tests for the read-only provenance audit report."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


SCRIPT = Path(__file__).parent / "scripts" / "run_provenance_audit.py"
SPEC = importlib.util.spec_from_file_location("provenance_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_build_report_projects_missing_rows_as_legacy_unknown(tmp_path: Path) -> None:
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
                source_doc_id INTEGER,
                merged_into INTEGER
            );
            CREATE TABLE fact_provenance (
                provenance_id INTEGER PRIMARY KEY,
                fact_id INTEGER NOT NULL,
                doc_id INTEGER NOT NULL,
                source_fact_id INTEGER NOT NULL,
                relation TEXT NOT NULL DEFAULT 'origin'
            );
            INSERT INTO documents(doc_id, source) VALUES
                (1, 'doc-a.md'),
                (2, 'doc-b.md');
            INSERT INTO facts(fact_id, content, category, source_doc_id, merged_into)
            VALUES
                (1, 'known fact', 'project', 1, NULL),
                (2, 'legacy fact', 'project', NULL, NULL),
                (3, 'deleted fact', 'project', 2, 999999);
            INSERT INTO fact_provenance(fact_id, doc_id, source_fact_id, relation)
            VALUES (1, 1, 1, 'origin');
            """
        )
        conn.commit()
    finally:
        conn.close()

    report = audit.build_report(db_path, db_path)

    assert report["read_only"] is True
    assert report["coverage"] == {
        "active_known": 1,
        "active_legacy_unknown": 1,
        "known_pct": 50.0,
        "legacy_unknown_pct": 50.0,
    }
    assert report["active_by_category"] == [
        {
            "category": "project",
            "active_facts": 2,
            "known_facts": 1,
            "legacy_unknown": 1,
            "known_pct": 50.0,
            "provenance_rows": 1,
        }
    ]


def test_build_report_counts_multi_doc_and_source_doc_mismatch(tmp_path: Path) -> None:
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
                source_doc_id INTEGER,
                merged_into INTEGER
            );
            CREATE TABLE fact_provenance (
                provenance_id INTEGER PRIMARY KEY,
                fact_id INTEGER NOT NULL,
                doc_id INTEGER NOT NULL,
                source_fact_id INTEGER NOT NULL,
                relation TEXT NOT NULL DEFAULT 'origin'
            );
            INSERT INTO documents(doc_id, source) VALUES
                (1, 'doc-a.md'),
                (2, 'doc-b.md');
            INSERT INTO facts(fact_id, content, category, source_doc_id, merged_into)
            VALUES (10, 'merged survivor', 'project', 1, NULL);
            INSERT INTO fact_provenance(fact_id, doc_id, source_fact_id, relation)
            VALUES
                (10, 1, 10, 'origin'),
                (10, 2, 11, 'merge');
            """
        )
        conn.commit()
    finally:
        conn.close()

    report = audit.build_report(db_path, db_path)

    assert report["active_multi_doc_facts"] == 1
    assert report["source_doc_mismatch_sample_count"] == 1
    assert report["multi_doc_fact_samples"][0]["fact_id"] == 10
    assert report["source_doc_mismatch_samples"][0]["provenance_doc_id"] == 2
    assert report["active_by_category"] == [
        {
            "category": "project",
            "active_facts": 1,
            "known_facts": 1,
            "legacy_unknown": 0,
            "known_pct": 100.0,
            "provenance_rows": 2,
        }
    ]


def test_build_report_handles_pre_v10_without_provenance_table(tmp_path: Path) -> None:
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
                source_doc_id INTEGER,
                merged_into INTEGER
            );
            INSERT INTO facts(fact_id, content, merged_into)
            VALUES (1, 'legacy fact', NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()

    report = audit.build_report(db_path, db_path)

    assert report["has_provenance_table"] is False
    assert report["coverage"]["active_known"] == 0
    assert report["coverage"]["active_legacy_unknown"] == 1


def test_write_reports_includes_coverage_tables(tmp_path: Path) -> None:
    report = {
        "generated_at": "2026-06-29T10:00:00",
        "source_db": "source.db",
        "snapshot_db": "snapshot.db",
        "read_only": True,
        "integrity_check": "ok",
        "foreign_key_violations": [],
        "facts_total": 2,
        "facts_active": 2,
        "facts_soft_deleted": 0,
        "documents_total": 1,
        "has_provenance_table": True,
        "coverage": {
            "active_known": 1,
            "active_legacy_unknown": 1,
            "known_pct": 50.0,
            "legacy_unknown_pct": 50.0,
        },
        "provenance_rows_total": 1,
        "provenance_rows_for_active": 1,
        "provenance_by_relation": {"origin": 1},
        "active_multi_doc_facts": 0,
        "source_doc_mismatch_sample_count": 0,
        "active_by_category": [
            {
                "category": "project",
                "active_facts": 2,
                "known_facts": 1,
                "legacy_unknown": 1,
                "known_pct": 50.0,
                "provenance_rows": 1,
            }
        ],
        "documents": [
            {
                "doc_id": 1,
                "source": "doc.md",
                "provenance_rows": 1,
                "distinct_facts": 1,
                "active_facts": 1,
            }
        ],
        "multi_doc_fact_samples": [],
        "source_doc_mismatch_samples": [],
    }

    _json_path, md_path = audit.write_reports(report, tmp_path)
    markdown = md_path.read_text(encoding="utf-8")

    assert "## Coverage" in markdown
    assert "- active_legacy_unknown: 1 (50.0%)" in markdown
    assert "| category | active_facts | known_facts | legacy_unknown | known_pct | provenance_rows |" in markdown
    assert "| project | 2 | 1 | 1 | 50.0 | 1 |" in markdown
