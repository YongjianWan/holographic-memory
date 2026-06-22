"""Retain a small batch of real documents into the live memory store.

Used for the §4 canary: 3-5 files first, then review 50 facts for go/no-go.
Documents are retained in chronological order (by mtime) and facts are
extracted via the LLM extractor.

Usage:
    python tests/scripts/run_retain_real_docs.py --yes
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import types
from pathlib import Path
from collections.abc import Callable
from datetime import datetime

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
    hermes_constants.get_hermes_home = lambda: Path("C:/Users/sdses/AppData/Local/hermes")
    hermes_constants.display_hermes_home = lambda: "C:/Users/sdses/AppData/Local/hermes"
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


def _read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def retain_batch(db_path: Path, files: list[Path], yes: bool = False) -> dict:
    db_path = db_path.expanduser().absolute()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    print(f"Target database: {db_path}")
    print(f"Files to retain (chronological order): {[f.name for f in files]}")
    if not yes:
        answer = input("This will write new facts into the live memory store. Continue? [y/N] ")
        if answer.lower() not in ("y", "yes"):
            print("Aborted.")
            return {"aborted": True}

    model_call = _resolve_model_call()
    if model_call is None:
        raise RuntimeError("No LLM API key available; cannot run LLM extraction.")

    extractor = _LLMExtractor(model_call=model_call)
    store = MemoryStore(db_path=str(db_path))

    try:
        before_facts = store._conn.execute(
            "SELECT COUNT(*) FROM facts WHERE merged_into IS NULL"
        ).fetchone()[0]

        file_reports = []
        for path in files:
            raw_text = _read_text(path)
            result = store.retain_document(
                raw_text,
                source=str(path),
                category="project",
                extractor=extractor,
                max_chunk_tokens=6000,
            )
            file_reports.append({
                "path": str(path),
                "facts_added": result["facts_added"],
                "chunks_processed": result["chunks_processed"],
                "extractor_kind": result["extractor_kind"],
            })

        after_facts = store._conn.execute(
            "SELECT COUNT(*) FROM facts WHERE merged_into IS NULL"
        ).fetchone()[0]

        return {
            "before_facts": before_facts,
            "after_facts": after_facts,
            "added_facts": after_facts - before_facts,
            "files": file_reports,
        }
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Retain canary real documents into live DB.")
    parser.add_argument("--db", default="C:/Users/sdses/AppData/Local/hermes/memory_store.db", help="Path to memory_store.db")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    desktop = Path.home() / "Desktop"
    candidate_files = [
        desktop / "现状（部分）.txt",
        desktop / "梁局汇报PPT-实际演示版.md",
        desktop / "今日.md",
        desktop / "AI智能检索与公文写作系统_需求文档.md",
    ]
    candidate_files = [f for f in candidate_files if f.exists()]
    # Sort by file modification time (oldest first).
    candidate_files.sort(key=lambda p: p.stat().st_mtime)

    result = retain_batch(Path(args.db), candidate_files, yes=args.yes)
    print(result)
    return 0 if not result.get("aborted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
