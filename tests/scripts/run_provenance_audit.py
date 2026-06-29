"""Generate a read-only provenance coverage report for the memory DB.

The report answers how much of the active corpus has forward provenance rows
in ``fact_provenance`` and how much is honestly legacy-unknown. It snapshots
the source database with SQLite's backup API, opens that snapshot read-only,
and never mutates facts, schema, documents, or provenance.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def _default_db_path() -> Path:
    return Path("C:/Users/sdses/AppData/Local/hermes/memory_store.db")


def create_snapshot(source: Path, snapshot_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_dir / f"memory_store_provenance_audit_{timestamp}.db"

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


def _open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_scalar(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(query, params).fetchone()
    return row[0] if row else None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
    )


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(part * 100 / total, 2)


def build_report(snapshot: Path, source: Path, *, sample_limit: int = 50) -> dict[str, Any]:
    with _open_readonly(snapshot) as conn:
        facts_active = int(
            _fetch_scalar(conn, "SELECT COUNT(*) FROM facts WHERE merged_into IS NULL")
        )
        facts_total = int(_fetch_scalar(conn, "SELECT COUNT(*) FROM facts"))
        facts_soft_deleted = int(
            _fetch_scalar(conn, "SELECT COUNT(*) FROM facts WHERE merged_into IS NOT NULL")
        )
        documents_total = int(_fetch_scalar(conn, "SELECT COUNT(*) FROM documents"))
        integrity_check = str(_fetch_scalar(conn, "PRAGMA integrity_check"))
        fk_violations = [dict(row) for row in conn.execute("PRAGMA foreign_key_check")]

        has_provenance_table = _table_exists(conn, "fact_provenance")
        if not has_provenance_table:
            return {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "source_db": str(source),
                "snapshot_db": str(snapshot),
                "read_only": True,
                "integrity_check": integrity_check,
                "foreign_key_violations": fk_violations,
                "facts_total": facts_total,
                "facts_active": facts_active,
                "facts_soft_deleted": facts_soft_deleted,
                "documents_total": documents_total,
                "has_provenance_table": False,
                "coverage": {
                    "active_known": 0,
                    "active_legacy_unknown": facts_active,
                    "known_pct": 0.0,
                    "legacy_unknown_pct": 100.0 if facts_active else 0.0,
                },
                "note": "fact_provenance table is absent; all active facts are legacy_unknown.",
            }

        active_known = int(
            _fetch_scalar(
                conn,
                """
                SELECT COUNT(DISTINCT f.fact_id)
                FROM facts f
                JOIN fact_provenance p ON p.fact_id = f.fact_id
                WHERE f.merged_into IS NULL
                """,
            )
        )
        active_legacy_unknown = facts_active - active_known
        provenance_rows_total = int(_fetch_scalar(conn, "SELECT COUNT(*) FROM fact_provenance"))
        provenance_rows_for_active = int(
            _fetch_scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM fact_provenance p
                JOIN facts f ON f.fact_id = p.fact_id
                WHERE f.merged_into IS NULL
                """,
            )
        )
        active_multi_doc_facts = int(
            _fetch_scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM (
                    SELECT f.fact_id
                    FROM facts f
                    JOIN fact_provenance p ON p.fact_id = f.fact_id
                    WHERE f.merged_into IS NULL
                    GROUP BY f.fact_id
                    HAVING COUNT(DISTINCT p.doc_id) > 1
                )
                """,
            )
        )
        active_multi_source_fact_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    f.fact_id,
                    f.source_doc_id,
                    COUNT(DISTINCT p.doc_id) AS doc_count,
                    GROUP_CONCAT(DISTINCT COALESCE(d.source, '')) AS sources,
                    f.content
                FROM facts f
                JOIN fact_provenance p ON p.fact_id = f.fact_id
                LEFT JOIN documents d ON d.doc_id = p.doc_id
                WHERE f.merged_into IS NULL
                GROUP BY f.fact_id
                HAVING COUNT(DISTINCT p.doc_id) > 1
                ORDER BY doc_count DESC, f.fact_id
                LIMIT ?
                """,
                (sample_limit,),
            )
        ]
        source_doc_mismatches = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    f.fact_id,
                    f.source_doc_id,
                    p.doc_id AS provenance_doc_id,
                    p.source_fact_id,
                    p.relation,
                    f.content,
                    d.source
                FROM facts f
                JOIN fact_provenance p ON p.fact_id = f.fact_id
                LEFT JOIN documents d ON d.doc_id = p.doc_id
                WHERE f.merged_into IS NULL
                  AND f.source_doc_id IS NOT NULL
                  AND f.source_doc_id != p.doc_id
                ORDER BY f.fact_id, p.doc_id, p.source_fact_id
                LIMIT ?
                """,
                (sample_limit,),
            )
        ]
        active_by_category_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    f.category,
                    COUNT(*) AS active_facts,
                    SUM(CASE WHEN p.fact_id IS NULL THEN 1 ELSE 0 END) AS legacy_unknown,
                    SUM(CASE WHEN p.fact_id IS NOT NULL THEN 1 ELSE 0 END) AS known_rows,
                    COUNT(DISTINCT CASE WHEN p.fact_id IS NOT NULL THEN f.fact_id END) AS known_facts
                FROM facts f
                LEFT JOIN fact_provenance p ON p.fact_id = f.fact_id
                WHERE f.merged_into IS NULL
                GROUP BY f.category
                ORDER BY active_facts DESC, f.category
                """
            )
        ]
        active_by_category = []
        for row in active_by_category_rows:
            active_facts = int(row["active_facts"])
            known_facts = int(row["known_facts"])
            active_by_category.append(
                {
                    "category": row["category"],
                    "active_facts": active_facts,
                    "known_facts": known_facts,
                    "legacy_unknown": active_facts - known_facts,
                    "known_pct": _pct(known_facts, active_facts),
                    "provenance_rows": int(row["known_rows"]),
                }
            )

        provenance_by_relation = dict(
            Counter(
                {
                    row["relation"]: int(row["count"])
                    for row in conn.execute(
                        """
                        SELECT relation, COUNT(*) AS count
                        FROM fact_provenance
                        GROUP BY relation
                        ORDER BY count DESC, relation
                        """
                    )
                }
            )
        )
        documents = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    d.doc_id,
                    d.source,
                    COUNT(p.provenance_id) AS provenance_rows,
                    COUNT(DISTINCT p.fact_id) AS distinct_facts,
                    COUNT(DISTINCT CASE WHEN f.merged_into IS NULL THEN p.fact_id END) AS active_facts
                FROM documents d
                LEFT JOIN fact_provenance p ON p.doc_id = d.doc_id
                LEFT JOIN facts f ON f.fact_id = p.fact_id
                GROUP BY d.doc_id
                ORDER BY active_facts DESC, provenance_rows DESC, d.doc_id
                """
            )
        ]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_db": str(source),
        "snapshot_db": str(snapshot),
        "read_only": True,
        "integrity_check": integrity_check,
        "foreign_key_violations": fk_violations,
        "facts_total": facts_total,
        "facts_active": facts_active,
        "facts_soft_deleted": facts_soft_deleted,
        "documents_total": documents_total,
        "has_provenance_table": True,
        "coverage": {
            "active_known": active_known,
            "active_legacy_unknown": active_legacy_unknown,
            "known_pct": _pct(active_known, facts_active),
            "legacy_unknown_pct": _pct(active_legacy_unknown, facts_active),
        },
        "provenance_rows_total": provenance_rows_total,
        "provenance_rows_for_active": provenance_rows_for_active,
        "provenance_by_relation": provenance_by_relation,
        "active_multi_doc_facts": active_multi_doc_facts,
        "source_doc_mismatch_sample_count": len(source_doc_mismatches),
        "active_by_category": active_by_category,
        "documents": documents,
        "multi_doc_fact_samples": active_multi_source_fact_rows,
        "source_doc_mismatch_samples": source_doc_mismatches,
    }


def write_reports(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "provenance_audit.json"
    md_path = output_dir / "provenance_audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    coverage = report["coverage"]
    lines = [
        "# Provenance Audit",
        "",
        "## Safety",
        "",
        "- Source database was copied with SQLite backup API.",
        "- Report reads the copied snapshot only; it does not mutate facts, schema, documents, or provenance.",
        "- `legacy_unknown` is derived at read time from missing `fact_provenance` rows; this report does not write placeholder provenance.",
        f"- Source DB: `{report['source_db']}`",
        f"- Snapshot DB: `{report['snapshot_db']}`",
        "",
        "## Integrity",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- integrity_check: {report['integrity_check']}",
        f"- foreign_key_violations: {len(report['foreign_key_violations'])}",
        f"- has_provenance_table: {report['has_provenance_table']}",
        "",
        "## Coverage",
        "",
        f"- facts_active: {report['facts_active']}",
        f"- active_known: {coverage['active_known']} ({coverage['known_pct']}%)",
        f"- active_legacy_unknown: {coverage['active_legacy_unknown']} ({coverage['legacy_unknown_pct']}%)",
    ]
    if report.get("has_provenance_table"):
        lines += [
            f"- provenance_rows_total: {report['provenance_rows_total']}",
            f"- provenance_rows_for_active: {report['provenance_rows_for_active']}",
            f"- active_multi_doc_facts: {report['active_multi_doc_facts']}",
            f"- source_doc_mismatch_sample_count: {report['source_doc_mismatch_sample_count']}",
            "",
            "## Active Coverage By Category",
            "",
            "| category | active_facts | known_facts | legacy_unknown | known_pct | provenance_rows |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for row in report["active_by_category"]:
            lines.append(
                f"| {row['category']} | {row['active_facts']} | {row['known_facts']} | "
                f"{row['legacy_unknown']} | {row['known_pct']} | {row['provenance_rows']} |"
            )
        lines += [
            "",
            "## Provenance By Relation",
            "",
            "| relation | rows |",
            "|---|---:|",
        ]
        for relation, count in report["provenance_by_relation"].items():
            lines.append(f"| {relation} | {count} |")
        lines += [
            "",
            "## Documents",
            "",
            "| doc_id | active_facts | distinct_facts | provenance_rows | source |",
            "|---:|---:|---:|---:|---|",
        ]
        for row in report["documents"]:
            source = str(row["source"] or "").replace("|", "\\|")
            lines.append(
                f"| {row['doc_id']} | {row['active_facts']} | {row['distinct_facts']} | "
                f"{row['provenance_rows']} | {source} |"
            )
        lines += [
            "",
            "## Multi-Document Fact Samples",
            "",
            "| fact_id | source_doc_id | doc_count | sources | content |",
            "|---:|---:|---:|---|---|",
        ]
        for row in report["multi_doc_fact_samples"]:
            content = str(row["content"]).replace("|", "\\|").replace("\n", " ")
            sources = str(row["sources"] or "").replace("|", "\\|")
            lines.append(
                f"| {row['fact_id']} | {row['source_doc_id']} | {row['doc_count']} | "
                f"{sources} | {content} |"
            )
        lines += [
            "",
            "## Source Doc Mismatch Samples",
            "",
            "| fact_id | source_doc_id | provenance_doc_id | relation | source_fact_id | source | content |",
            "|---:|---:|---:|---|---:|---|---|",
        ]
        for row in report["source_doc_mismatch_samples"]:
            content = str(row["content"]).replace("|", "\\|").replace("\n", " ")
            source = str(row["source"] or "").replace("|", "\\|")
            lines.append(
                f"| {row['fact_id']} | {row['source_doc_id']} | {row['provenance_doc_id']} | "
                f"{row['relation']} | {row['source_fact_id']} | {source} | {content} |"
            )
    else:
        lines += ["", f"- note: {report.get('note', '')}"]

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=_default_db_path())
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("reports/snapshots"))
    parser.add_argument("--sample-limit", type=int, default=50)
    args = parser.parse_args()

    db_path = args.db.expanduser().absolute()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    snapshot = create_snapshot(db_path, args.snapshot_dir)
    report = build_report(snapshot, db_path, sample_limit=args.sample_limit)
    json_path, md_path = write_reports(report, args.output_dir)

    coverage = report["coverage"]
    print(f"snapshot={snapshot}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    print(f"facts_active={report['facts_active']}")
    print(f"active_known={coverage['active_known']}")
    print(f"active_legacy_unknown={coverage['active_legacy_unknown']}")


if __name__ == "__main__":
    main()
