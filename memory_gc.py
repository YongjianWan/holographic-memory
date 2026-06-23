"""Lazy maintenance coordination for the holographic memory store.

GC runs inside the hermes process only (no OS cron, no standalone worker).
It is triggered at initialize() and on_session_end(), and uses the gc_log
table to decide whether enough time has passed since the last run.

Retrieval recency is intentionally not persisted or refreshed here. It is
derived from facts.last_accessed_at at query time.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_GC_TYPE_MAINTENANCE = "maintenance"
def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_ts(value: str | None) -> float:
    """Parse an ISO-8601 timestamp string to seconds since epoch.

    Returns 0.0 for missing/invalid values so that a missing log entry
    behaves like "never run".
    """
    if not value:
        return 0.0
    try:
        # SQLite may store '2026-06-22 13:52:05' (no timezone) or an
        # ISO string with '+00:00' / 'Z'. fromisoformat handles both.
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def recency_factor(days: float, max_days: float = 365.0, floor: float = 0.1) -> float:
    """Return a multiplicative recency factor in [floor, 1.0].

    A fact that is ``max_days`` old receives the floor; a brand-new fact
    receives 1.0. The factor is applied to trust_score, so recency is a
    multiplicative boost/cut centered at 1.0 (per project RQ red-line).
    """
    if max_days <= 0:
        return 1.0
    return max(floor, min(1.0, 1.0 - days / max_days))


class GarbageCollector:
    """Non-blocking, cross-process maintenance coordinator."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        interval_days: float = 7.0,
        decay_max_days: float = 365.0,
        decay_floor: float = 0.1,
    ) -> None:
        self.conn = conn
        self.interval_days = max(0.0, interval_days)
        self.decay_max_days = max(1.0, decay_max_days)
        self.decay_floor = max(0.0, min(1.0, decay_floor))

    def maybe_run(self, force: bool = False) -> dict:
        """Run due maintenance if this process can claim the writer lock.

        Returns a status dict with at least {"ran": bool, ...}. When
        ``interval_days`` is 0 and ``force`` is False, GC is disabled.
        """
        if self.interval_days <= 0 and not force:
            return {"ran": False, "reason": "disabled"}

        # GC is opportunistic maintenance. Across multiple agent processes,
        # only the first connection that acquires the SQLite writer lock runs;
        # the others skip immediately and retry at a later trigger.
        if self.conn.in_transaction:
            self.conn.commit()
        previous_timeout = int(
            self.conn.execute("PRAGMA busy_timeout").fetchone()[0]
        )
        self.conn.execute("PRAGMA busy_timeout = 0")
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                return {"ran": False, "reason": "busy"}
            raise
        finally:
            self.conn.execute(f"PRAGMA busy_timeout = {previous_timeout}")

        last_ts = self._last_finished_ts()
        now = _now_ts()
        elapsed_days = (now - last_ts) / 86400.0
        if elapsed_days < self.interval_days and not force:
            self.conn.rollback()
            return {
                "ran": False,
                "reason": "too_soon",
                "elapsed_days": elapsed_days,
                "interval_days": self.interval_days,
            }

        return self._run_maintenance()

    def _last_finished_ts(self) -> float:
        row = self.conn.execute(
            "SELECT MAX(finished_at) FROM gc_log WHERE gc_type = ? AND finished_at IS NOT NULL",
            (_GC_TYPE_MAINTENANCE,),
        ).fetchone()
        return _parse_iso_ts(row[0] if row else None)

    def _run_maintenance(self) -> dict:
        started = _utc_now_iso()
        cur = self.conn.execute(
            "INSERT INTO gc_log(gc_type, started_at) VALUES (?, ?)",
            (_GC_TYPE_MAINTENANCE, started),
        )
        gc_id = cur.lastrowid

        try:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM facts WHERE merged_into IS NULL"
            ).fetchone()
            facts_processed = int(row[0]) if row else 0

            finished = _utc_now_iso()
            self.conn.execute(
                "UPDATE gc_log SET finished_at = ?, facts_processed = ?, facts_updated = ? WHERE gc_id = ?",
                (finished, facts_processed, 0, gc_id),
            )
            self.conn.commit()
            logger.info(
                "Maintenance checkpoint finished: active_facts=%d",
                facts_processed,
            )
            return {
                "ran": True,
                "facts_processed": facts_processed,
                "facts_updated": 0,
            }
        except Exception:
            self.conn.rollback()
            logger.exception("Lazy maintenance failed")
            raise
