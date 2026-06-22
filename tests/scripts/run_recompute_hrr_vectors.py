"""Recompute entity links and HRR vectors for all active facts.

This is a one-off maintenance script for when entity extraction rules change
and existing fact_entities / hrr_vector values may no longer match the current
content. It only touches derived data (fact_entities, entities, hrr_vector,
and memory_banks), never facts content or source entities.

Usage:
    python tests/scripts/run_recompute_hrr_vectors.py --db "C:/Users/.../memory_store.db" --yes
"""

from __future__ import annotations

import argparse
import sys
import types
from pathlib import Path

# When running from the project root, Python puts the root directory on
# sys.path first. That causes `import holographic` to resolve to the file
# `holographic.py` instead of the package directory. Insert the parent
# directory first and remove the misleading cwd entry.
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
    hermes_constants.get_hermes_home = lambda: Path(".")
    hermes_constants.display_hermes_home = lambda: "."
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

from holographic import entities  # noqa: E402
from holographic.store import MemoryStore  # noqa: E402


def recompute_entities_and_hrr(db_path: Path, yes: bool = False) -> dict:
    db_path = db_path.expanduser().absolute()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    print(f"Target database: {db_path}")
    if not yes:
        answer = input(
            "This will re-extract entities and recompute HRR vectors for all active facts. Continue? [y/N] "
        )
        if answer.lower() not in ("y", "yes"):
            print("Aborted.")
            return {"aborted": True}

    store = MemoryStore(db_path=str(db_path))
    try:
        fact_rows = store._conn.execute(
            "SELECT fact_id, content, category FROM facts WHERE merged_into IS NULL"
        ).fetchall()

        categories: set[str] = set()
        recomputed = 0
        skipped_no_numpy = 0

        if not store._hrr_available:
            print("WARNING: numpy unavailable, HRR recompute is a no-op.")
            skipped_no_numpy = len(fact_rows)

        for row in fact_rows:
            fact_id = row["fact_id"]
            content = row["content"]
            category = row["category"]

            # Remove stale entity links for this fact.
            store._conn.execute("DELETE FROM fact_entities WHERE fact_id = ?", (fact_id,))

            # Re-extract and link current entities.
            entity_names = entities.extract_entities(content)
            for name in entity_names:
                entity_id = entities.resolve_entity(store._conn, name)
                entities.link_fact_entity(store._conn, fact_id, entity_id)

            # Recompute HRR vector from current content + current entity links.
            store._compute_hrr_vector(fact_id, content)
            categories.add(category)
            recomputed += 1

        # Rebuild category banks from fresh vectors.
        for category in categories:
            store._rebuild_bank(category)

        # Drop orphan entities that are no longer linked to any fact.
        orphan_rows = store._conn.execute(
            """
            SELECT e.entity_id
            FROM entities e
            LEFT JOIN fact_entities fe ON fe.entity_id = e.entity_id
            WHERE fe.fact_id IS NULL
            """
        ).fetchall()
        orphans_removed = 0
        for orphan in orphan_rows:
            store._conn.execute("DELETE FROM entities WHERE entity_id = ?", (orphan["entity_id"],))
            orphans_removed += 1
        store._conn.commit()

        # Verify consistency after recompute.
        orphaned = store._conn.execute("""
            SELECT COUNT(*) AS c
            FROM facts f
            WHERE f.merged_into IS NULL
              AND f.hrr_vector IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM fact_entities fe WHERE fe.fact_id = f.fact_id)
        """).fetchone()["c"]

        entity_count = store._conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        link_count = store._conn.execute("SELECT COUNT(*) FROM fact_entities").fetchone()[0]

        return {
            "recomputed": recomputed,
            "skipped_no_numpy": skipped_no_numpy,
            "categories_rebuilt": sorted(categories),
            "orphans_removed": orphans_removed,
            "entity_count": entity_count,
            "link_count": link_count,
            "facts_with_hrr_but_no_entities": orphaned,
        }
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-extract entities and recompute HRR vectors.")
    parser.add_argument("--db", required=True, help="Path to memory_store.db")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    result = recompute_entities_and_hrr(Path(args.db), yes=args.yes)
    print(result)
    return 0 if not result.get("aborted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
