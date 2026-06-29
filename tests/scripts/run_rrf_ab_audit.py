"""Read-only A/B audit for hypothetical 3-way vs default 2-way RRF search.

Default search uses FTS5 + Jaccard. This script compares that 2-way ranking
with a hypothetical 3-way FTS5+Jaccard+HRR ranking on a fixed query set, so
future changes can re-check whether HRR deserves to return. It snapshots the source DB first and never calls
``FactRetriever.search()``, so it does not mutate retrieval_count or
last_accessed_at.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).absolute().parent.parent.parent
PARENT_DIR = PROJECT_ROOT.parent
if "" in sys.path:
    sys.path.remove("")
sys.path.insert(0, str(PARENT_DIR))

if "hermes_state" not in sys.modules:
    hermes_state = types.ModuleType("hermes_state")
    hermes_state.apply_wal_with_fallback = lambda conn, db_label="": None
    sys.modules["hermes_state"] = hermes_state

from holographic.retrieval import FactRetriever, _RRF_K  # noqa: E402


QUERY_SET = [
    "Holographic memory provider",
    "fact_provenance legacy_unknown",
    "source_doc_id provenance",
    "HRR bank sharding",
    "category source_doc shard256",
    "dirty fact candidates",
    "Gate A Gate B scope",
    "P2 graph edge veto",
    "retain_document extraction",
    "LLM extractor rejects chatter",
    "retrieval_count side effect",
    "RRF FTS Jaccard HRR",
    "无常驻进程",
    "关机即文件",
    "软删除 merged_into",
    "迁移前备份",
    "事实废话判定边界",
    "项目元文档 原子提炼",
    "legacy Hindsight 长 fact",
    "DeepSeek retain routing",
]


def _default_db_path() -> Path:
    return Path("C:/Users/sdses/AppData/Local/hermes/memory_store.db")


def create_snapshot(source: Path, snapshot_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_dir / f"memory_store_rrf_ab_audit_{timestamp}.db"

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


class _ReadOnlyStore:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn


def _open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rrf_score(rankings: list[dict[int, int]], fact_id: int) -> float:
    score = 0.0
    for ranking in rankings:
        if fact_id in ranking:
            score += 1.0 / (_RRF_K + ranking[fact_id])
    return score


def _score_rows(
    retriever: FactRetriever,
    rows: list[dict[str, Any]],
    rankings: list[dict[int, int]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    scored = []
    for fact in rows:
        fid = int(fact["fact_id"])
        trust_boost = 1.0 + 0.2 * (float(fact["trust_score"]) - 0.5)
        recency_boost = retriever._recency_boost(
            fact.get("last_accessed_at") or fact.get("created_at")
        )
        speaker_penalty = 0.85 if re.match(r"^说话人\s*\d+", fact["content"]) else 1.0
        score = _rrf_score(rankings, fid) * trust_boost * recency_boost * speaker_penalty
        scored.append(
            {
                "fact_id": fid,
                "score": round(score, 8),
                "content": fact["content"],
                "category": fact["category"],
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def evaluate_query(
    retriever: FactRetriever,
    query: str,
    *,
    category: str | None = None,
    min_trust: float = 0.0,
    pool: int = 100,
    limit: int = 5,
) -> dict[str, Any]:
    fts_ranking = retriever._fts_ranking(query, category, min_trust, pool)
    jaccard_ranking = retriever._jaccard_ranking(query, category, min_trust, pool)
    hrr_ranking = retriever._hrr_ranking(query, category, min_trust, pool)

    candidate_ids = set(fts_ranking) | set(jaccard_ranking) | set(hrr_ranking)
    rows = retriever._fetch_facts(candidate_ids, category, min_trust)

    top_2way = _score_rows(
        retriever, rows, [fts_ranking, jaccard_ranking], limit=limit
    )
    top_3way = _score_rows(
        retriever, rows, [fts_ranking, jaccard_ranking, hrr_ranking], limit=limit
    )
    ids_2way = [item["fact_id"] for item in top_2way]
    ids_3way = [item["fact_id"] for item in top_3way]
    overlap_count = len(set(ids_2way) & set(ids_3way))
    hrr_only = [fid for fid in ids_3way if fid not in set(fts_ranking) | set(jaccard_ranking)]

    return {
        "query": query,
        "candidate_counts": {
            "fts": len(fts_ranking),
            "jaccard": len(jaccard_ranking),
            "hrr": len(hrr_ranking),
            "union": len(candidate_ids),
        },
        "top_2way": top_2way,
        "top_3way": top_3way,
        "top_2way_ids": ids_2way,
        "top_3way_ids": ids_3way,
        "top5_overlap": round(overlap_count / max(len(ids_3way), 1), 3),
        "top1_changed": bool(ids_2way and ids_3way and ids_2way[0] != ids_3way[0]),
        "hrr_only_top3_count": len(hrr_only),
        "hrr_only_top3_ids": hrr_only,
    }


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return round((ordered[mid - 1] + ordered[mid]) / 2, 3)


def build_report(
    snapshot: Path,
    source: Path,
    *,
    queries: list[str] | None = None,
    category: str | None = None,
    min_trust: float = 0.0,
    pool: int = 100,
    limit: int = 5,
) -> dict[str, Any]:
    query_set = list(queries or QUERY_SET)
    conn = _open_readonly(snapshot)
    try:
        store = _ReadOnlyStore(conn)
        retriever = FactRetriever(store=store, hrr_dim=1024)  # type: ignore[arg-type]
        results = [
            evaluate_query(
                retriever,
                query,
                category=category,
                min_trust=min_trust,
                pool=pool,
                limit=limit,
            )
            for query in query_set
        ]

        facts_active = int(
            conn.execute("SELECT COUNT(*) FROM facts WHERE merged_into IS NULL").fetchone()[0]
        )
    finally:
        conn.close()

    overlaps = [float(item["top5_overlap"]) for item in results]
    top1_changed_count = sum(1 for item in results if item["top1_changed"])
    hrr_only_queries = sum(1 for item in results if item["hrr_only_top3_count"])
    median_overlap = _median(overlaps)
    min_overlap = min(overlaps) if overlaps else 0.0

    if median_overlap >= 0.9 and top1_changed_count == 0 and hrr_only_queries == 0:
        recommendation = "hrr_has_negligible_default_search_effect"
    elif min_overlap < 0.6 or top1_changed_count >= max(1, len(results) // 4):
        recommendation = "hrr_changes_rankings_materially_needs_human_relevance_judgment"
    else:
        recommendation = "hrr_changes_some_rankings_collect_human_labels_before_changing_default"

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_db": str(source),
        "snapshot_db": str(snapshot),
        "read_only": True,
        "facts_active": facts_active,
        "query_count": len(query_set),
        "category": category,
        "min_trust": min_trust,
        "pool": pool,
        "limit": limit,
        "summary": {
            "median_top5_overlap": median_overlap,
            "min_top5_overlap": min_overlap,
            "top1_changed_count": top1_changed_count,
            "hrr_only_top3_query_count": hrr_only_queries,
            "recommendation": recommendation,
        },
        "queries": results,
    }


def write_reports(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "rrf_ab_audit.json"
    md_path = output_dir / "rrf_ab_audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    lines = [
        "# RRF A/B Audit",
        "",
        "## Safety",
        "",
        "- Source database was copied with SQLite backup API.",
        "- Report reads the copied snapshot only; it does not call `search()` and does not mutate retrieval_count or last_accessed_at.",
        "- Default search is FTS5+Jaccard; 3-way results shown here are a hypothetical comparison path.",
        "- The audit measures ranking movement only; it does not claim relevance quality without human labels.",
        f"- Source DB: `{report['source_db']}`",
        f"- Snapshot DB: `{report['snapshot_db']}`",
        "",
        "## Summary",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- facts_active: {report['facts_active']}",
        f"- query_count: {report['query_count']}",
        f"- median_top5_overlap: {summary['median_top5_overlap']}",
        f"- min_top5_overlap: {summary['min_top5_overlap']}",
        f"- top1_changed_count: {summary['top1_changed_count']}",
        f"- hrr_only_top3_query_count: {summary['hrr_only_top3_query_count']}",
        f"- recommendation: {summary['recommendation']}",
        "",
        "## Queries",
        "",
        "| query | top5_overlap | top1_changed | hrr_only_top3_count | top_3way_ids | top_2way_ids |",
        "|---|---:|---|---:|---|---|",
    ]
    for item in report["queries"]:
        query = str(item["query"]).replace("|", "\\|")
        lines.append(
            f"| {query} | {item['top5_overlap']} | {item['top1_changed']} | "
            f"{item['hrr_only_top3_count']} | {item['top_3way_ids']} | {item['top_2way_ids']} |"
        )
    lines += [
        "",
        "## Top Differences",
        "",
        "| query | 3-way top1 | 2-way top1 |",
        "|---|---|---|",
    ]
    for item in report["queries"]:
        if not item["top1_changed"]:
            continue
        top3 = item["top_3way"][0] if item["top_3way"] else {}
        top2 = item["top_2way"][0] if item["top_2way"] else {}
        top3_content = str(top3.get("content", "")).replace("|", "\\|").replace("\n", " ")
        top2_content = str(top2.get("content", "")).replace("|", "\\|").replace("\n", " ")
        query = str(item["query"]).replace("|", "\\|")
        lines.append(
            f"| {query} | {top3.get('fact_id')}: {top3_content} | "
            f"{top2.get('fact_id')}: {top2_content} |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=_default_db_path())
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("reports/snapshots"))
    parser.add_argument("--category")
    parser.add_argument("--min-trust", type=float, default=0.0)
    parser.add_argument("--pool", type=int, default=100)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    db_path = args.db.expanduser().absolute()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    snapshot = create_snapshot(db_path, args.snapshot_dir)
    report = build_report(
        snapshot,
        db_path,
        category=args.category,
        min_trust=args.min_trust,
        pool=args.pool,
        limit=args.limit,
    )
    json_path, md_path = write_reports(report, args.output_dir)
    print(f"snapshot={snapshot}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    print(f"median_top5_overlap={report['summary']['median_top5_overlap']}")
    print(f"top1_changed_count={report['summary']['top1_changed_count']}")


if __name__ == "__main__":
    main()
