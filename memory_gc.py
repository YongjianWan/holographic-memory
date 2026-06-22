"""Garbage collection and trust decay for the holographic memory store.

GC runs inside the hermes process only (no OS cron, no standalone worker).
It is triggered at initialize() and on_session_end(), and uses the gc_log
table to decide whether enough time has passed since the last run.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_GC_TYPE_DECAY = "trust_decay"
_TRUST_MIN = 0.0
_TRUST_MAX = 1.0


def _clamp_trust(value: float) -> float:
    return max(_TRUST_MIN, min(_TRUST_MAX, value))


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
    """Lazy, process-internal garbage collector for the memory store."""

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
        """Run trust-decay GC if enough time has passed since the last run.

        Returns a status dict with at least {"ran": bool, ...}. When
        ``interval_days`` is 0 and ``force`` is False, GC is disabled.
        """
        if self.interval_days <= 0 and not force:
            return {"ran": False, "reason": "disabled"}

        last_ts = self._last_finished_ts()
        now = _now_ts()
        elapsed_days = (now - last_ts) / 86400.0
        if elapsed_days < self.interval_days and not force:
            return {
                "ran": False,
                "reason": "too_soon",
                "elapsed_days": elapsed_days,
                "interval_days": self.interval_days,
            }

        return self._run_decay(now)

    def _last_finished_ts(self) -> float:
        row = self.conn.execute(
            "SELECT MAX(finished_at) FROM gc_log WHERE gc_type = ? AND finished_at IS NOT NULL",
            (_GC_TYPE_DECAY,),
        ).fetchone()
        return _parse_iso_ts(row[0] if row else None)

    def _run_decay(self, now: float) -> dict:
        started = _utc_now_iso()
        cur = self.conn.execute(
            "INSERT INTO gc_log(gc_type, started_at) VALUES (?, ?)",
            (_GC_TYPE_DECAY, started),
        )
        gc_id = cur.lastrowid

        try:
            rows = self.conn.execute(
                "SELECT fact_id, trust_score, updated_at, created_at FROM facts WHERE merged_into IS NULL"
            ).fetchall()

            updated_count = 0
            for fact_id, trust_score, updated_at, created_at in rows:
                ref_time = updated_at or created_at or started
                ref_ts = _parse_iso_ts(ref_time)
                if ref_ts <= 0:
                    ref_ts = now
                days = (now - ref_ts) / 86400.0
                factor = recency_factor(days, self.decay_max_days, self.decay_floor)
                new_trust = _clamp_trust(trust_score * factor)

                if abs(new_trust - trust_score) >= 0.001:
                    self.conn.execute(
                        "UPDATE facts SET trust_score = ?, updated_at = ? WHERE fact_id = ?",
                        (new_trust, _utc_now_iso(), fact_id),
                    )
                    updated_count += 1

            finished = _utc_now_iso()
            self.conn.execute(
                "UPDATE gc_log SET finished_at = ?, facts_processed = ?, facts_updated = ? WHERE gc_id = ?",
                (finished, len(rows), updated_count, gc_id),
            )
            self.conn.commit()
            logger.info(
                "Trust-decay GC finished: processed=%d updated=%d",
                len(rows),
                updated_count,
            )
            return {
                "ran": True,
                "facts_processed": len(rows),
                "facts_updated": updated_count,
            }
        except Exception:
            self.conn.rollback()
            logger.exception("Trust-decay GC failed")
            raise
