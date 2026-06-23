"""Read-only Gate A/B audit for scope separability.

The audit never derives scope from ``source_doc_id``. Facts are classified
from their own content using a multi-label taxonomy discovered from the
corpus. Outputs are reports only; the database is opened read-only.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Callable


_META_PATTERNS = (
    re.compile(r"^(等等|让我|我需要|我应该|我先|再看|实际上用户说|题目说)"),
    re.compile(r"(用户要求我|从文本中提取|原子事实|每行一个事实|需要确保.*自包含)"),
    re.compile(r"(这是Claude的建议|区分.*用户.*Claude|作为事实提取)"),
    re.compile(r"</?think>", re.IGNORECASE),
    re.compile(r'"\s*-\s*\d+\s*[分字].*(OK|通过|太短)', re.IGNORECASE),
)


def detect_extraction_meta(content: str) -> list[str]:
    """Return conservative reasons that a row may be extractor self-talk."""
    reasons = [pattern.pattern for pattern in _META_PATTERNS if pattern.search(content)]
    if len(content) > 80 and any(
        marker in content
        for marker in ("用户", "文本", "提取", "事实", "自包含", "应该", "需要")
    ):
        reasons.append("long_extractor_discourse")
    return reasons


def summarize_scope_labels(labels: dict[int, list[str]]) -> dict:
    scope_counts: Counter[str] = Counter()
    cardinality = {"0": 0, "1": 0, "2": 0, "3+": 0}
    for scopes in labels.values():
        unique = list(dict.fromkeys(scope.strip() for scope in scopes if scope.strip()))
        scope_counts.update(unique)
        if not unique:
            cardinality["0"] += 1
        elif len(unique) == 1:
            cardinality["1"] += 1
        elif len(unique) == 2:
            cardinality["2"] += 1
        else:
            cardinality["3+"] += 1
    total = len(labels)
    largest = max(scope_counts.values(), default=0)
    return {
        "facts_classified": total,
        "cardinality": cardinality,
        "scope_counts": dict(scope_counts.most_common()),
        "max_scope_share": round(largest / total, 4) if total else 0.0,
    }


def summarize_batch_diff(
    before: dict[int, dict], after: dict[int, dict]
) -> dict:
    inserted_ids = set(after) - set(before)
    merge_deltas: dict[int, int] = {}
    for fact_id, row in after.items():
        previous = before.get(fact_id, {}).get("retrieval_count", 0)
        delta = int(row.get("retrieval_count", 0)) - int(previous)
        if delta > 0:
            merge_deltas[fact_id] = delta
    merge_events = sum(merge_deltas.values())
    return {
        "inserted_rows": len(inserted_ids),
        "unique_fact_ids": len(after),
        "merge_targets": len(merge_deltas),
        "merge_events": merge_events,
        "successful_fact_id_returns": len(inserted_ids) + merge_events,
    }


def _open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _load_active_facts(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT fact_id, content, category, source_doc_id, retrieval_count
            FROM facts
            WHERE merged_into IS NULL
            ORDER BY fact_id
            """
        )
    ]


def _load_snapshot(path: Path) -> dict[int, dict]:
    with _open_readonly(path) as conn:
        return {
            int(row["fact_id"]): dict(row)
            for row in conn.execute(
                "SELECT fact_id, retrieval_count FROM facts WHERE merged_into IS NULL"
            )
        }


def _parse_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(text[start : end + 1])


def _discover_taxonomy(
    facts: list[dict], model_call: Callable[[str], str], sample_size: int = 240
) -> list[str]:
    step = max(1, len(facts) // sample_size)
    sample = facts[::step][:sample_size]
    payload = [{"id": f["fact_id"], "content": f["content"]} for f in sample]
    prompt = (
        "Infer a compact domain taxonomy from these memory facts. Domains describe "
        "subject areas, not fact types, people, source files, or temporary tasks. "
        "Return 4-12 Chinese domain names. Do not force unrelated facts together. "
        'Output JSON only: {"scopes":["领域1","领域2"]}.\n\n'
        + json.dumps(payload, ensure_ascii=False)
    )
    data = _parse_json_object(model_call(prompt))
    scopes = [str(scope).strip() for scope in data.get("scopes", []) if str(scope).strip()]
    if not 4 <= len(scopes) <= 12:
        raise ValueError(f"taxonomy size must be 4-12, got {len(scopes)}")
    return list(dict.fromkeys(scopes))


def _classify_batch(
    batch: list[dict], scopes: list[str], model_call: Callable[[str], str]
) -> dict[int, list[str]]:
    prompt = (
        "Classify each fact independently into zero or more scopes from the allowed "
        "list. Use multiple scopes when the fact genuinely spans domains. Use [] "
        "when none fit or the fact is unclear. Never infer scope from source or "
        "person names alone. Output JSON only as "
        '{"labels":[{"fact_id":1,"scopes":["领域"]}]}.\n\n'
        f"Allowed scopes: {json.dumps(scopes, ensure_ascii=False)}\n"
        f"Facts: {json.dumps([{'fact_id': f['fact_id'], 'content': f['content']} for f in batch], ensure_ascii=False)}"
    )
    data = _parse_json_object(model_call(prompt))
    allowed = set(scopes)
    result: dict[int, list[str]] = {}
    for item in data.get("labels", []):
        fact_id = int(item["fact_id"])
        result[fact_id] = [
            scope for scope in item.get("scopes", []) if scope in allowed
        ]
    for fact in batch:
        result.setdefault(int(fact["fact_id"]), [])
    return result


def _sample_gate_a(facts: list[dict], size: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    if len(facts) <= size:
        return list(facts)
    return sorted(rng.sample(facts, size), key=lambda fact: fact["fact_id"])


def _render_markdown(report: dict) -> str:
    lines = [
        "# Scope Gate A/B Read-only Audit",
        "",
        "## Safety and counting contract",
        "",
        "- Database opened read-only; no facts, schema, or provenance were modified.",
        "- Scope labels come from fact content and are multi-label.",
        "- `source_doc_id` is displayed only for traceability, never used to infer scope.",
        "- Gate A rows exclude extraction-meta candidates but those candidates remain listed separately.",
        "",
        "## Batch ledger",
        "",
    ]
    for key, value in report.get("batch_ledger", {}).items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## Extraction-meta candidates", ""]
    lines.append(f"- count: {len(report['meta_candidates'])}")
    lines += ["", "## Gate A: manual 50-fact review", ""]
    lines.append("| fact_id | person-independent? | notes | content |")
    lines.append("|---:|---|---|---|")
    for fact in report["gate_a_sample"]:
        content = fact["content"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {fact['fact_id']} |  |  | {content} |")
    lines += ["", "## Gate B: multi-label scope distribution", ""]
    lines.append(f"- discovered scopes: {', '.join(report['scopes'])}")
    for key, value in report["scope_stats"]["cardinality"].items():
        lines.append(f"- {key} scopes: {value}")
    lines.append(f"- largest scope share: {report['scope_stats']['max_scope_share']:.1%}")
    lines += ["", "| scope | facts | share |", "|---|---:|---:|"]
    total = report["scope_stats"]["facts_classified"]
    for scope, count in report["scope_stats"]["scope_counts"].items():
        lines.append(f"| {scope} | {count} | {count / total:.1%} |")
    return "\n".join(lines) + "\n"


def run(
    db_path: Path,
    before_db: Path,
    output_dir: Path,
    model_call: Callable[[str], str],
    *,
    sample_size: int = 50,
    batch_size: int = 80,
    seed: int = 20260623,
) -> dict:
    with _open_readonly(db_path) as conn:
        facts = _load_active_facts(conn)
    meta_candidates = []
    clean_facts = []
    for fact in facts:
        reasons = detect_extraction_meta(fact["content"])
        if reasons:
            meta_candidates.append({**fact, "reasons": reasons})
        else:
            clean_facts.append(fact)

    print(
        f"loaded active={len(facts)} clean={len(clean_facts)} "
        f"meta_candidates={len(meta_candidates)}",
        flush=True,
    )
    print("discovering taxonomy...", flush=True)
    scopes = _discover_taxonomy(clean_facts, model_call)
    print(f"taxonomy={scopes}", flush=True)
    labels: dict[int, list[str]] = {}
    for start in range(0, len(clean_facts), batch_size):
        end = min(start + batch_size, len(clean_facts))
        print(
            f"classifying batch {start // batch_size + 1}: facts {start + 1}-{end}",
            flush=True,
        )
        labels.update(
            _classify_batch(clean_facts[start : start + batch_size], scopes, model_call)
        )

    report = {
        "database": str(db_path),
        "read_only": True,
        "total_active_facts": len(facts),
        "clean_facts": len(clean_facts),
        "meta_candidates": meta_candidates,
        "batch_ledger": summarize_batch_diff(
            _load_snapshot(before_db),
            {int(f["fact_id"]): f for f in facts},
        ),
        "scopes": scopes,
        "scope_labels": {str(k): v for k, v in sorted(labels.items())},
        "scope_stats": summarize_scope_labels(labels),
        "gate_a_sample": _sample_gate_a(clean_facts, sample_size, seed),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "scope_gate_audit.json"
    md_path = output_dir / "scope_gate_audit.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--before-db", required=True, type=Path)
    parser.add_argument("--output-dir", default=Path("reports"), type=Path)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    parent = project_root.parent
    hermes_root = Path.home() / "AppData/Local/hermes/hermes-agent"
    sys.path[:0] = [str(parent), str(hermes_root)]
    import os
    from openai import OpenAI

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is unavailable")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    client = OpenAI(
        api_key=api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        timeout=120.0,
        max_retries=1,
    )

    def model_call(prompt: str) -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            stream=False,
        )
        return response.choices[0].message.content or ""

    report = run(args.db, args.before_db, args.output_dir, model_call)
    print(
        json.dumps(
            {
                "total_active_facts": report["total_active_facts"],
                "clean_facts": report["clean_facts"],
                "meta_candidates": len(report["meta_candidates"]),
                "scopes": report["scopes"],
                "scope_stats": report["scope_stats"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
