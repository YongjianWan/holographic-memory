"""Load real desktop files into a temp DB for safe P1-2 consolidation trial."""
import os
import sys
import tempfile
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if "hermes_state" not in sys.modules:
    hermes_state = types.ModuleType("hermes_state")
    hermes_state.apply_wal_with_fallback = lambda conn, db_label="": None
    sys.modules["hermes_state"] = hermes_state

if "hermes_constants" not in sys.modules:
    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: Path(tempfile.gettempdir())
    hermes_constants.display_hermes_home = lambda: tempfile.gettempdir()
    sys.modules["hermes_constants"] = hermes_constants

from store import MemoryStore, _LLMExtractor


def _resolve_model_call():
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
        except Exception:
            pass
    return None


def _read_text_flexible(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def build_temp_db(file_paths: list[Path]) -> Path:
    model_call = _resolve_model_call()
    extractor = _LLMExtractor(model_call=model_call) if model_call else None

    db_path = Path(tempfile.mktemp(suffix="_p1_2_trial.db"))
    store = MemoryStore(db_path=str(db_path))
    try:
        for path in file_paths:
            if not path.exists():
                print(f"SKIP (not found): {path}")
                continue
            raw_text = _read_text_flexible(path)
            result = store.retain_document(
                raw_text,
                source=str(path),
                category="project",
                extractor=extractor,
            )
            print(f"{path.name}: {result['facts_added']} facts")
        total = store._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        print(f"\nTemp DB: {db_path}")
        print(f"Total facts: {total}")
    finally:
        store.close()
    return db_path


if __name__ == "__main__":
    desktop = Path.home() / "Desktop"
    files = [
        desktop / "AI智能检索与公文写作系统_需求文档.md",
        desktop / "rf_output.txt",
        desktop / "user_pasted_clipboard_long_content_as_file_说话人1 000001 嗯。女一。.txt",
        desktop / "今日.md",
        desktop / "梁局汇报PPT-实际演示版.md",
        desktop / "现状（部分）.txt",
    ]
    build_temp_db(files)
