"""Create a stable memory DB snapshot and write a current ledger report.

This script never mutates the source database. It uses SQLite's backup API to
copy a consistent snapshot, then opens that snapshot read-only for counts.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


def _default_db_path() -> Path:
    return Path.home() / "AppData" / "Local" / "hermes" / "memory_store.db"


def create_snapshot(source: Path, snapshot_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_dir / f"memory_store_snapshot_{timestamp}.db"

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


def _fetch_scalar(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(query, params).fetchone()
    return row[0] if row else None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def build_ledger(snapshot: Path, source: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        facts_total = int(_fetch_scalar(conn, "SELECT COUNT(*) FROM facts"))
        facts_active = int(_fetch_scalar(conn, "SELECT COUNT(*) FROM facts WHERE merged_into IS NULL"))
        facts_soft_deleted = int(
            _fetch_scalar(conn, "SELECT COUNT(*) FROM facts WHERE merged_into IS NOT NULL")
        )
        documents_total = int(_fetch_scalar(conn, "SELECT COUNT(*) FROM documents"))
        schema_version = int(_fetch_scalar(conn, "SELECT version FROM schema_version"))
        fk_violations = [dict(row) for row in conn.execute("PRAGMA foreign_key_check")]
        integrity_check = str(_fetch_scalar(conn, "PRAGMA integrity_check"))

        active_by_category = [
            dict(row)
            for row in conn.execute(
                """
                SELECT category, COUNT(*) AS active_facts
                FROM facts
                WHERE merged_into IS NULL
                GROUP BY category
                ORDER BY active_facts DESC, category
                """
            )
        ]
        active_by_doc = [
            dict(row)
            for row in conn.execute(
                """
                SELECT source_doc_id, COUNT(*) AS active_facts
                FROM facts
                WHERE merged_into IS NULL
                GROUP BY source_doc_id
                ORDER BY source_doc_id
                """
            )
        ]
        soft_deleted_by_doc = [
            dict(row)
            for row in conn.execute(
                """
                SELECT source_doc_id, COUNT(*) AS soft_deleted_facts
                FROM facts
                WHERE merged_into IS NOT NULL
                GROUP BY source_doc_id
                ORDER BY source_doc_id
                """
            )
        ]
        document_rows = [
            {
                "doc_id": row["doc_id"],
                "source": row["source"],
                "active_facts": row["active_facts"],
                "soft_deleted_facts": row["soft_deleted_facts"],
                "created_at": row["created_at"],
            }
            for row in conn.execute(
                """
                SELECT
                    d.doc_id,
                    d.source,
                    d.created_at,
                    SUM(CASE WHEN f.fact_id IS NOT NULL AND f.merged_into IS NULL THEN 1 ELSE 0 END) AS active_facts,
                    SUM(CASE WHEN f.fact_id IS NOT NULL AND f.merged_into IS NOT NULL THEN 1 ELSE 0 END) AS soft_deleted_facts
                FROM documents d
                LEFT JOIN facts f ON f.source_doc_id = d.doc_id
                GROUP BY d.doc_id
                ORDER BY d.doc_id
                """
            )
        ]

        merge_targets = int(
            _fetch_scalar(
                conn,
                "SELECT COUNT(DISTINCT merged_into) FROM facts WHERE merged_into IS NOT NULL",
            )
        )
        merge_events = facts_soft_deleted
        source_lost_candidates = int(
            _fetch_scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM facts old
                JOIN facts target ON target.fact_id = old.merged_into
                WHERE old.source_doc_id IS NOT NULL
                  AND target.source_doc_id IS NOT NULL
                  AND old.source_doc_id != target.source_doc_id
                """,
            )
        )

        meta_patterns = [
            "%我需要%",
            "%用户要求我%",
            "%提取原子事实%",
            "%JSON%",
            "%不能输出%",
            "%规则%",
        ]
        meta_where = " OR ".join("content LIKE ?" for _ in meta_patterns)
        meta_candidates = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT fact_id, source_doc_id, LENGTH(content) AS length, content
                FROM facts
                WHERE merged_into IS NULL
                  AND ({meta_where} OR LENGTH(content) > 120)
                ORDER BY length DESC, fact_id
                LIMIT 100
                """,
                tuple(meta_patterns),
            )
        ]

        bank_columns = _table_columns(conn, "memory_banks")
        memory_banks: list[dict[str, Any]] = []
        if {"bank_name", "fact_count"}.issubset(bank_columns):
            select_cols = ["bank_name", "fact_count"]
            if "snr" in bank_columns:
                select_cols.append("snr")
            for row in conn.execute(f"SELECT {', '.join(select_cols)} FROM memory_banks ORDER BY bank_name"):
                data = dict(row)
                if "snr" not in data and data.get("fact_count"):
                    data["snr_estimate_1024"] = round(math.sqrt(1024 / int(data["fact_count"])), 3)
                memory_banks.append(data)

        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_db": str(source),
            "snapshot_db": str(snapshot),
            "schema_version": schema_version,
            "integrity_check": integrity_check,
            "foreign_key_violations": fk_violations,
            "facts_total": facts_total,
            "facts_active": facts_active,
            "facts_soft_deleted": facts_soft_deleted,
            "documents_total": documents_total,
            "active_by_category": active_by_category,
            "active_by_doc": active_by_doc,
            "soft_deleted_by_doc": soft_deleted_by_doc,
            "documents": document_rows,
            "merge_targets": merge_targets,
            "merge_events": merge_events,
            "source_lost_candidates": source_lost_candidates,
            "meta_candidates": meta_candidates,
            "memory_banks": memory_banks,
        }
    finally:
        conn.close()


def write_reports(ledger: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "current_db_ledger.json"
    md_path = output_dir / "current_db_ledger.md"
    json_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Current DB Ledger",
        "",
        "## Safety",
        "",
        "- Source database was copied with SQLite backup API.",
        "- Counts below come from the copied snapshot, not from the live WAL database.",
        f"- Source DB: `{ledger['source_db']}`",
        f"- Snapshot DB: `{ledger['snapshot_db']}`",
        "",
        "## Integrity",
        "",
        f"- generated_at: {ledger['generated_at']}",
        f"- schema_version: {ledger['schema_version']}",
        f"- integrity_check: {ledger['integrity_check']}",
        f"- foreign_key_violations: {len(ledger['foreign_key_violations'])}",
        "",
        "## Fact Counts",
        "",
        f"- facts_total: {ledger['facts_total']}",
        f"- facts_active: {ledger['facts_active']}",
        f"- facts_soft_deleted: {ledger['facts_soft_deleted']}",
        f"- documents_total: {ledger['documents_total']}",
        f"- merge_targets: {ledger['merge_targets']}",
        f"- merge_events: {ledger['merge_events']}",
        f"- cross-source merge candidates: {ledger['source_lost_candidates']}",
        "",
        "## Active Facts By Category",
        "",
        "| category | active_facts |",
        "|---|---:|",
    ]
    lines.extend(f"| {row['category']} | {row['active_facts']} |" for row in ledger["active_by_category"])
    lines += ["", "## Documents", "", "| doc_id | active | soft_deleted | source |", "|---:|---:|---:|---|"]
    for row in ledger["documents"]:
        source = str(row["source"] or "").replace("|", "\\|")
        lines.append(
            f"| {row['doc_id']} | {row['active_facts']} | {row['soft_deleted_facts']} | {source} |"
        )
    lines += ["", "## Memory Banks", "", "| bank_name | fact_count | snr |", "|---|---:|---:|"]
    for row in ledger["memory_banks"]:
        snr = row.get("snr", row.get("snr_estimate_1024", ""))
        lines.append(f"| {row['bank_name']} | {row['fact_count']} | {snr} |")
    lines += [
        "",
        "## Meta Candidates",
        "",
        f"- candidate_count_limited_to_100: {len(ledger['meta_candidates'])}",
        "",
        "| fact_id | doc | length | content |",
        "|---:|---:|---:|---|",
    ]
    for row in ledger["meta_candidates"]:
        content = str(row["content"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {row['fact_id']} | {row['source_doc_id']} | {row['length']} | {content} |")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=_default_db_path())
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("reports/snapshots"))
    args = parser.parse_args()

    snapshot = create_snapshot(args.db, args.snapshot_dir)
    ledger = build_ledger(snapshot, args.db)
    json_path, md_path = write_reports(ledger, args.output_dir)
    print(f"snapshot={snapshot}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    print(f"facts_active={ledger['facts_active']}")
    print(f"facts_soft_deleted={ledger['facts_soft_deleted']}")


if __name__ == "__main__":
    main()
