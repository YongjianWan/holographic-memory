"""Read-only audit for HRR memory-bank partition options.

The audit compares virtual bank partition schemes against the current active
facts. It does not write memory_banks, facts, schema, or provenance. The goal is
to measure whether category-internal physical partitioning can relieve HRR bank
saturation without introducing scope.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


HRR_DIM = 1024
CAPACITY_ITEMS = HRR_DIM // 4


def _default_db_path() -> Path:
    return Path("C:/Users/sdses/AppData/Local/hermes/memory_store.db")


def create_snapshot(source: Path, snapshot_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_dir / f"memory_store_hrr_bank_audit_{timestamp}.db"

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


def snr_for_count(fact_count: int, dim: int = HRR_DIM) -> float:
    if fact_count <= 0:
        return float("inf")
    return round(math.sqrt(dim / fact_count), 3)


def document_family(source: str | None) -> str:
    if not source:
        return "legacy_none"
    normalized = source.replace("\\", "/")
    if normalized.startswith("docs/achieve/"):
        return "repo_docs_archive"
    if normalized.startswith("docs/"):
        return "repo_docs_current"
    if "/" not in normalized and ":" not in normalized:
        return "repo_root_doc"
    if "Desktop/" in normalized or normalized.startswith("C:/"):
        return "desktop_import"
    return "other_source"


def load_active_facts(snapshot: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    f.fact_id,
                    f.category,
                    f.source_doc_id,
                    d.source,
                    f.hrr_vector IS NOT NULL AS has_hrr_vector
                FROM facts f
                LEFT JOIN documents d ON d.doc_id = f.source_doc_id
                WHERE f.merged_into IS NULL
                ORDER BY f.fact_id
                """
            )
        ]
    finally:
        conn.close()


def _bucket_rows(
    facts: list[dict[str, Any]],
    scheme_name: str,
    bucket_key: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    missing_hrr: Counter[str] = Counter()
    examples: dict[str, dict[str, Any]] = {}
    for fact in facts:
        key = bucket_key(fact)
        counts[key] += 1
        if not fact["has_hrr_vector"]:
            missing_hrr[key] += 1
        examples.setdefault(
            key,
            {
                "category": fact["category"],
                "source_doc_id": fact["source_doc_id"],
                "source": fact["source"],
            },
        )

    rows: list[dict[str, Any]] = []
    for key, count in counts.items():
        row = {
            "bank_name": key,
            "fact_count": count,
            "snr": snr_for_count(count),
            "over_capacity": count > CAPACITY_ITEMS,
            "missing_hrr_vectors": missing_hrr.get(key, 0),
            **examples[key],
        }
        rows.append(row)
    rows.sort(key=lambda row: (-row["fact_count"], row["bank_name"]))

    max_count = rows[0]["fact_count"] if rows else 0
    return {
        "scheme": scheme_name,
        "bank_count": len(rows),
        "max_fact_count": max_count,
        "max_snr": snr_for_count(max_count),
        "banks_over_capacity": sum(1 for row in rows if row["over_capacity"]),
        "banks_with_snr_below_2": sum(1 for row in rows if row["snr"] < 2.0),
        "missing_hrr_vectors": sum(row["missing_hrr_vectors"] for row in rows),
        "top_banks": rows[:20],
    }


def _source_doc_shard_key(fact: dict[str, Any]) -> str:
    doc = fact["source_doc_id"] or "none"
    shard = int(fact.get("_source_doc_shard", 0))
    return f"cat:{fact['category']}|doc:{doc}|shard:{shard:02d}"


def annotate_source_doc_shards(facts: list[dict[str, Any]], shard_size: int = CAPACITY_ITEMS) -> None:
    grouped: dict[tuple[str, Any], list[dict[str, Any]]] = {}
    for fact in facts:
        grouped.setdefault((str(fact["category"]), fact["source_doc_id"]), []).append(fact)
    for group in grouped.values():
        group.sort(key=lambda fact: int(fact["fact_id"]))
        for index, fact in enumerate(group):
            fact["_source_doc_shard"] = index // shard_size


def build_report(snapshot: Path, source: Path) -> dict[str, Any]:
    facts = load_active_facts(snapshot)
    annotate_source_doc_shards(facts)
    schemes = [
        _bucket_rows(
            facts,
            "category",
            lambda fact: f"cat:{fact['category']}",
        ),
        _bucket_rows(
            facts,
            "category_source_doc",
            lambda fact: f"cat:{fact['category']}|doc:{fact['source_doc_id'] or 'none'}",
        ),
        _bucket_rows(
            facts,
            "category_document_family",
            lambda fact: f"cat:{fact['category']}|family:{document_family(fact['source'])}",
        ),
        _bucket_rows(
            facts,
            "category_source_doc_shard256",
            _source_doc_shard_key,
        ),
    ]

    active_by_category = Counter(str(fact["category"]) for fact in facts)
    recommendation = _recommend(schemes)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_db": str(source),
        "snapshot_db": str(snapshot),
        "read_only": True,
        "hrr_dim": HRR_DIM,
        "capacity_items": CAPACITY_ITEMS,
        "active_facts_scanned": len(facts),
        "active_by_category": dict(active_by_category.most_common()),
        "schemes": schemes,
        "recommendation": recommendation,
    }


def _recommend(schemes: list[dict[str, Any]]) -> dict[str, Any]:
    viable = [
        scheme
        for scheme in schemes
        if scheme["banks_over_capacity"] == 0 and scheme["missing_hrr_vectors"] == 0
    ]
    if viable:
        best = min(viable, key=lambda item: (item["bank_count"], -item["max_snr"]))
        return {
            "status": "viable_without_scope",
            "preferred_scheme": best["scheme"],
            "reason": "all virtual banks are below HRR capacity without adding scope schema",
        }
    best = min(schemes, key=lambda item: (item["banks_over_capacity"], item["max_fact_count"]))
    return {
        "status": "needs_more_partitioning",
        "preferred_scheme": best["scheme"],
        "reason": "no tested scheme fully clears capacity pressure",
    }


def write_reports(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "hrr_bank_partition_audit.json"
    md_path = output_dir / "hrr_bank_partition_audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# HRR Bank Partition Audit",
        "",
        "## Safety",
        "",
        "- Source database was copied with SQLite backup API.",
        "- The audit reads the copied snapshot only; it does not write memory_banks, facts, schema, or provenance.",
        "- Schemes below are virtual partitions for measurement, not persisted schema.",
        f"- Source DB: `{report['source_db']}`",
        f"- Snapshot DB: `{report['snapshot_db']}`",
        "",
        "## Summary",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- active_facts_scanned: {report['active_facts_scanned']}",
        f"- hrr_dim: {report['hrr_dim']}",
        f"- capacity_items: {report['capacity_items']}",
        f"- recommendation: {report['recommendation']['status']} / {report['recommendation']['preferred_scheme']}",
        f"- recommendation_reason: {report['recommendation']['reason']}",
        "",
        "## Scheme Comparison",
        "",
        "| scheme | banks | max_fact_count | max_snr | over_capacity | snr_below_2 | missing_hrr |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for scheme in report["schemes"]:
        lines.append(
            f"| {scheme['scheme']} | {scheme['bank_count']} | {scheme['max_fact_count']} | "
            f"{scheme['max_snr']} | {scheme['banks_over_capacity']} | "
            f"{scheme['banks_with_snr_below_2']} | {scheme['missing_hrr_vectors']} |"
        )

    for scheme in report["schemes"]:
        lines += [
            "",
            f"## Top Banks: {scheme['scheme']}",
            "",
            "| bank | facts | snr | over_capacity | doc | source |",
            "|---|---:|---:|---|---:|---|",
        ]
        for row in scheme["top_banks"]:
            source = str(row.get("source") or "").replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {row['bank_name']} | {row['fact_count']} | {row['snr']} | "
                f"{row['over_capacity']} | {row.get('source_doc_id')} | {source} |"
            )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=_default_db_path())
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("reports/snapshots"))
    args = parser.parse_args()

    snapshot = create_snapshot(args.db, args.snapshot_dir)
    report = build_report(snapshot, args.db)
    json_path, md_path = write_reports(report, args.output_dir)
    print(f"snapshot={snapshot}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    print(f"active_facts_scanned={report['active_facts_scanned']}")
    for scheme in report["schemes"]:
        print(
            f"{scheme['scheme']}: banks={scheme['bank_count']} "
            f"max={scheme['max_fact_count']} snr={scheme['max_snr']} "
            f"over_capacity={scheme['banks_over_capacity']}"
        )
    print(
        "recommendation="
        f"{report['recommendation']['status']}:{report['recommendation']['preferred_scheme']}"
    )


if __name__ == "__main__":
    main()
