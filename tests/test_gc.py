"""Tests for the lazy garbage collector and trust decay."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from holographic.gc import GarbageCollector, recency_factor
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
            ("trust_decay", _days_ago_iso(0.5), _days_ago_iso(0.5), 1, 0),
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
            ("trust_decay", _days_ago_iso(0.5), _days_ago_iso(0.5), 1, 0),
        )
        conn.execute(
            "INSERT INTO facts(content, trust_score, updated_at) VALUES (?, ?, ?)",
            ("test fact", 0.8, _days_ago_iso(180)),
        )
        conn.commit()
        result = gc.maybe_run(force=True)
        assert result["ran"] is True
        assert result["facts_processed"] == 1
        assert result["facts_updated"] == 1

    def test_decay_applied_to_active_facts(self):
        conn = _make_in_memory_store()
        gc = GarbageCollector(conn, interval_days=0, decay_max_days=365, decay_floor=0.1)
        conn.execute(
            "INSERT INTO facts(content, trust_score, updated_at, created_at) VALUES (?, ?, ?, ?)",
            ("old fact", 0.8, _days_ago_iso(180), _days_ago_iso(200)),
        )
        conn.commit()
        result = gc.maybe_run(force=True)
        assert result["facts_processed"] == 1
        assert result["facts_updated"] == 1
        row = conn.execute("SELECT trust_score FROM facts").fetchone()
        # 180 days -> recency ~0.505, 0.8 * 0.505 ~= 0.404
        assert row["trust_score"] == pytest.approx(0.404, abs=0.01)

    def test_uses_updated_at_over_created_at(self):
        conn = _make_in_memory_store()
        gc = GarbageCollector(conn, interval_days=0, decay_max_days=365, decay_floor=0.1)
        # updated_at recent, created_at old -> almost no decay
        conn.execute(
            "INSERT INTO facts(content, trust_score, updated_at, created_at) VALUES (?, ?, ?, ?)",
            ("recently touched", 0.8, _days_ago_iso(1), _days_ago_iso(300)),
        )
        conn.commit()
        gc.maybe_run(force=True)
        row = conn.execute("SELECT trust_score FROM facts").fetchone()
        assert row["trust_score"] == pytest.approx(0.797, abs=0.01)

    def test_merged_facts_are_skipped(self):
        conn = _make_in_memory_store()
        gc = GarbageCollector(conn, interval_days=0)
        conn.execute(
            "INSERT INTO facts(fact_id, content, trust_score, updated_at) VALUES (?, ?, ?, ?)",
            (1, "active", 0.8, _days_ago_iso(180)),
        )
        conn.execute(
            "INSERT INTO facts(fact_id, content, trust_score, updated_at, merged_into) VALUES (?, ?, ?, ?, ?)",
            (2, "merged", 0.8, _days_ago_iso(180), 1),
        )
        conn.commit()
        result = gc.maybe_run(force=True)
        assert result["facts_processed"] == 1
        assert result["facts_updated"] == 1

    def test_no_update_when_change_below_epsilon(self):
        conn = _make_in_memory_store()
        gc = GarbageCollector(conn, interval_days=0, decay_max_days=365, decay_floor=0.1)
        conn.execute(
            "INSERT INTO facts(content, trust_score, updated_at) VALUES (?, ?, ?)",
            ("barely old", 0.8, _days_ago_iso(0.1)),
        )
        conn.commit()
        result = gc.maybe_run(force=True)
        assert result["facts_processed"] == 1
        assert result["facts_updated"] == 0

    def test_gc_log_entry_written(self):
        conn = _make_in_memory_store()
        gc = GarbageCollector(conn, interval_days=0)
        conn.execute(
            "INSERT INTO facts(content, trust_score, updated_at) VALUES (?, ?, ?)",
            ("fact", 0.5, _days_ago_iso(180)),
        )
        conn.commit()
        gc.maybe_run(force=True)
        rows = conn.execute("SELECT * FROM gc_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["gc_type"] == "trust_decay"
        assert rows[0]["finished_at"] is not None
        assert rows[0]["facts_processed"] == 1
        assert rows[0]["facts_updated"] == 1


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
                "UPDATE facts SET updated_at = ? WHERE fact_id = ?",
                (_days_ago_iso(180), fact_id),
            )
            store._conn.commit()

            result = store.run_gc(force=True)
            assert result["ran"] is True
            assert result["facts_processed"] == 1
            assert result["facts_updated"] == 1

            row = store._conn.execute(
                "SELECT trust_score FROM facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()
            assert row["trust_score"] == pytest.approx(0.404, abs=0.01)
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
