"""Retain this repository's canonical project documents into the live DB.

The script intentionally excludes generated reports, pytest cache, and review
scratch files. It writes only after creating a SQLite backup of the target DB.

Usage:
    python tests/scripts/run_retain_project_docs.py --dry-run
    python tests/scripts/run_retain_project_docs.py --yes
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import types
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

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

ROOT_DOCS = {
    "AGENTS.md",
    "CHANGELOG.md",
    "ROADMAP.md",
    "SESSION.md",
    "TECH_DEBT.md",
}


def _default_db_path() -> Path:
    return Path("C:/Users/sdses/AppData/Local/hermes/memory_store.db")


def discover_project_docs() -> list[Path]:
    files = [PROJECT_ROOT / name for name in sorted(ROOT_DOCS)]
    files.extend(sorted((PROJECT_ROOT / "docs").rglob("*.md")))
    return [path for path in files if path.exists() and path.is_file()]


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
        except Exception as exc:
            print(f"Failed to initialize DeepSeek client: {exc}")
    return None


def _backup_db(db_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = PROJECT_ROOT / "reports" / "live_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"memory_store_before_project_docs_{timestamp}.db"

    src = sqlite3.connect(str(db_path))
    try:
        src.execute("PRAGMA wal_checkpoint(FULL)")
        dst = sqlite3.connect(str(backup_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return backup_path


def _counts(store: MemoryStore) -> dict:
    return {
        "facts_total": store._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
        "facts_active": store._conn.execute(
            "SELECT COUNT(*) FROM facts WHERE merged_into IS NULL"
        ).fetchone()[0],
        "documents_total": store._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
    }


def retain_project_docs(db_path: Path, files: list[Path], yes: bool, dry_run: bool) -> dict:
    if dry_run:
        return {
            "dry_run": True,
            "files": [
                {
                    "path": str(path.relative_to(PROJECT_ROOT)),
                    "chars": len(_read_text(path)),
                }
                for path in files
            ],
        }

    db_path = db_path.expanduser().absolute()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    if not yes:
        answer = input("This will write project docs into the live memory store. Continue? [y/N] ")
        if answer.lower() not in ("y", "yes"):
            return {"aborted": True}

    model_call = _resolve_model_call()
    if model_call is None:
        raise RuntimeError("No LLM API key available; refusing to retain project docs with fallback extraction.")

    backup_path = _backup_db(db_path)
    extractor = _LLMExtractor(model_call=model_call)
    store = MemoryStore(db_path=str(db_path))
    try:
        before = _counts(store)
        file_reports = []
        for path in files:
            result = store.retain_document(
                _read_text(path),
                source=str(path.relative_to(PROJECT_ROOT)),
                category="project",
                extractor=extractor,
                max_chunk_tokens=6000,
            )
            file_reports.append(
                {
                    "path": str(path.relative_to(PROJECT_ROOT)),
                    "status": result["status"],
                    "doc_id": result["doc_id"],
                    "facts_added": result["facts_added"],
                    "fact_ids": result["fact_ids"],
                    "chunks_processed": result["chunks_processed"],
                    "extraction_errors": result["extraction_errors"],
                }
            )
        after = _counts(store)
        return {
            "dry_run": False,
            "backup_path": str(backup_path),
            "before": before,
            "after": after,
            "delta": {key: after[key] - before[key] for key in before},
            "files": file_reports,
        }
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Retain canonical project docs into live DB.")
    parser.add_argument("--db", default=str(_default_db_path()), help="Path to memory_store.db")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--dry-run", action="store_true", help="List files without writing")
    args = parser.parse_args()

    files = discover_project_docs()
    result = retain_project_docs(Path(args.db), files, yes=args.yes, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("aborted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
