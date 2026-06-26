import os
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

def audit_facts_batch(model_call, facts: list[dict]) -> list[dict]:
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
    results = []
    for line in response.strip().splitlines():
        line = line.strip()
        if not line or not line.startswith("["):
            continue
        try:
            bracket_end = line.index("]")
            num = int(line[1:bracket_end])
            rest = line[bracket_end+1:].strip()
            if rest.startswith("PASS"):
                verdict = "PASS"
                reason = rest[4:].strip().lstrip("-").strip()
            elif rest.startswith("FAIL"):
                verdict = "FAIL"
                reason = rest[4:].strip().lstrip("-").strip()
            else:
                verdict = "UNKNOWN"
                reason = rest
            idx = num - 1
            if 0 <= idx < len(facts):
                results.append({
                    "fact_id": facts[idx]["fact_id"],
                    "content": facts[idx]["content"],
                    "verdict": verdict,
                    "reason": reason,
                })
        except (ValueError, IndexError):
            continue
    return results

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

    # Fetch all active facts for doc 8
    rows = conn.execute(
        "SELECT fact_id, content FROM facts WHERE source_doc_id = 8 AND merged_into IS NULL"
    ).fetchall()
    facts = [dict(r) for r in rows]
    conn.close()

    total_facts = len(facts)
    print(f"Loaded {total_facts} active facts for Doc 8.")

    if total_facts == 0:
        return

    model_call = _resolve_model_call()
    
    # Process in batches of 50
    batch_size = 50
    results = []
    for i in range(0, total_facts, batch_size):
        batch = facts[i:i+batch_size]
        print(f"Auditing facts {i+1} to {min(i+batch_size, total_facts)}...")
        batch_results = audit_facts_batch(model_call, batch)
        results.extend(batch_results)

    # Compute stats
    pass_count = sum(1 for r in results if r["verdict"] == "PASS")
    fail_count = sum(1 for r in results if r["verdict"] == "FAIL")
    unknown_count = sum(1 for r in results if r["verdict"] == "UNKNOWN")
    total = len(results)
    pass_rate = pass_count / total * 100 if total > 0 else 0

    report_lines = [
        "=" * 60,
        "DOC 8 100% QUALITY AUDIT REPORT",
        "=" * 60,
        f"Total active facts in DB for Doc 8: {total_facts}",
        f"Audited: {total}",
        f"",
        f"PASS: {pass_count} ({pass_rate:.1f}%)",
        f"FAIL: {fail_count} ({fail_count/total*100 if total else 0:.1f}%)",
        f"UNKNOWN: {unknown_count}",
        f"",
        f"VERDICT: {'PASS' if pass_rate >= 50 else 'FAIL'} (threshold: 50%)",
        f"",
        "-" * 60,
        "FAIL DETAILED RESULTS",
        "-" * 60,
    ]

    # Display fail facts
    fails = [r for r in results if r["verdict"] == "FAIL"]
    for r in fails:
        report_lines.append(f"\n[{r['fact_id']}] FAIL: {r['reason']}")
        report_lines.append(f"  Content: {r['content']}")

    report = "\n".join(report_lines)
    out_path = PROJECT_ROOT / "tests" / "scripts" / "_doc8_audit_report.txt"
    with open(str(out_path), "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\nDoc 8 report saved to: {out_path}")

if __name__ == "__main__":
    main()
