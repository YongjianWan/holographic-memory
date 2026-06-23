"""Tests for the read-only scope gate audit helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parent / "scripts" / "run_scope_gate_audit.py"
SPEC = importlib.util.spec_from_file_location("scope_gate_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_meta_detection_marks_reasoning_not_long_domain_fact() -> None:
    meta = "等等，我需要确保自包含。用户要求我从文本中提取原子事实。"
    domain = "招商平台采用企业综合评分、投资意愿评分和产业匹配度共同生成推荐结果。"

    assert audit.detect_extraction_meta(meta)
    assert not audit.detect_extraction_meta(domain)


def test_multilabel_stats_count_each_scope_and_cardinality() -> None:
    labels = {
        1: ["招商", "公文系统"],
        2: ["招商"],
        3: [],
        4: ["Holographic", "检索", "工程工具"],
    }

    stats = audit.summarize_scope_labels(labels)

    assert stats["cardinality"] == {"0": 1, "1": 1, "2": 1, "3+": 1}
    assert stats["scope_counts"]["招商"] == 2
    assert stats["scope_counts"]["公文系统"] == 1
    assert sum(stats["scope_counts"].values()) == 6
    assert stats["max_scope_share"] == 0.5


def test_batch_diff_separates_inserted_rows_and_merge_events() -> None:
    before = {
        1: {"retrieval_count": 0},
        2: {"retrieval_count": 2},
    }
    after = {
        1: {"retrieval_count": 0},
        2: {"retrieval_count": 3},
        3: {"retrieval_count": 2},
        4: {"retrieval_count": 0},
    }

    stats = audit.summarize_batch_diff(before, after)

    assert stats == {
        "inserted_rows": 2,
        "unique_fact_ids": 4,
        "merge_targets": 2,
        "merge_events": 3,
        "successful_fact_id_returns": 5,
    }
