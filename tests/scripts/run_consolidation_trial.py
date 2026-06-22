"""P1-2 consolidation trial on the live memory_store.db.

⚠️  WARNING: This script operates on the REAL memory_store.db used by hermes.
    The "--run" and "--facts" modes perform soft-delete merges. Results are
    recoverable via merged_into=NULL rollback, but you should back up your .db
    before running them.

Phase 1: discover candidate clusters (read-only).
Phase 2: run consolidation on a selected cluster index and show results.
"""
import os
import sys
import pathlib
import argparse

HERMES_AGENT = r"C:\Users\sdses\AppData\Local\hermes\hermes-agent"
PROJECT_ROOT = str(pathlib.Path(__file__).absolute().parent.parent.parent)
sys.path.insert(0, HERMES_AGENT)
sys.path.insert(0, PROJECT_ROOT)

from store import MemoryStore


def resolve_db() -> pathlib.Path:
    hermes_home = os.environ.get("HERMES_HOME") or str(
        pathlib.Path.home() / "AppData" / "Local" / "hermes"
    )
    return pathlib.Path(hermes_home) / "memory_store.db"


def discover(db_path: pathlib.Path, category: str | None, max_cluster_size: int = 6):
    store = MemoryStore(db_path=str(db_path))
    try:
        clusters = store._find_consolidation_candidates(
            category=category,
            max_cluster_size=max_cluster_size,
        )
        if not clusters:
            print("No consolidation candidates found.")
            return

        print(f"Found {len(clusters)} candidate cluster(s):\n")
        for idx, cluster in enumerate(clusters, start=1):
            print(f"--- Cluster {idx} ({len(cluster)} facts) ---")
            for f in cluster:
                content = f["content"].replace("\n", " ")
                print(f"  id={f['fact_id']:>3} | {content}")
            print()
    finally:
        store.close()


def run_consolidation(
    db_path: pathlib.Path,
    cluster_index: int | None,
    fact_ids: list[int] | None,
    category: str | None,
    max_cluster_size: int = 6,
):
    from __init__ import _resolve_model_call

    model_call = _resolve_model_call()
    if not model_call:
        print("ERROR: DEEPSEEK_API_KEY or OPENAI_API_KEY not found in environment.")
        sys.exit(1)

    store = MemoryStore(db_path=str(db_path))
    try:
        if fact_ids:
            rows = store._conn.execute(
                "SELECT fact_id, content, category, tags, trust_score FROM facts "
                f"WHERE fact_id IN ({','.join('?' * len(fact_ids))})",
                fact_ids,
            ).fetchall()
            cluster = [dict(r) for r in rows]
            print(f"Running consolidation on explicit cluster ({len(cluster)} facts):\n")
        else:
            clusters = store._find_consolidation_candidates(
                category=category,
                max_cluster_size=max_cluster_size,
            )
            if not clusters:
                print("No consolidation candidates found.")
                return
            if cluster_index is None or cluster_index < 1 or cluster_index > len(clusters):
                print(f"ERROR: cluster index must be between 1 and {len(clusters)}")
                sys.exit(1)
            cluster = clusters[cluster_index - 1]
            print(f"Running consolidation on cluster {cluster_index} ({len(cluster)} facts):\n")

        for f in cluster:
            content = f["content"].replace("\n", " ")
            print(f"  id={f['fact_id']:>3} | {content}")
        print()

        category = cluster[0]["category"] if cluster else category
        report = store.consolidate_facts(
            model_call=model_call,
            category=category,
            max_cluster_size=max_cluster_size,
            clusters=[cluster] if cluster else [],
        )
        print("Report:", report)
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description="P1-2 consolidation trial on live DB")
    parser.add_argument(
        "--run",
        type=int,
        metavar="N",
        help="Run consolidation on cluster N (1-indexed) instead of just listing.",
    )
    parser.add_argument(
        "--facts",
        type=lambda s: [int(x) for x in s.split(",")],
        help="Comma-separated fact IDs to form an explicit cluster (e.g. 24,25,26).",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Filter candidates by category.",
    )
    parser.add_argument(
        "--max-cluster-size",
        type=int,
        default=6,
        help="Max facts per cluster passed to LLM (default 6).",
    )
    args = parser.parse_args()

    db_path = resolve_db()
    if not db_path.exists():
        print(f"ERROR: database not found at {db_path}")
        sys.exit(1)

    print(f"Using DB: {db_path}  ({db_path.stat().st_size // 1024} KB)\n")

    if args.run is None and args.facts is None:
        discover(db_path, args.category, args.max_cluster_size)
    else:
        run_consolidation(
            db_path,
            args.run,
            args.facts,
            args.category,
            args.max_cluster_size,
        )


if __name__ == "__main__":
    main()
