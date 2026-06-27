"""Tests for soft-deleting confirmed dirty fact candidates."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


SCRIPT = Path(__file__).parent / "scripts" / "run_apply_dirty_fact_verdicts.py"
SPEC = importlib.util.spec_from_file_location("apply_dirty_fact_verdicts", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
apply_dirty = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(apply_dirty)


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE facts (
                fact_id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'project',
                trust_score REAL DEFAULT 0.5,
                source_doc_id INTEGER,
                merged_into INTEGER,
                updated_at TEXT
            );
            INSERT INTO facts(fact_id, content, category, source_doc_id, merged_into)
            VALUES
                (999999, 'System audit soft-delete marker', 'system', NULL, NULL),
                (1, 'dirty candidate', 'project', 9, NULL),
                (2, 'review candidate', 'project', 9, NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_selected_fact_ids_accepts_likely_dirty_and_verdicts() -> None:
    report = {
        "candidates": [
            {"fact_id": 1, "disposition": "likely_dirty"},
            {"fact_id": 2, "disposition": "review", "verdict": "reject"},
            {"fact_id": 3, "disposition": "review", "verdict": "keep"},
        ]
    }

    assert apply_dirty.selected_fact_ids(
        report, apply_likely_dirty=True, verdicts={"reject"}
    ) == [1, 2]
    assert apply_dirty.selected_fact_ids(
        report, apply_likely_dirty=False, verdicts={"reject"}
    ) == [2]


def test_apply_soft_delete_sets_merged_into_without_physical_delete(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    _make_db(db_path)

    result = apply_dirty.apply_soft_delete(db_path, [1])

    conn = sqlite3.connect(db_path)
    try:
        assert result == {"updated": 1, "categories": ["project"]}
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 3
        assert conn.execute("SELECT merged_into FROM facts WHERE fact_id = 1").fetchone()[0] == 999999
        assert conn.execute("SELECT merged_into FROM facts WHERE fact_id = 2").fetchone()[0] is None
    finally:
        conn.close()


def test_apply_soft_delete_rejects_missing_sentinel(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE facts (
                fact_id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'project',
                merged_into INTEGER,
                updated_at TEXT
            );
            INSERT INTO facts(fact_id, content, category, merged_into)
            VALUES (1, 'dirty candidate', 'project', NULL);
            """
        )
        conn.commit()
    finally:
        conn.close()

    try:
        apply_dirty.apply_soft_delete(db_path, [1])
    except RuntimeError as exc:
        assert "999999" in str(exc)
    else:
        raise AssertionError("missing sentinel should fail")


def test_preview_reports_selected_rows_and_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    _make_db(db_path)

    result = apply_dirty.preview(db_path, [1])

    assert result["facts_total"] == 3
    assert result["facts_active"] == 3
    assert result["facts_soft_deleted"] == 0
    assert result["sentinel_exists"] is True
    assert result["selected"][0]["fact_id"] == 1
