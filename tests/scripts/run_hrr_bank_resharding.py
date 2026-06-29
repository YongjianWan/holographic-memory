"""Apply the sharded HRR memory-bank scheme to the live DB.

`store._rebuild_bank` now writes `cat:{category}|doc:{doc}|shard:{nn}` banks
instead of one flat `cat:{category}` bundle (see
reports/hrr_bank_partition_audit.md). This script re-runs that rebuild for
every category in the live DB so the on-disk banks reflect the new code, then
reports before/after bank counts and max SNR. It never touches `facts` rows.

Usage:
    python tests/scripts/run_hrr_bank_resharding.py --dry-run
    python tests/scripts/run_hrr_bank_resharding.py --yes
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any

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

from holographic.store import MemoryStore  # noqa: E402


def _default_db_path() -> Path:
    return Path("C:/Users/sdses/AppData/Local/hermes/memory_store.db")


def _backup_db(db_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = PROJECT_ROOT / "reports" / "live_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"memory_store_before_hrr_resharding_{timestamp}.db"

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


def _snr(dim: int, fact_count: int) -> float:
    if fact_count <= 0:
        return float("inf")
    return round(math.sqrt(dim / fact_count), 3)


def _bank_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT bank_name, dim, fact_count FROM memory_banks").fetchall()
    banks = [
        {
            "bank_name": row[0],
            "dim": row[1],
            "fact_count": row[2],
            "snr": _snr(row[1], row[2]),
        }
        for row in rows
    ]
    banks.sort(key=lambda b: (-b["fact_count"], b["bank_name"]))
    capacities = [b for b in banks if b["dim"]]
    max_bank = max(banks, key=lambda b: b["fact_count"]) if banks else None
    return {
        "bank_count": len(banks),
        "max_fact_count": max_bank["fact_count"] if max_bank else 0,
        "max_snr": max_bank["snr"] if max_bank else None,
        "banks_over_capacity": sum(
            1 for b in capacities if b["fact_count"] > (b["dim"] // 4)
        ),
        "top_banks": banks[:20],
    }


def _distinct_categories(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT category FROM facts WHERE merged_into IS NULL"
    ).fetchall()
    return sorted(row[0] for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=_default_db_path())
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    db_path = args.db.expanduser().absolute()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    before_conn = sqlite3.connect(str(db_path))
    try:
        before = _bank_summary(before_conn)
        categories = _distinct_categories(before_conn)
    finally:
        before_conn.close()

    backup_path: Path | None = None
    after = before
    if args.yes:
        backup_path = _backup_db(db_path)
        store = MemoryStore(db_path=str(db_path))
        try:
            for category in categories:
                store._rebuild_bank(category)
        finally:
            store.close()

        after_conn = sqlite3.connect(str(db_path))
        try:
            after = _bank_summary(after_conn)
        finally:
            after_conn.close()

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": not args.yes,
        "db": str(db_path),
        "backup": str(backup_path) if backup_path else None,
        "categories_rebuilt": categories,
        "before": before,
        "after": after,
    }

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "hrr_bank_resharding.json"
    md_path = output_dir / "hrr_bank_resharding.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# HRR Bank Resharding",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- dry_run: {report['dry_run']}",
        f"- db: `{report['db']}`",
        f"- backup: `{report.get('backup') or ''}`",
        f"- categories_rebuilt: {', '.join(report['categories_rebuilt'])}",
        "",
        "| stage | bank_count | max_fact_count | max_snr | banks_over_capacity |",
        "|---|---:|---:|---:|---:|",
        f"| before | {before['bank_count']} | {before['max_fact_count']} | {before['max_snr']} | {before['banks_over_capacity']} |",
        f"| after | {after['bank_count']} | {after['max_fact_count']} | {after['max_snr']} | {after['banks_over_capacity']} |",
        "",
        "## Top banks after",
        "",
        "| bank_name | fact_count | snr |",
        "|---|---:|---:|",
    ]
    for bank in after["top_banks"]:
        lines.append(f"| {bank['bank_name']} | {bank['fact_count']} | {bank['snr']} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"dry_run={not args.yes}")
    print(f"backup={backup_path}")
    print(f"before_max_fact_count={before['max_fact_count']} before_max_snr={before['max_snr']}")
    print(f"after_max_fact_count={after['max_fact_count']} after_max_snr={after['max_snr']}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")


if __name__ == "__main__":
    main()
