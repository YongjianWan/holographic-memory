"""Evaluate retain_document extraction quality on a real document.

Reports three things the design doc calls for after retain_document lands:
1. Granularity — are extracted facts atomic (one fact per line) or coarse?
2. Token cost — prompt + output token count for LLM extraction, scaled to N files.
3. SNR warning — content word count + entity count crossing dim/4.

Usage:
    python eval_retain_quality.py
"""

from __future__ import annotations

import json
import math
import re
import sys
import tempfile
import types
from pathlib import Path

# Make the project source importable as standalone modules (avoiding the
# package-level __init__.py which depends on hermes internals).
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Stub hermes internals so store.py can load without the hermes runtime.
if "hermes_state" not in sys.modules:
    hermes_state = types.ModuleType("hermes_state")
    hermes_state.apply_wal_with_fallback = lambda conn, db_label="": None
    sys.modules["hermes_state"] = hermes_state

if "hermes_constants" not in sys.modules:
    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: Path(tempfile.gettempdir())
    hermes_constants.display_hermes_home = lambda: tempfile.gettempdir()
    sys.modules["hermes_constants"] = hermes_constants

import store  # noqa: E402
import holographic as hrr  # noqa: E402

# Optional tiktoken for realistic token-cost estimates.
try:
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENCODING = None


DOC_PATH = Path("C:/Users/sdses/Desktop/现状（部分）.txt")
HRR_DIM = 1024
SNR_THRESHOLD = HRR_DIM // 4


def count_tokens(text: str) -> int:
    if _ENCODING is None:
        return 0
    return len(_ENCODING.encode(text))


def count_clauses(text: str) -> int:
    """Rough proxy for how many clauses/ideas are packed into one fact."""
    # Chinese and Western clause separators.
    return len(re.findall(r"[，；、：,;:]", text))


def is_likely_atomic(text: str, entity_names: list[str]) -> tuple[bool, dict]:
    """Heuristic atomicity check. Returns (ok, details)."""
    content_items = store._content_item_count(text)
    clauses = count_clauses(text)
    entities = len(entity_names)
    # More than ~2 internal clause separators usually means multiple claims.
    multi_claim = clauses > 2
    # Very long sentences are suspect even without punctuation.
    too_long = content_items > 60
    # Multiple numeric signatures often mean several distinct facts.
    sig = store._extract_numeric_signature(text)
    multi_numeric = len(sig) > 2
    ok = not (multi_claim or too_long or multi_numeric)
    return ok, {
        "content_items": content_items,
        "clauses": clauses,
        "entities": entities,
        "numeric_signatures": sorted(sig),
        "multi_claim": multi_claim,
        "too_long": too_long,
        "multi_numeric": multi_numeric,
    }


def evaluate(raw_text: str) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        memory_store = store.MemoryStore(
            db_path=db_path,
            hrr_dim=HRR_DIM,
        )
        result = memory_store.retain_document(
            raw_text,
            source="桌面-现状（部分）.txt",
            category="project",
        )
        doc_id = result["doc_id"]

        rows = memory_store._conn.execute(
            "SELECT fact_id, content FROM facts WHERE source_doc_id = ? ORDER BY fact_id",
            (doc_id,),
        ).fetchall()

        facts: list[dict] = []
        snr_warnings = 0
        non_atomic = 0
        total_output_tokens = 0

        for row in rows:
            content: str = row["content"]
            entity_names = memory_store._extract_entities(content)
            content_items = store._content_item_count(content)
            entity_count = len(entity_names)
            n_items = content_items + entity_count
            snr = math.sqrt(HRR_DIM / n_items) if n_items else float("inf")
            over_capacity = n_items > SNR_THRESHOLD
            if over_capacity:
                snr_warnings += 1

            atomic_ok, atomic_details = is_likely_atomic(content, entity_names)
            if not atomic_ok:
                non_atomic += 1

            tokens = count_tokens(content)
            total_output_tokens += tokens

            facts.append(
                {
                    "fact_id": row["fact_id"],
                    "content": content,
                    "content_items": content_items,
                    "word_count": len(content.split()),
                    "entity_count": entity_count,
                    "capacity_items": n_items,
                    "snr": round(snr, 2),
                    "over_capacity": over_capacity,
                    "tokens": tokens,
                    "atomic_ok": atomic_ok,
                    "atomic_details": atomic_details,
                }
            )

        # LLM extraction cost estimate.
        llm_extractor = store._LLMExtractor(model_call=lambda p: "")
        prompt = llm_extractor._build_prompt(raw_text, "project")
        prompt_tokens = count_tokens(prompt)
        # Use fallback facts as a proxy for the LLM output size.
        output_tokens = total_output_tokens
        total_tokens = prompt_tokens + output_tokens

        memory_store.close()

        return {
            "document": {
                "path": str(DOC_PATH),
                "characters": len(raw_text),
                "lines": len(raw_text.splitlines()),
                "document_tokens": count_tokens(raw_text),
            },
            "retain_result": result,
            "facts": facts,
            "summary": {
                "fact_count": len(facts),
                "snr_warnings": snr_warnings,
                "non_atomic_facts": non_atomic,
                "prompt_tokens": prompt_tokens,
                "output_tokens": output_tokens,
                "total_tokens_per_doc": total_tokens,
                "capacity_threshold": SNR_THRESHOLD,
            },
        }
    finally:
        Path(db_path).unlink(missing_ok=True)


def print_report(report: dict) -> None:
    lines: list[str] = []

    doc = report["document"]
    lines.append("=" * 60)
    lines.append("retain_document 质量评估报告")
    lines.append("=" * 60)
    lines.append(f"文档: {doc['path']}")
    lines.append(f"字符数: {doc['characters']:,}  行数: {doc['lines']:,}  tokens: {doc['document_tokens']:,}")
    lines.append("")

    rr = report["retain_result"]
    lines.append(f"默认提取器: {rr['extractor_kind']}")
    lines.append(f"抽出 fact 数: {rr['facts_added']}")
    lines.append(f"doc_id: {rr['doc_id']}  status: {rr['status']}")
    lines.append("")

    summary = report["summary"]
    lines.append("-" * 60)
    lines.append("1. 粒度（是否原子）")
    lines.append("-" * 60)
    lines.append(f"疑似非原子 fact: {summary['non_atomic_facts']} / {summary['fact_count']}")
    lines.append("判定标准: 内部 clause 分隔符>2 或 词数>60 或 数字签名>2")
    lines.append("")
    lines.append("粒度最差的前 5 条:")
    coarse = [f for f in report["facts"] if not f["atomic_ok"]]
    coarse.sort(key=lambda f: f["capacity_items"], reverse=True)
    for i, f in enumerate(coarse[:5], 1):
        details = f["atomic_details"]
        snippet = f["content"].replace("\n", " ")[:120]
        lines.append(
            f"  {i}. fact_id={f['fact_id']} items={f['capacity_items']} "
            f"(content_items={f['content_items']}, entities={f['entity_count']}) "
            f"clauses={details['clauses']} numeric={details['numeric_signatures'][:3]}"
        )
        lines.append(f"     {snippet}")
    lines.append("")

    lines.append("-" * 60)
    lines.append("2. Token 成本（LLM 提炼估算）")
    lines.append("-" * 60)
    lines.append(f"单文件 prompt tokens:  {summary['prompt_tokens']:,}")
    lines.append(f"单文件 output tokens:  {summary['output_tokens']:,}")
    lines.append(f"单文件合计 tokens:     {summary['total_tokens_per_doc']:,}")
    lines.append("")
    rates = [
        ("gpt-4o-mini", 0.15, 0.60),  # USD per 1M tokens (public 2024 rates)
        ("kimi/国产常见", 1.0, 1.0),  # RMB per 1M tokens (rough placeholder)
    ]
    for name, in_rate, out_rate in rates:
        cost = (
            summary["prompt_tokens"] * in_rate
            + summary["output_tokens"] * out_rate
        ) / 1_000_000
        lines.append(f"  {name}: 单文件 ≈ {cost:.4f} {'USD' if name.startswith('gpt') else '元'}")
        lines.append(f"  {name}: 100 文件 ≈ {cost * 100:.2f} {'USD' if name.startswith('gpt') else '元'}")
    lines.append("")

    lines.append("-" * 60)
    lines.append("3. HRR SNR / 容量 warning")
    lines.append("-" * 60)
    lines.append(f"HRR dim={HRR_DIM}, 阈值 = dim/4 = {summary['capacity_threshold']}")
    lines.append(f"触发 warning 的 fact 数: {summary['snr_warnings']} / {summary['fact_count']}")
    lines.append("标准: content 词数 + entity 数 > 阈值")
    lines.append("")
    over = [f for f in report["facts"] if f["over_capacity"]]
    over.sort(key=lambda f: f["capacity_items"], reverse=True)
    for i, f in enumerate(over[:5], 1):
        snippet = f["content"].replace("\n", " ")[:120]
        lines.append(
            f"  {i}. fact_id={f['fact_id']} items={f['capacity_items']} "
            f"(content_items={f['content_items']}, entities={f['entity_count']}) SNR={f['snr']}"
        )
        lines.append(f"     {snippet}")
    lines.append("")

    lines.append("-" * 60)
    lines.append("4. 前 10 条 fact 明细")
    lines.append("-" * 60)
    for f in report["facts"][:10]:
        ok = "✓" if f["atomic_ok"] else "✗"
        warn = "⚠" if f["over_capacity"] else " "
        snippet = f["content"].replace("\n", " ")[:140]
        lines.append(
            f"{ok}{warn} id={f['fact_id']:3d} items={f['capacity_items']:3d} "
            f"(content={f['content_items']:3d}+entities={f['entity_count']:2d}) "
            f"tokens={f['tokens']:4d} | {snippet}"
        )
    lines.append("")

    report_text = "\n".join(lines)
    print(report_text)
    out_path = PROJECT_ROOT / "eval_retain_report.txt"
    out_path.write_text(report_text, encoding="utf-8")
    print(f"\n完整报告已写入: {out_path}")

    # Also dump machine-readable JSON next to it.
    json_path = PROJECT_ROOT / "eval_retain_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"机器可读 JSON: {json_path}")


def main() -> None:
    if not DOC_PATH.exists():
        print(f"文档不存在: {DOC_PATH}")
        sys.exit(1)

    raw_text = DOC_PATH.read_text(encoding="utf-8")
    report = evaluate(raw_text)
    print_report(report)


if __name__ == "__main__":
    main()
