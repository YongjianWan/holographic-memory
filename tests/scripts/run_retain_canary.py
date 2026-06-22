"""Canary retain of 3-5 real documents into a temp DB for LLM extraction QA.

Reports:
- facts per file / per chunk
- average fact length and word count
- estimated input/output tokens (cl100k_base)
- sampled facts for manual granularity review
- any HRR capacity / SNR warnings logged by the store

Usage:
    python tests/scripts/run_retain_canary.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path
from collections.abc import Callable

PROJECT_ROOT = Path(__file__).absolute().parent.parent.parent
PARENT_DIR = PROJECT_ROOT.parent
if "" in sys.path:
    sys.path.remove("")
sys.path.insert(0, str(PARENT_DIR))

if "hermes_state" not in sys.modules:
    hermes_state = types.ModuleType("hermes_state")
    hermes_state.apply_wal_with_fallback = lambda conn, db_label="": None
    sys.modules["hermes_state"] = hermes_state

if "hermes_constants" not in sys.modules:
    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: Path(tempfile.gettempdir())
    hermes_constants.display_hermes_home = lambda: tempfile.gettempdir()
    sys.modules["hermes_constants"] = hermes_constants

if "agent.memory_provider" not in sys.modules:
    memory_provider = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        @property
        def name(self) -> str:
            return "stub"

    memory_provider.MemoryProvider = MemoryProvider
    sys.modules["agent.memory_provider"] = memory_provider
    sys.modules.setdefault("agent", types.ModuleType("agent"))

if "tools.registry" not in sys.modules:
    tools_registry = types.ModuleType("tools.registry")
    tools_registry.tool_error = lambda message: f"ERROR: {message}"
    sys.modules["tools.registry"] = tools_registry
    sys.modules.setdefault("tools", types.ModuleType("tools"))

if "hermes_cli.config" not in sys.modules:
    hermes_cli_config = types.ModuleType("hermes_cli.config")

    def _cfg_get(config: dict, *keys: str, default=None):
        current = config
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current if current is not None else default

    hermes_cli_config.cfg_get = _cfg_get
    sys.modules["hermes_cli.config"] = hermes_cli_config
    sys.modules.setdefault("hermes_cli", types.ModuleType("hermes_cli"))

from holographic.extractors import _LLMExtractor  # noqa: E402
from holographic.store import MemoryStore  # noqa: E402

try:
    import tiktoken
    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENCODING = None


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _resolve_model_call() -> Callable[[str], str] | None:
    ds_key = os.environ.get("DEEPSEEK_API_KEY")
    if ds_key:
        try:
            from openai import OpenAI
            base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
            client = OpenAI(api_key=ds_key, base_url=base_url)

            def model_call(prompt: str) -> str:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    stream=False,
                )
                return resp.choices[0].message.content or ""

            return model_call
        except Exception as e:
            print(f"Failed to initialize DeepSeek client: {e}")
    return None


def _count_tokens(text: str) -> int:
    if _ENCODING is None:
        return len(text) // 4  # rough fallback
    return len(_ENCODING.encode(text))


def _wrap_with_token_count(model_call: Callable[[str], str]) -> tuple[Callable[[str], str], list[dict]]:
    calls: list[dict] = []

    def wrapped(prompt: str) -> str:
        response = model_call(prompt)
        calls.append({
            "prompt_tokens": _count_tokens(prompt),
            "response_tokens": _count_tokens(response),
        })
        return response

    return wrapped, calls


def run_canary(file_paths: list[Path], max_chunk_tokens: int = 6000) -> dict:
    model_call = _resolve_model_call()
    if model_call is None:
        raise RuntimeError("No LLM API key available; cannot run LLM canary.")

    wrapped_call, call_log = _wrap_with_token_count(model_call)
    extractor = _LLMExtractor(model_call=wrapped_call)

    db_path = Path(tempfile.mktemp(suffix="_retain_canary.db"))
    store = MemoryStore(db_path=str(db_path))

    try:
        file_reports = []
        total_facts = 0
        total_input_tokens = 0
        total_output_tokens = 0

        for path in file_paths:
            raw_text = _read_text(path)
            result = store.retain_document(
                raw_text,
                source=str(path),
                category="project",
                extractor=extractor,
                max_chunk_tokens=max_chunk_tokens,
            )

            facts_added = result.get("facts_added", 0)
            chunks_processed = result.get("chunks_processed", 1)
            total_facts += facts_added
            file_input = sum(c["prompt_tokens"] for c in call_log[-chunks_processed:])
            file_output = sum(c["response_tokens"] for c in call_log[-chunks_processed:])
            total_input_tokens += file_input
            total_output_tokens += file_output

            # Fetch the actual facts from the DB for length analysis.
            fact_rows = store._conn.execute(
                "SELECT content FROM facts WHERE source_doc_id = ? ORDER BY fact_id",
                (result["doc_id"],),
            ).fetchall()
            contents = [r["content"] for r in fact_rows]
            lengths = [len(c) for c in contents]
            word_counts = [len(c.split()) for c in contents]

            file_reports.append({
                "path": str(path),
                "facts_added": facts_added,
                "chunks": chunks_processed,
                "input_tokens": file_input,
                "output_tokens": file_output,
                "avg_fact_chars": sum(lengths) / len(lengths) if lengths else 0,
                "avg_fact_words": sum(word_counts) / len(word_counts) if word_counts else 0,
                "max_fact_chars": max(lengths) if lengths else 0,
                "sample_facts": contents[:5],
            })

        return {
            "db_path": str(db_path),
            "total_facts": total_facts,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "files": file_reports,
        }
    finally:
        store.close()


def main() -> int:
    desktop = Path.home() / "Desktop"
    files = [
        desktop / "今日.md",
        desktop / "梁局汇报PPT-实际演示版.md",
        desktop / "AI智能检索与公文写作系统_需求文档.md",
        desktop / "现状（部分）.txt",
        # Large file, commented out for first canary to control cost:
        # desktop / "文档" / "6.5 投促局会议纪要.md",
    ]
    files = [f for f in files if f.exists()]
    if not files:
        print("No canary files found.")
        return 1

    report = run_canary(files)
    print(f"Canary DB: {report['db_path']}")
    print(f"Total facts extracted: {report['total_facts']}")
    print(f"Total estimated input tokens:  {report['total_input_tokens']}")
    print(f"Total estimated output tokens: {report['total_output_tokens']}")
    print()

    for fr in report["files"]:
        print(f"--- {fr['path']} ---")
        print(f"  facts: {fr['facts_added']}  chunks: {fr['chunks']}")
        print(f"  input tokens: {fr['input_tokens']}  output tokens: {fr['output_tokens']}")
        print(f"  avg chars/fact: {fr['avg_fact_chars']:.1f}  avg words/fact: {fr['avg_fact_words']:.1f}  max chars: {fr['max_fact_chars']}")
        print("  sample facts:")
        for i, fact in enumerate(fr["sample_facts"], 1):
            print(f"    {i}. {fact[:200]}{'...' if len(fact) > 200 else ''}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
