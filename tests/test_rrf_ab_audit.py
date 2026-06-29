"""Tests for the read-only RRF A/B audit report."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

from holographic.store import MemoryStore


SCRIPT = Path(__file__).parent / "scripts" / "run_rrf_ab_audit.py"
SPEC = importlib.util.spec_from_file_location("rrf_ab_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_build_report_does_not_increment_retrieval_count() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    store = MemoryStore(db_path=str(db_path), default_trust=0.5, hrr_dim=1024)
    try:
        fact_id = store.add_fact("Python provenance uses fact_provenance rows", category="project")
        store.add_fact("Legacy unknown facts have no provenance rows", category="project")

        report = audit.build_report(
            db_path,
            db_path,
            queries=["Python provenance", "legacy unknown"],
            min_trust=0.0,
            pool=20,
            limit=3,
        )

        row = store._conn.execute(
            "SELECT retrieval_count, last_accessed_at FROM facts WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()
        assert row["retrieval_count"] == 0
        assert row["last_accessed_at"] is None
        assert report["read_only"] is True
        assert report["query_count"] == 2
        assert set(report["summary"]) == {
            "median_top5_overlap",
            "min_top5_overlap",
            "top1_changed_count",
            "hrr_only_top3_query_count",
            "recommendation",
        }
    finally:
        store.close()
        db_path.unlink(missing_ok=True)


def test_median_handles_even_and_odd_counts() -> None:
    assert audit._median([1.0, 0.0, 0.5]) == 0.5
    assert audit._median([1.0, 0.0]) == 0.5


def test_write_reports_includes_no_quality_claim_warning(tmp_path: Path) -> None:
    report = {
        "generated_at": "2026-06-29T16:00:00",
        "source_db": "source.db",
        "snapshot_db": "snapshot.db",
        "read_only": True,
        "facts_active": 2,
        "query_count": 1,
        "category": None,
        "min_trust": 0.0,
        "pool": 100,
        "limit": 5,
        "summary": {
            "median_top5_overlap": 1.0,
            "min_top5_overlap": 1.0,
            "top1_changed_count": 0,
            "hrr_only_top3_query_count": 0,
            "recommendation": "hrr_has_negligible_default_search_effect",
        },
        "queries": [
            {
                "query": "Python provenance",
                "candidate_counts": {"fts": 1, "jaccard": 1, "hrr": 1, "union": 1},
                "top_2way": [{"fact_id": 1, "content": "a", "score": 0.1}],
                "top_3way": [{"fact_id": 1, "content": "a", "score": 0.2}],
                "top_2way_ids": [1],
                "top_3way_ids": [1],
                "top5_overlap": 1.0,
                "top1_changed": False,
                "hrr_only_top3_count": 0,
                "hrr_only_top3_ids": [],
            }
        ],
    }

    _json_path, md_path = audit.write_reports(report, tmp_path)
    markdown = md_path.read_text(encoding="utf-8")

    assert "does not claim relevance quality without human labels" in markdown
    assert "- median_top5_overlap: 1.0" in markdown
    assert "| Python provenance | 1.0 | False | 0 | [1] | [1] |" in markdown
