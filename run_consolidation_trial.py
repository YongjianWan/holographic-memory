"""Consolidation Trial Runner.

Loads the real holographic_corpus_audit.db database, extracts consolidation
candidates, calls the model to consolidate them, and prints the result.
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT.parent))

# Hermes stubs
import dotenv
dotenv.load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

sys.path.insert(0, str(PROJECT_ROOT / "tests"))
import conftest

from holographic import store

def _resolve_model_call():
    import os
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

    oa_key = os.environ.get("OPENAI_API_KEY")
    if oa_key:
        try:
            from openai import OpenAI
            model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            client = OpenAI(api_key=oa_key)
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

DB_PATH = Path(tempfile.gettempdir()) / "holographic_corpus_audit.db"

def main() -> None:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    if not DB_PATH.exists():
        print(f"Database {DB_PATH} not found. Please run corpus_audit.py first.")
        sys.exit(1)

    model_call = _resolve_model_call()
    if not model_call:
        print("Error: Neither DEEPSEEK_API_KEY nor OPENAI_API_KEY is set in the environment.")
        sys.exit(1)

    # Load store
    db = store.MemoryStore(db_path=str(DB_PATH), hrr_dim=1024)

    print("Finding consolidation candidates...")
    clusters = db._find_consolidation_candidates(category="project", generic_threshold=15)
    print(f"Found {len(clusters)} candidate clusters for consolidation.\n")

    if not clusters:
        print("No candidates found. Exiting.")
        return

    # Print clusters
    for i, cluster in enumerate(clusters, 1):
        print(f"=== Cluster #{i} ({len(cluster)} facts) ===")
        for f in cluster:
            print(f"  [{f['fact_id']}] {f['content']}")
        print()

    print("Running LLM consolidation trial...")
    # Run consolidate_facts
    report = db.consolidate_facts(
        model_call=model_call,
        category="project",
        generic_threshold=15
    )

    print("\nConsolidation Report:")
    print(f"- Clusters processed: {report['clusters_processed']}")
    print(f"- Facts processed: {report['facts_processed']}")
    print(f"- Facts merged: {report['facts_merged']}")
    print(f"- Facts created: {report['facts_created']}")
    print(f"- Status: {report['status']}")

    # Query the newly created and soft-deleted facts
    if report["facts_created"] > 0 or report["facts_merged"] > 0:
        print("\n=== Consolidated Outcomes ===")
        rows = db._conn.execute(
            """
            SELECT fact_id, content, merged_into
            FROM facts
            WHERE merged_into IS NOT NULL OR fact_id IN (
                SELECT DISTINCT merged_into FROM facts WHERE merged_into IS NOT NULL
            )
            ORDER BY merged_into DESC, fact_id ASC
            """
        ).fetchall()

        # Group by merged_into target
        outcomes: dict[int, list[dict]] = {}
        for r in rows:
            target = r["merged_into"]
            if target is None:
                # This is the new consolidated fact itself
                target_id = r["fact_id"]
                outcomes.setdefault(target_id, []).append({"fact_id": target_id, "content": r["content"], "role": "target"})
            else:
                outcomes.setdefault(target, []).append({"fact_id": r["fact_id"], "content": r["content"], "role": "source"})

        for target_id, members in outcomes.items():
            target_fact = next((m for m in members if m["role"] == "target"), None)
            source_facts = [m for m in members if m["role"] == "source"]
            
            # If the target is not in outcomes (e.g. if it didn't return in the query because of some reason), fetch it
            if not target_fact:
                t_row = db._conn.execute("SELECT content FROM facts WHERE fact_id = ?", (target_id,)).fetchone()
                target_content = t_row["content"] if t_row else "<Unknown>"
                target_fact = {"fact_id": target_id, "content": target_content, "role": "target"}

            print(f"\nTarget Consolidated Fact [{target_fact['fact_id']}]:\n  -> {target_fact['content']}")
            print("Source Facts merged:")
            for src in source_facts:
                print(f"  - [{src['fact_id']}] {src['content']}")

if __name__ == "__main__":
    main()
