"""Tests for the lazy garbage collector and trust decay."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from holographic.memory_gc import GarbageCollector, recency_factor
from holographic.store import MemoryStore
from holographic.store_migrations import _SCHEMA


def _days_ago_iso(days: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat()


def _make_in_memory_store() -> sqlite3.Connection:
    """Return a connection with the latest schema for direct GC tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


class TestRecencyFactor:
    def test_new_fact_has_full_trust(self):
        assert recency_factor(0) == pytest.approx(1.0)

    def test_half_life_at_max_days(self):
        assert recency_factor(182.5) == pytest.approx(0.5)

    def test_reaches_floor(self):
        assert recency_factor(365) == pytest.approx(0.1)

    def test_floor_clip_for_very_old(self):
        assert recency_factor(500) == pytest.approx(0.1)

    def test_custom_max_days_and_floor(self):
        # 50 days into a 100-day half-life -> 0.5
        assert recency_factor(50, max_days=100, floor=0.2) == pytest.approx(0.5)
        # At max -> floor
        assert recency_factor(100, max_days=100, floor=0.2) == pytest.approx(0.2)


class TestGarbageCollectorUnit:
    def test_two_connections_busy_skip_writes_no_log_then_retries(
        self, tmp_path: Path
    ):
        """A second SQLite connection must not acknowledge work it did not run.

        This deliberately uses two independent connections to the same file:
        conn1 holds BEGIN IMMEDIATE while conn2 attempts the GC writer claim.
        """
        db_path = tmp_path / "shared.db"
        conn1 = sqlite3.connect(db_path, timeout=10)
        conn1.row_factory = sqlite3.Row
        conn1.executescript(_SCHEMA)
        conn2 = sqlite3.connect(db_path, timeout=10)
        conn2.row_factory = sqlite3.Row

        conn1.execute("BEGIN IMMEDIATE")
        try:
            gc = GarbageCollector(conn2, interval_days=0)
            started = datetime.now(timezone.utc)
            result = gc.maybe_run(force=True)
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            log_count = conn2.execute("SELECT COUNT(*) FROM gc_log").fetchone()[0]
        finally:
            conn1.rollback()

        assert result == {"ran": False, "reason": "busy"}
        assert elapsed < 1.0
        assert log_count == 0

        retry = gc.maybe_run(force=True)
        finished_count = conn2.execute(
            "SELECT COUNT(*) FROM gc_log WHERE finished_at IS NOT NULL"
        ).fetchone()[0]
        conn1.close()
        conn2.close()

        assert retry["ran"] is True
        assert finished_count == 1

    def test_disabled_when_interval_zero(self):
        conn = _make_in_memory_store()
        gc = GarbageCollector(conn, interval_days=0)
        assert gc.maybe_run() == {"ran": False, "reason": "disabled"}

    def test_too_soon_after_run(self):
        conn = _make_in_memory_store()
        gc = GarbageCollector(conn, interval_days=7)
        # Insert a recent finished log entry.
        conn.execute(
            "INSERT INTO gc_log(gc_type, started_at, finished_at, facts_processed, facts_updated) VALUES (?, ?, ?, ?, ?)",
            ("maintenance", _days_ago_iso(0.5), _days_ago_iso(0.5), 1, 0),
        )
        conn.commit()
        result = gc.maybe_run()
        assert result["ran"] is False
        assert result["reason"] == "too_soon"

    def test_force_runs_even_when_too_soon(self):
        conn = _make_in_memory_store()
        gc = GarbageCollector(conn, interval_days=7)
        conn.execute(
            "INSERT INTO gc_log(gc_type, started_at, finished_at, facts_processed, facts_updated) VALUES (?, ?, ?, ?, ?)",
            ("maintenance", _days_ago_iso(0.5), _days_ago_iso(0.5), 1, 0),
        )
        conn.execute(
            "INSERT INTO facts(content, trust_score, last_accessed_at) VALUES (?, ?, ?)",
            ("test fact", 0.8, _days_ago_iso(180)),
        )
        conn.commit()
        result = gc.maybe_run(force=True)
        assert result["ran"] is True
        assert result["facts_processed"] == 1
        assert result["facts_updated"] == 0

    def test_merged_facts_are_skipped(self):
        conn = _make_in_memory_store()
        gc = GarbageCollector(conn, interval_days=0)
        conn.execute(
            "INSERT INTO facts(fact_id, content, trust_score, last_accessed_at) VALUES (?, ?, ?, ?)",
            (1, "active", 0.8, _days_ago_iso(180)),
        )
        conn.execute(
            "INSERT INTO facts(fact_id, content, trust_score, last_accessed_at, merged_into) VALUES (?, ?, ?, ?, ?)",
            (2, "merged", 0.8, _days_ago_iso(180), 1),
        )
        conn.commit()
        result = gc.maybe_run(force=True)
        assert result["facts_processed"] == 1
        assert result["facts_updated"] == 0

    def test_gc_log_entry_written(self):
        conn = _make_in_memory_store()
        gc = GarbageCollector(conn, interval_days=0)
        conn.execute(
            "INSERT INTO facts(content, trust_score, last_accessed_at) VALUES (?, ?, ?)",
            ("fact", 0.5, _days_ago_iso(180)),
        )
        conn.commit()
        gc.maybe_run(force=True)
        rows = conn.execute("SELECT * FROM gc_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["gc_type"] == "maintenance"
        assert rows[0]["finished_at"] is not None
        assert rows[0]["facts_processed"] == 1
        assert rows[0]["facts_updated"] == 0


class TestMemoryStoreGcIntegration:
    def test_run_gc_through_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.db"
            store = MemoryStore(
                db_path=db,
                default_trust=0.8,
                gc_interval_days=0,
                gc_decay_max_days=365,
                gc_decay_floor=0.1,
            )
            fact_id = store.add_fact("old fact", category="general")
            # Manually age the fact.
            store._conn.execute(
                "UPDATE facts SET last_accessed_at = ? WHERE fact_id = ?",
                (_days_ago_iso(180), fact_id),
            )
            store._conn.commit()

            result = store.run_gc(force=True)
            assert result["ran"] is True
            assert result["facts_processed"] == 1
            assert result["facts_updated"] == 0
            store.close()

    def test_gc_disabled_by_interval_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.db"
            store = MemoryStore(
                db_path=db,
                gc_interval_days=0,
            )
            result = store.run_gc()
            assert result == {"ran": False, "reason": "disabled"}
            store.close()
