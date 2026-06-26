import os
import random
import sqlite3
from pathlib import Path
import sys
import types

PROJECT_ROOT = Path(__file__).absolute().parent.parent.parent
PARENT_DIR = PROJECT_ROOT.parent
if "" in sys.path:
    sys.path.remove("")
sys.path.insert(0, str(PARENT_DIR))

# Stubs
for mod_name, mod_setup in [
    ("hermes_state", lambda m: setattr(m, "apply_wal_with_fallback", lambda conn, db_label="": None)),
    ("hermes_constants", lambda m: (
        setattr(m, "get_hermes_home", lambda: Path("C:/Users/sdses/AppData/Local/hermes")),
        setattr(m, "display_hermes_home", lambda: "C:/Users/sdses/AppData/Local/hermes"),
    )),
]:
    if mod_name not in sys.modules:
        mod = types.ModuleType(mod_name)
        mod_setup(mod)
        sys.modules[mod_name] = mod

DB_PATH = "C:/Users/sdses/AppData/Local/hermes/memory_store.db"
CONTROL_ID_FILE = PROJECT_ROOT / "tests" / "scripts" / "_control_fact_ids.txt"

def _resolve_model_call():
    ds_key = os.environ.get("DEEPSEEK_API_KEY")
    if not ds_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
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

def audit_facts_batch(model_call, facts: list[dict]) -> dict[int, str]:
    """Audit a list of facts and return a dict of {fact_id: VERDICT}."""
    fact_lines = []
    for i, f in enumerate(facts):
        fact_lines.append(f"[{i+1}] (ID={f['fact_id']}) {f['content']}")

    prompt = (
        "You are a fact quality auditor. For each fact below, classify it as PASS or FAIL.\n\n"
        "PASS criteria (ALL must be met):\n"
        "- Objective, verifiable statement (not opinion/feeling unless attributed to a named speaker)\n"
        "- Self-contained: understandable without surrounding context\n"
        "- Has long-term recall value (not transient system state, chat noise, or session-specific data)\n"
        "- Concrete: contains specific details (names, numbers, dates, or clear claims)\n\n"
        "FAIL criteria (ANY triggers fail):\n"
        "- Psychological attribution or motive inference about the user\n"
        "- Transient system/dialogue state (e.g., 'currently has 23 memory entries')\n"
        "- Vague filler with no informational content\n"
        "- Compound sentence that should be split\n"
        "- Chat noise or pleasantries\n\n"
        "For each fact, output exactly one line: the number, PASS or FAIL, and a brief reason (< 15 words).\n"
        "Format: [N] PASS/FAIL reason\n\n"
        "Facts:\n" + "\n".join(fact_lines)
    )

    response = model_call(prompt)
    verdicts = {}
    for line in response.strip().splitlines():
        line = line.strip()
        if not line or not line.startswith("["):
            continue
        try:
            bracket_end = line.index("]")
            num = int(line[1:bracket_end])
            rest = line[bracket_end+1:].strip()
            verdict = "PASS" if rest.startswith("PASS") else "FAIL"
            idx = num - 1
            if 0 <= idx < len(facts):
                verdicts[facts[idx]["fact_id"]] = verdict
        except (ValueError, IndexError):
            continue
    return verdicts

def main():
    # Load .env
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Generate or load the 30 control fact IDs
    if not CONTROL_ID_FILE.exists():
        print("Generating 30 static control fact IDs...")
        rows = conn.execute(
            "SELECT fact_id FROM facts WHERE source_doc_id IN (1, 2, 3, 4, 5, 7, 9) AND merged_into IS NULL"
        ).fetchall()
        all_ids = [r["fact_id"] for r in rows]
        random.seed(12345)
        sampled_ids = random.sample(all_ids, min(30, len(all_ids)))
        CONTROL_ID_FILE.write_text("\n".join(map(str, sampled_ids)))
    else:
        print("Loading 30 static control fact IDs...")
        sampled_ids = [int(line.strip()) for line in CONTROL_ID_FILE.read_text().splitlines() if line.strip()]

    # Fetch contents
    placeholders = ",".join("?" for _ in sampled_ids)
    rows = conn.execute(
        f"SELECT fact_id, content, source_doc_id FROM facts WHERE fact_id IN ({placeholders})",
        sampled_ids
    ).fetchall()
    facts = [dict(r) for r in rows]
    conn.close()

    print(f"Loaded {len(facts)} control facts.")

    model_call = _resolve_model_call()
    
    print("\n--- Running Audit 1 ---")
    verdicts1 = audit_facts_batch(model_call, facts)
    
    print("\n--- Running Audit 2 ---")
    verdicts2 = audit_facts_batch(model_call, facts)

    # Compare
    agreements = 0
    mismatches = []
    for f in facts:
        fid = f["fact_id"]
        v1 = verdicts1.get(fid, "MISSING")
        v2 = verdicts2.get(fid, "MISSING")
        if v1 == v2:
            agreements += 1
        else:
            mismatches.append((fid, f["content"], v1, v2))

    consistency = agreements / len(facts) * 100 if facts else 0.0
    print(f"\nConsistency check finished: {agreements}/{len(facts)} matched ({consistency:.1f}%)")
    
    if mismatches:
        print("\nMismatches found:")
        for fid, content, v1, v2 in mismatches:
            print(f"  [{fid}] {content}")
            print(f"    Audit 1: {v1}")
            print(f"    Audit 2: {v2}")

if __name__ == "__main__":
    main()
