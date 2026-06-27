"""Generate a read-only dirty/meta fact candidate report.

The report is an audit aid only. It snapshots the source database with
SQLite's backup API, opens that snapshot read-only, and writes JSON/Markdown
candidate lists for human review. It never soft-deletes or physically deletes
facts.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).absolute().parent.parent.parent
if "" in sys.path:
    sys.path.remove("")
sys.path.insert(0, str(PROJECT_ROOT))

from extractors import _LLMExtractor


_META_PATTERNS = (
    re.compile(r"^(等等|让我|我需要|我应该|我先|再看|实际上用户说|题目说)"),
    re.compile(r"(用户要求我|从文本中提取|每行一个事实|需要确保.*自包含)"),
    re.compile(r"(这是Claude的建议|区分.*用户.*Claude|作为事实提取)"),
    re.compile(r"</?think>", re.IGNORECASE),
    re.compile(r'"\s*-\s*\d+\s*[分字].*(OK|通过|太短)', re.IGNORECASE),
)

_TRANSIENT_PATTERNS = (
    re.compile(r"(第\s*\d+\s*条记忆|memory slot|numbered entries)", re.IGNORECASE),
    re.compile(r"(当前|目前).{0,12}(facts?|条目|token|上下文|slot|槽位)", re.IGNORECASE),
    re.compile(r"(active facts?|schema_version|memory_store\.db|retrieval_count)", re.IGNORECASE),
)

_CHATTER_PATTERNS = (
    re.compile(r"^(嗯|哦|啊|好吧|对对对|哈哈|行吧)[，,。!！\s]*"),
    re.compile(r"(晚安|该睡|睡吧|很晚了|goodnight|time to sleep)", re.IGNORECASE),
)


def _default_db_path() -> Path:
    return Path.home() / "AppData" / "Local" / "hermes" / "memory_store.db"


def create_snapshot(source: Path, snapshot_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_dir / f"memory_store_dirty_audit_{timestamp}.db"

    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(snapshot)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    return snapshot


def detect_candidate_reasons(content: str, *, review_length: int = 240) -> list[dict[str, str]]:
    """Return conservative candidate reasons for human review.

    Hard reasons mirror the current extractor guardrails and historical
    extraction-meta leak patterns. Review reasons are intentionally broad:
    they flag rows worth a human look without claiming the row is dirty.
    """
    reasons: list[dict[str, str]] = []

    if _LLMExtractor._should_reject_fact(content):
        reasons.append(
            {
                "severity": "likely_dirty",
                "reason": "current_extractor_guard",
            }
        )

    for pattern in _META_PATTERNS:
        if pattern.search(content):
            reasons.append(
                {
                    "severity": "likely_dirty",
                    "reason": f"extraction_meta:{pattern.pattern}",
                }
            )

    for pattern in _CHATTER_PATTERNS:
        if pattern.search(content):
            reasons.append(
                {
                    "severity": "likely_dirty",
                    "reason": f"conversation_noise:{pattern.pattern}",
                }
            )

    for pattern in _TRANSIENT_PATTERNS:
        if pattern.search(content):
            reasons.append(
                {
                    "severity": "review",
                    "reason": f"transient_state:{pattern.pattern}",
                }
            )

    if len(content) > review_length:
        reasons.append(
            {
                "severity": "review",
                "reason": f"long_atomicity_check:>{review_length}",
            }
        )

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in reasons:
        key = (item["severity"], item["reason"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_active_facts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
                f.fact_id,
                f.content,
                f.category,
                f.source_doc_id,
                f.trust_score,
                d.source AS source
            FROM facts f
            LEFT JOIN documents d ON d.doc_id = f.source_doc_id
            WHERE f.merged_into IS NULL
            ORDER BY f.fact_id
            """
        )
    )


def build_report(snapshot: Path, source: Path, *, review_length: int = 240) -> dict[str, Any]:
    with _open_readonly(snapshot) as conn:
        rows = _fetch_active_facts(conn)

    candidates: list[dict[str, Any]] = []
    for row in rows:
        content = str(row["content"])
        reasons = detect_candidate_reasons(content, review_length=review_length)
        if not reasons:
            continue
        severities = {item["severity"] for item in reasons}
        disposition = "likely_dirty" if "likely_dirty" in severities else "review"
        candidates.append(
            {
                "fact_id": row["fact_id"],
                "source_doc_id": row["source_doc_id"],
                "source": row["source"],
                "category": row["category"],
                "trust_score": row["trust_score"],
                "length": len(content),
                "disposition": disposition,
                "reasons": reasons,
                "content": content,
            }
        )

    by_disposition = Counter(item["disposition"] for item in candidates)
    by_doc = Counter(str(item["source_doc_id"]) for item in candidates)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_db": str(source),
        "snapshot_db": str(snapshot),
        "read_only": True,
        "review_length": review_length,
        "active_facts_scanned": len(rows),
        "candidate_count": len(candidates),
        "by_disposition": dict(sorted(by_disposition.items())),
        "by_doc": dict(by_doc.most_common()),
        "candidates": candidates,
    }


def write_reports(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "dirty_fact_candidates.json"
    md_path = output_dir / "dirty_fact_candidates.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Dirty Fact Candidates",
        "",
        "## Safety",
        "",
        "- Source database was copied with SQLite backup API.",
        "- Report reads the copied snapshot only; it does not mutate facts, schema, or provenance.",
        "- `likely_dirty` means the row matched current extractor guardrails or historical meta-leak patterns.",
        "- `review` means the row is worth a human look, not that it should be removed.",
        f"- Source DB: `{report['source_db']}`",
        f"- Snapshot DB: `{report['snapshot_db']}`",
        "",
        "## Summary",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- active_facts_scanned: {report['active_facts_scanned']}",
        f"- candidate_count: {report['candidate_count']}",
        f"- review_length: {report['review_length']}",
    ]
    for disposition, count in report["by_disposition"].items():
        lines.append(f"- {disposition}: {count}")

    lines += [
        "",
        "## Candidates",
        "",
        "| fact_id | verdict | disposition | doc | length | reasons | content |",
        "|---:|---|---|---:|---:|---|---|",
    ]
    disposition_order = {"likely_dirty": 0, "review": 1}
    candidates = sorted(
        report["candidates"],
        key=lambda item: (
            disposition_order.get(item["disposition"], 9),
            item["source_doc_id"] if item["source_doc_id"] is not None else -1,
            -item["length"],
            item["fact_id"],
        ),
    )
    for item in candidates:
        reasons = ", ".join(reason["reason"] for reason in item["reasons"])
        reasons = reasons.replace("|", "\\|")
        content = str(item["content"]).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {item['fact_id']} |  | {item['disposition']} | "
            f"{item['source_doc_id']} | {item['length']} | {reasons} | {content} |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=_default_db_path())
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("reports/snapshots"))
    parser.add_argument("--review-length", type=int, default=240)
    args = parser.parse_args()

    snapshot = create_snapshot(args.db, args.snapshot_dir)
    report = build_report(snapshot, args.db, review_length=args.review_length)
    json_path, md_path = write_reports(report, args.output_dir)
    print(f"snapshot={snapshot}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    print(f"active_facts_scanned={report['active_facts_scanned']}")
    print(f"candidate_count={report['candidate_count']}")
    for disposition, count in report["by_disposition"].items():
        print(f"{disposition}={count}")


if __name__ == "__main__":
    main()
