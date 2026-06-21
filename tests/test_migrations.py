"""Tests for the schema migration framework."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from holographic.store import MemoryStore, _migration_v2_documents, _migration_v3_document_hash


class TestMigrations:
    def test_fresh_database_gets_schema_version_3(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            row = store._conn.execute(
                "SELECT version FROM schema_version"
            ).fetchone()
            assert row is not None
            # _SCHEMA is the latest structure, so a fresh DB is recognised as
            # already at v6 and no migrations (and no backup) are needed.
            assert int(row["version"]) == 6

            tables = {
                r["name"]
                for r in store._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "documents" in tables

            fact_columns = {
                r[1]
                for r in store._conn.execute("PRAGMA table_info(facts)").fetchall()
            }
            assert "source_doc_id" in fact_columns

            doc_columns = {
                r[1]
                for r in store._conn.execute("PRAGMA table_info(documents)").fetchall()
            }
            assert "text_hash" in doc_columns
        finally:
            store.close()
            # No backup should have been created for a fresh empty database.
            assert not Path(f"{db_path}.bak.v6").exists()
            Path(db_path).unlink(missing_ok=True)

    def test_legacy_database_without_schema_version_is_baselined_to_v0(
        self,
    ) -> None:
        """Old DB with facts but no hrr_vector and no schema_version -> baseline v0."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        # Simulate pre-migration database (full legacy schema without hrr_vector
        # and without schema_version).
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE facts (
                fact_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                content         TEXT NOT NULL UNIQUE,
                category        TEXT DEFAULT 'general',
                tags            TEXT DEFAULT '',
                trust_score     REAL DEFAULT 0.5,
                retrieval_count INTEGER DEFAULT 0,
                helpful_count   INTEGER DEFAULT 0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE entities (
                entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            );
            """
        )
        conn.close()

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            row = store._conn.execute(
                "SELECT version FROM schema_version"
            ).fetchone()
            # Should end at v6 (migrations applied after baseline v0).
            assert int(row["version"]) == 6

            columns = {
                r[1]
                for r in store._conn.execute("PRAGMA table_info(facts)").fetchall()
            }
            assert "hrr_vector" in columns
            assert "source_doc_id" in columns

            doc_columns = {
                r[1]
                for r in store._conn.execute("PRAGMA table_info(documents)").fetchall()
            }
            assert "text_hash" in doc_columns
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_legacy_database_with_hrr_vector_is_baselined_to_v1(self) -> None:
        """Old DB with hrr_vector but no schema_version -> baseline v1."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE facts (
                fact_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                content         TEXT NOT NULL UNIQUE,
                category        TEXT DEFAULT 'general',
                tags            TEXT DEFAULT '',
                trust_score     REAL DEFAULT 0.5,
                retrieval_count INTEGER DEFAULT 0,
                helpful_count   INTEGER DEFAULT 0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hrr_vector      BLOB
            );
            CREATE TABLE entities (
                entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            );
            """
        )
        conn.close()

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            row = store._conn.execute(
                "SELECT version FROM schema_version"
            ).fetchone()
            assert int(row["version"]) == 6

            columns = {
                r[1]
                for r in store._conn.execute("PRAGMA table_info(facts)").fetchall()
            }
            assert "source_doc_id" in columns

            doc_columns = {
                r[1]
                for r in store._conn.execute("PRAGMA table_info(documents)").fetchall()
            }
            assert "text_hash" in doc_columns
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_migration_v2_is_idempotent(self) -> None:
        """Applying v2 to an already-migrated database is a no-op."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            # v2 has already run via _init_db.
            # Running it again directly should not raise.
            _migration_v2_documents(store._conn)

            tables = {
                r["name"]
                for r in store._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "documents" in tables
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_migration_v3_is_idempotent(self) -> None:
        """Applying v3 to an already-migrated database is a no-op."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            _migration_v3_document_hash(store._conn)

            doc_columns = {
                r[1]
                for r in store._conn.execute("PRAGMA table_info(documents)").fetchall()
            }
            assert "text_hash" in doc_columns
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_partial_v2_state_is_detected_as_lower_version(self) -> None:
        """Baseline detection uses AND: documents table without text_hash is not v3."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE facts (
                fact_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                content         TEXT NOT NULL UNIQUE,
                category        TEXT DEFAULT 'general',
                tags            TEXT DEFAULT '',
                trust_score     REAL DEFAULT 0.5,
                retrieval_count INTEGER DEFAULT 0,
                helpful_count   INTEGER DEFAULT 0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hrr_vector      BLOB
            );
            CREATE TABLE documents (
                doc_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text    TEXT NOT NULL,
                source      TEXT DEFAULT '',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.close()

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            row = store._conn.execute(
                "SELECT version FROM schema_version"
            ).fetchone()
            assert int(row["version"]) == 6

            columns = {
                r[1]
                for r in store._conn.execute("PRAGMA table_info(facts)").fetchall()
            }
            assert "source_doc_id" in columns

            doc_columns = {
                r[1]
                for r in store._conn.execute("PRAGMA table_info(documents)").fetchall()
            }
            assert "text_hash" in doc_columns
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_backup_created_before_migration(self) -> None:
        """A legacy DB with data triggers a backup before schema changes."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE facts (
                fact_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                content         TEXT NOT NULL UNIQUE,
                category        TEXT DEFAULT 'general',
                tags            TEXT DEFAULT '',
                trust_score     REAL DEFAULT 0.5,
                retrieval_count INTEGER DEFAULT 0,
                helpful_count   INTEGER DEFAULT 0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute("INSERT INTO facts (content) VALUES ('legacy fact')")
        conn.commit()
        original_size = Path(db_path).stat().st_size
        conn.close()

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            # Baseline is v0, so backup should be .db.bak.v0.
            backup_path = Path(f"{db_path}.bak.v0")
            assert backup_path.exists()
            # WAL checkpoint before copy should make the backup complete.
            assert backup_path.stat().st_size >= original_size
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)
            backup_path.unlink(missing_ok=True)

    def test_source_doc_id_is_nullable(self) -> None:
        """Facts can exist without a source document; bad FKs are rejected."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            # Insert a fact without source_doc_id should succeed.
            store._conn.execute(
                "INSERT INTO facts (content) VALUES (?)", ("standalone fact",)
            )
            store._conn.commit()

            # Insert with a non-existent doc_id should fail.
            with pytest.raises(sqlite3.IntegrityError):
                store._conn.execute(
                    "INSERT INTO facts (content, source_doc_id) VALUES (?, ?)",
                    ("orphan fact", 999),
                )
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_document_delete_sets_source_doc_id_null(self) -> None:
        """FK is ON after init: deleting a document clears linked facts' source."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        store = MemoryStore(db_path=db_path, hrr_dim=256)
        try:
            cur = store._conn.execute(
                "INSERT INTO documents (raw_text, text_hash) VALUES (?, ?) RETURNING doc_id",
                ("raw doc text", "a" * 64),
            )
            doc_id = cur.fetchone()["doc_id"]
            store._conn.execute(
                "INSERT INTO facts (content, source_doc_id) VALUES (?, ?)",
                ("derived fact", doc_id),
            )
            store._conn.commit()

            store._conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            store._conn.commit()

            row = store._conn.execute(
                "SELECT source_doc_id FROM facts WHERE content = ?",
                ("derived fact",),
            ).fetchone()
            assert row["source_doc_id"] is None
        finally:
            store.close()
            Path(db_path).unlink(missing_ok=True)

    def test_migration_v6_fts_covers_merged_facts(self) -> None:
        """v6: FTS5 rebuild must make soft-deleted facts searchable.

        The v5 bug: facts_fts was populated only from active facts.
        For a content= FTS5 table, this means the FTS5 index entries for
        merged facts are absent, so text search can't match them even if
        the source row exists. v6 runs 'rebuild' to re-index from the
        full content source table, making merged fact content searchable.
        """
        from holographic.store import _migration_v6_fts_fix_merged_coverage
        import pathlib as pl

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(
            "CREATE TABLE facts ("
            "    fact_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "    content TEXT NOT NULL UNIQUE,"
            "    category TEXT DEFAULT 'general',"
            "    tags TEXT DEFAULT '',"
            "    trust_score REAL DEFAULT 0.5,"
            "    retrieval_count INTEGER DEFAULT 0,"
            "    helpful_count INTEGER DEFAULT 0,"
            "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "    hrr_vector BLOB,"
            "    source_doc_id INTEGER,"
            "    merged_into INTEGER"
            ");"
            "CREATE VIRTUAL TABLE facts_fts"
            "    USING fts5(content, tags, content=facts, content_rowid=fact_id, tokenize='trigram');"
            "CREATE TABLE entities"
            "    (entity_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);"
        )
        conn.execute(
            "INSERT INTO facts (content, category, tags) VALUES (?, ?, ?)",
            ("holographic active", "general", ""),
        )
        conn.execute(
            "INSERT INTO facts (content, category, tags, merged_into) VALUES (?, ?, ?, ?)",
            ("holographic merged", "general", "", 1),
        )
        conn.commit()

        # Reproduce the v5 bug: only index active facts in FTS5
        conn.execute(
            "INSERT INTO facts_fts(rowid, content, tags)"
            " SELECT fact_id, content, tags FROM facts WHERE merged_into IS NULL"
        )
        conn.commit()

        # Verify the bug: searching for 'merged' should return 0 results since
        # the merged fact was not indexed. (trigram needs >= 3 chars: 'mer' works)
        hits_before = conn.execute(
            "SELECT facts_fts.rowid FROM facts_fts WHERE facts_fts MATCH 'merged'"
        ).fetchall()
        assert len(hits_before) == 0, (
            f"Bug precondition failed: expected 0 FTS hits for 'merged', got {len(hits_before)}"
        )

        # Apply v6 fix
        _migration_v6_fts_fix_merged_coverage(conn)
        conn.commit()

        # After v6: searching 'merged' must find the previously-missing fact
        hits_after = conn.execute(
            "SELECT facts_fts.rowid FROM facts_fts WHERE facts_fts MATCH 'merged'"
        ).fetchall()
        assert len(hits_after) == 1, (
            f"After v6, expected 1 FTS hit for 'merged', got {len(hits_after)}"
        )

        conn.close()
        pl.Path(db_path).unlink(missing_ok=True)
