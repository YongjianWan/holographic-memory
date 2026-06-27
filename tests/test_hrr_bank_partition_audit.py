"""Tests for the read-only HRR bank partition audit."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


SCRIPT = Path(__file__).parent / "scripts" / "run_hrr_bank_partition_audit.py"
SPEC = importlib.util.spec_from_file_location("hrr_bank_partition_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_snr_for_count_uses_hrr_capacity_formula() -> None:
    assert audit.snr_for_count(1024) == 1.0
    assert audit.snr_for_count(256) == 2.0


def test_document_family_keeps_scope_out_of_partitioning() -> None:
    assert audit.document_family(None) == "legacy_none"
    assert audit.document_family("AGENTS.md") == "repo_root_doc"
    assert audit.document_family("docs\\宪法.md") == "repo_docs_current"
    assert audit.document_family("docs/achieve/session.md") == "repo_docs_archive"
    assert audit.document_family("C:/Users/sdses/Desktop/foo.txt") == "desktop_import"


def test_build_report_compares_category_and_source_doc_buckets(tmp_path: Path) -> None:
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
                content TEXT,
                category TEXT,
                source_doc_id INTEGER,
                hrr_vector BLOB,
                merged_into INTEGER
            );
            INSERT INTO documents(doc_id, source)
            VALUES (1, 'AGENTS.md'), (2, 'docs/achieve/old.md');
            INSERT INTO facts(fact_id, content, category, source_doc_id, hrr_vector, merged_into)
            VALUES
                (1, 'a', 'project', 1, X'00', NULL),
                (2, 'b', 'project', 1, X'00', NULL),
                (3, 'c', 'project', 2, X'00', NULL),
                (4, 'd', 'personal', NULL, X'00', NULL),
                (5, 'old', 'project', 2, X'00', 999999);
            """
        )
        conn.commit()
    finally:
        conn.close()

    report = audit.build_report(db_path, db_path)
    schemes = {scheme["scheme"]: scheme for scheme in report["schemes"]}

    assert report["read_only"] is True
    assert report["active_facts_scanned"] == 4
    assert schemes["category"]["max_fact_count"] == 3
    assert schemes["category_source_doc"]["max_fact_count"] == 2
    assert schemes["category_document_family"]["bank_count"] == 3
    assert schemes["category_source_doc_shard256"]["max_fact_count"] == 2
    assert report["recommendation"]["status"] == "viable_without_scope"


def test_source_doc_shard_splits_large_document_without_scope() -> None:
    facts = [
        {"fact_id": fact_id, "category": "project", "source_doc_id": 6}
        for fact_id in range(1, 266)
    ]

    audit.annotate_source_doc_shards(facts, shard_size=256)
    counts: dict[int, int] = {}
    for fact in facts:
        counts[fact["_source_doc_shard"]] = counts.get(fact["_source_doc_shard"], 0) + 1

    assert counts == {0: 256, 1: 9}


def test_write_reports_records_scheme_comparison(tmp_path: Path) -> None:
    report = {
        "generated_at": "2026-06-27T19:00:00",
        "source_db": "source.db",
        "snapshot_db": "snapshot.db",
        "read_only": True,
        "hrr_dim": 1024,
        "capacity_items": 256,
        "active_facts_scanned": 3,
        "active_by_category": {"project": 3},
        "recommendation": {
            "status": "viable_without_scope",
            "preferred_scheme": "category_source_doc",
            "reason": "all virtual banks are below HRR capacity without adding scope schema",
        },
        "schemes": [
            {
                "scheme": "category",
                "bank_count": 1,
                "max_fact_count": 3,
                "max_snr": 18.475,
                "banks_over_capacity": 0,
                "banks_with_snr_below_2": 0,
                "missing_hrr_vectors": 0,
                "top_banks": [
                    {
                        "bank_name": "cat:project",
                        "fact_count": 3,
                        "snr": 18.475,
                        "over_capacity": False,
                        "source_doc_id": None,
                        "source": None,
                    }
                ],
            }
        ],
    }

    _json_path, md_path = audit.write_reports(report, tmp_path)
    markdown = md_path.read_text(encoding="utf-8")

    assert "## Scheme Comparison" in markdown
    assert "| category | 1 | 3 | 18.475 | 0 | 0 | 0 |" in markdown
