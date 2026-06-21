"""Batch retain_document evaluation over 3-5 real files.

Reports per-file and aggregate metrics for:
  - extraction granularity (atomic vs coarse facts)
  - estimated LLM token cost
  - HRR SNR capacity warnings

Usage:
    python batch_retain_eval.py [--watch-dir DIR] [--patterns *.txt *.md]

Defaults scan the Desktop for .txt / .md files. Extend PARSERS to add
.docx / .pdf support when those files appear in the real corpus.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import tempfile
import types
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

try:
    from openai import OpenAI

    _HAS_OPENAI = True
except Exception:  # pragma: no cover
    _HAS_OPENAI = False

# Project root for direct module imports.
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Hermes stubs so store.py loads without the hermes runtime.
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

logger = logging.getLogger(__name__)

# Optional parsers for richer file types.
try:
    from docx import Document as _DocxDocument

    _HAS_DOCX = True
except Exception:  # pragma: no cover
    _HAS_DOCX = False

try:
    import PyPDF2

    _HAS_PYPDF2 = True
except Exception:  # pragma: no cover
    _HAS_PYPDF2 = False

try:
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover
    _ENCODING = None


class Parser(Protocol):
    def __call__(self, path: Path) -> str:
        ...


def _parse_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_docx(path: Path) -> str:
    if not _HAS_DOCX:
        raise RuntimeError("python-docx not installed")
    doc = _DocxDocument(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _parse_pdf(path: Path) -> str:
    if not _HAS_PYPDF2:
        raise RuntimeError("PyPDF2 not installed")
    reader = PyPDF2.PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n".join(parts)


PARSERS: dict[str, Callable[[Path], str]] = {
    ".txt": _parse_text,
    ".md": _parse_text,
    ".docx": _parse_docx,
    ".pdf": _parse_pdf,
}


class _DeepSeekExtractor:
    """One-shot DeepSeek API extractor; accumulates real token usage."""

    kind = "llm"

    def __init__(self, model: str) -> None:
        if not _HAS_OPENAI:
            raise RuntimeError("openai package not installed")
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY not set")
        base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model
        self.usage = {"prompt": 0, "completion": 0}
        self._client = OpenAI(api_key=key, base_url=base)

    def extract(self, raw_text: str, category: str) -> list[str]:
        # Reuse the hardened prompt from store._LLMExtractor.
        builder = store._LLMExtractor(model_call=lambda _p: "")
        prompt = builder._build_prompt(raw_text, category)
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                stream=False,
            )
            if resp.usage:
                self.usage["prompt"] += resp.usage.prompt_tokens
                self.usage["completion"] += resp.usage.completion_tokens
            return builder._parse_response(resp.choices[0].message.content or "")
        except Exception:
            return []


def token_count(text: str) -> int:
    if _ENCODING is None:
        return 0
    return len(_ENCODING.encode(text))


def count_clauses(text: str) -> int:
    return len(re.findall(r"[，；、：,;:]", text))


def is_likely_atomic(content: str, entity_names: list[str]) -> tuple[bool, dict]:
    items = store._content_item_count(content)
    clauses = count_clauses(content)
    entities = len(entity_names)
    sig = store._extract_numeric_signature(content)
    multi_claim = clauses > 2
    too_long = items > 60
    multi_numeric = len(sig) > 2
    ok = not (multi_claim or too_long or multi_numeric)
    return ok, {
        "items": items,
        "clauses": clauses,
        "entities": entities,
        "numeric_signatures": sorted(sig),
        "multi_claim": multi_claim,
        "too_long": too_long,
        "multi_numeric": multi_numeric,
    }


def evaluate_file(
    memory_store: store.MemoryStore,
    path: Path,
    category: str,
    extractor: store.FactExtractor | None = None,
) -> dict:
    ext = path.suffix.lower()
    parser = PARSERS.get(ext)
    if parser is None:
        raise ValueError(f"No parser for extension {ext!r}")

    raw_text = parser(path)
    if not raw_text.strip():
        raise ValueError("File is empty")

    doc_tokens = token_count(raw_text)

    result = memory_store.retain_document(
        raw_text,
        source=str(path.name),
        category=category,
        extractor=extractor,
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
    worst: dict | None = None

    for row in rows:
        content: str = row["content"]
        entity_names = memory_store._extract_entities(content)
        content_items = store._content_item_count(content)
        entity_count = len(entity_names)
        capacity_items = content_items + entity_count
        snr = math.sqrt(memory_store.hrr_dim / capacity_items) if capacity_items else float("inf")
        over_capacity = capacity_items > memory_store.hrr_dim // 4
        if over_capacity:
            snr_warnings += 1

        atomic_ok, atomic_details = is_likely_atomic(content, entity_names)
        if not atomic_ok:
            non_atomic += 1

        tokens = token_count(content)
        total_output_tokens += tokens

        fact_record = {
            "fact_id": row["fact_id"],
            "content": content,
            "content_items": content_items,
            "entity_count": entity_count,
            "capacity_items": capacity_items,
            "snr": round(snr, 2),
            "over_capacity": over_capacity,
            "tokens": tokens,
            "atomic_ok": atomic_ok,
            "atomic_details": atomic_details,
        }
        facts.append(fact_record)

        if worst is None or capacity_items > worst["capacity_items"]:
            worst = fact_record

    if isinstance(extractor, _DeepSeekExtractor):
        # Real API usage.
        prompt_tokens = extractor.usage["prompt"]
        output_tokens = extractor.usage["completion"]
    else:
        # Fallback: estimate via tiktoken.
        llm_extractor = store._LLMExtractor(model_call=lambda p: "")
        prompt = llm_extractor._build_prompt(raw_text, category)
        prompt_tokens = token_count(prompt)
        output_tokens = total_output_tokens

    return {
        "path": str(path),
        "extension": ext,
        "characters": len(raw_text),
        "document_tokens": doc_tokens,
        "extractor_kind": result["extractor_kind"],
        "facts_added": result["facts_added"],
        "chunks_processed": result.get("chunks_processed", 1),
        "fact_count": len(facts),
        "non_atomic": non_atomic,
        "snr_warnings": snr_warnings,
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "total_tokens": prompt_tokens + output_tokens,
        "worst_fact": worst,
        "facts": facts,
    }


def run(
    watch_dir: Path,
    patterns: list[str],
    category: str,
    extractor: store.FactExtractor | None = None,
) -> dict:
    files: list[Path] = []
    for pat in patterns:
        files.extend(watch_dir.glob(pat))

    skip_names = {
        "eval_retain_report.txt",
        "eval_retain_report.json",
        "batch_retain_report.txt",
        "batch_retain_report.json",
    }
    files = sorted({p for p in files if p.name not in skip_names and p.suffix.lower() in PARSERS})

    if not files:
        raise RuntimeError(f"No matching files found in {watch_dir} for patterns {patterns}")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    reports: list[dict] = []
    try:
        memory_store = store.MemoryStore(db_path=db_path, hrr_dim=1024)
        for path in files:
            try:
                reports.append(evaluate_file(memory_store, path, category, extractor))
            except Exception as exc:
                logger.warning("Skipping %s: %s", path, exc)
                reports.append({"path": str(path), "error": str(exc)})
        memory_store.close()
    finally:
        Path(db_path).unlink(missing_ok=True)

    ok_reports = [r for r in reports if "error" not in r]
    total_facts = sum(r["fact_count"] for r in ok_reports)
    total_non_atomic = sum(r["non_atomic"] for r in ok_reports)
    total_snr_warnings = sum(r["snr_warnings"] for r in ok_reports)
    total_prompt = sum(r["prompt_tokens"] for r in ok_reports)
    total_output = sum(r["output_tokens"] for r in ok_reports)

    return {
        "watch_dir": str(watch_dir),
        "patterns": patterns,
        "category": category,
        "files": reports,
        "aggregate": {
            "files_evaluated": len(ok_reports),
            "files_skipped": len(reports) - len(ok_reports),
            "total_facts": total_facts,
            "total_non_atomic": total_non_atomic,
            "total_snr_warnings": total_snr_warnings,
            "snr_warning_rate": round(total_snr_warnings / total_facts, 3) if total_facts else 0.0,
            "non_atomic_rate": round(total_non_atomic / total_facts, 3) if total_facts else 0.0,
            "total_prompt_tokens": total_prompt,
            "total_output_tokens": total_output,
            "total_tokens": total_prompt + total_output,
        },
    }


def print_report(report: dict) -> None:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("batch_retain_eval 报告")
    lines.append("=" * 70)
    lines.append(f"扫描目录: {report['watch_dir']}")
    lines.append(f"匹配模式: {report['patterns']}")
    lines.append(f"事实类别: {report['category']}")
    lines.append("")

    agg = report["aggregate"]
    lines.append("-" * 70)
    lines.append("汇总")
    lines.append("-" * 70)
    lines.append(f"评估文件数: {agg['files_evaluated']}")
    lines.append(f"跳过文件数: {agg['files_skipped']}")
    lines.append(f"总 fact 数: {agg['total_facts']}")
    lines.append(f"非原子 fact: {agg['total_non_atomic']} ({agg['non_atomic_rate']*100:.1f}%)")
    lines.append(f"SNR warning: {agg['total_snr_warnings']} ({agg['snr_warning_rate']*100:.1f}%)")
    lines.append(f"总 prompt tokens: {agg['total_prompt_tokens']:,}")
    lines.append(f"总 output tokens: {agg['total_output_tokens']:,}")
    lines.append(f"总 tokens: {agg['total_tokens']:,}")
    lines.append("")

    gpt_in, gpt_out = 0.15, 0.60
    gpt_cost = (agg["total_prompt_tokens"] * gpt_in + agg["total_output_tokens"] * gpt_out) / 1_000_000
    lines.append(f"按 gpt-4o-mini 估算总成本: ${gpt_cost:.4f} USD")
    lines.append("")

    lines.append("-" * 70)
    lines.append("逐文件明细")
    lines.append("-" * 70)
    for r in report["files"]:
        if "error" in r:
            lines.append(f"[SKIP] {r['path']}: {r['error']}")
            continue
        worst = r.get("worst_fact")
        worst_txt = ""
        if worst:
            snippet = worst["content"].replace("\n", " ")[:80]
            worst_txt = f" worst_items={worst['capacity_items']} SNR={worst['snr']} | {snippet}"
        chunks = r.get("chunks_processed", 1)
        lines.append(
            f"{r['path']}\n"
            f"  chars={r['characters']:,} doc_tokens={r['document_tokens']:,} "
            f"facts={r['fact_count']} non_atomic={r['non_atomic']} "
            f"snr_warn={r['snr_warnings']} chunks={chunks} "
            f"total_tokens={r['total_tokens']:,}\n"
            f"  {worst_txt}"
        )
    lines.append("")

    report_text = "\n".join(lines)
    print(report_text)

    txt_path = PROJECT_ROOT / "batch_retain_report.txt"
    json_path = PROJECT_ROOT / "batch_retain_report.json"
    txt_path.write_text(report_text, encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"文本报告: {txt_path}")
    print(f"JSON 报告: {json_path}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(description="Batch retain_document evaluation")
    parser.add_argument(
        "--watch-dir",
        type=Path,
        default=Path("C:/Users/sdses/Desktop"),
        help="Directory to scan for files (default: Desktop)",
    )
    parser.add_argument(
        "--patterns",
        nargs="+",
        default=["*.txt", "*.md"],
        help="Glob patterns to match (default: *.txt *.md)",
    )
    parser.add_argument(
        "--category",
        default="project",
        help="Category passed to retain_document (default: project)",
    )
    parser.add_argument(
        "--llm",
        choices=["fallback", "deepseek"],
        default="fallback",
        help="Extractor to use (default: fallback)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        help="DeepSeek model name (default: deepseek-v4-flash or DEEPSEEK_MODEL env)",
    )
    args = parser.parse_args()

    extractor: store.FactExtractor | None = None
    if args.llm == "deepseek":
        extractor = _DeepSeekExtractor(model=args.model)

    report = run(args.watch_dir, args.patterns, args.category, extractor)
    print_report(report)


if __name__ == "__main__":
    main()
