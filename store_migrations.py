"""SQLite schema and migration runner for the holographic memory store.

This module is intentionally separate from store.py so that the schema history
and migration logic do not bloat the core MemoryStore implementation.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text    TEXT NOT NULL,
    text_hash   TEXT NOT NULL UNIQUE,
    source      TEXT DEFAULT '',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS facts (
    fact_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content         TEXT NOT NULL UNIQUE,
    category        TEXT DEFAULT 'general',
    tags            TEXT DEFAULT '',
    trust_score     REAL DEFAULT 0.5,
    retrieval_count INTEGER DEFAULT 0,
    helpful_count   INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_doc_id   INTEGER REFERENCES documents(doc_id) ON DELETE SET NULL,
    hrr_vector      BLOB,
    merged_into     INTEGER REFERENCES facts(fact_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS entities (
    entity_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    entity_type TEXT DEFAULT 'unknown',
    aliases     TEXT DEFAULT '',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fact_entities (
    fact_id   INTEGER REFERENCES facts(fact_id),
    entity_id INTEGER REFERENCES entities(entity_id),
    PRIMARY KEY (fact_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_facts_trust    ON facts(trust_score DESC);
CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);
CREATE INDEX IF NOT EXISTS idx_entities_name  ON entities(name);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
    USING fts5(content, tags, content=facts, content_rowid=fact_id, tokenize="trigram");

CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, content, tags)
        VALUES (new.fact_id, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, tags)
        VALUES ('delete', old.fact_id, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, content, tags)
        VALUES ('delete', old.fact_id, old.content, old.tags);
    INSERT INTO facts_fts(rowid, content, tags)
        VALUES (new.fact_id, new.content, new.tags);
END;

CREATE TABLE IF NOT EXISTS memory_banks (
    bank_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_name  TEXT NOT NULL UNIQUE,
    vector     BLOB NOT NULL,
    dim        INTEGER NOT NULL,
    fact_count INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _text_hash(raw_text: str) -> str:
    """Stable SHA256 hash for raw document text (used for deduplication)."""
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def _migration_v1_ensure_hrr_vector(conn: sqlite3.Connection) -> None:
    """Formalize the historical hrr_vector column addition as migration v1."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(facts)").fetchall()}
    if "hrr_vector" not in columns:
        conn.execute("ALTER TABLE facts ADD COLUMN hrr_vector BLOB")


def _migration_v2_documents(conn: sqlite3.Connection) -> None:
    """Ensure documents table and source_doc_id link exist on legacy databases."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            doc_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_text    TEXT NOT NULL,
            source      TEXT DEFAULT '',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(facts)").fetchall()}
    if "source_doc_id" not in columns:
        conn.execute(
            """
            ALTER TABLE facts
            ADD COLUMN source_doc_id INTEGER
                REFERENCES documents(doc_id)
                ON DELETE SET NULL
            """
        )


def _migration_v3_document_hash(conn: sqlite3.Connection) -> None:
    """Add text_hash to documents for deduplication of raw text."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if "text_hash" not in columns:
        conn.execute("ALTER TABLE documents ADD COLUMN text_hash TEXT")
    # Backfill any rows that lack a hash. SQLite has no sha256 built-in, so we
    # compute hashes in Python and update in batches to keep memory bounded.
    rows = conn.execute(
        "SELECT doc_id, raw_text FROM documents WHERE text_hash IS NULL"
    ).fetchall()
    for doc_id, raw_text in rows:
        conn.execute(
            "UPDATE documents SET text_hash = ? WHERE doc_id = ?",
            (_text_hash(raw_text), doc_id),
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_text_hash "
        "ON documents(text_hash)"
    )


def _migration_v4_merged_into(conn: sqlite3.Connection) -> None:
    """Add merged_into to facts for soft-deletion/supersession during consolidation."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(facts)").fetchall()}
    if "merged_into" not in columns:
        conn.execute(
            """
            ALTER TABLE facts
            ADD COLUMN merged_into INTEGER
                REFERENCES facts(fact_id)
                ON DELETE SET NULL
            """
        )


def _migration_v5_trigram_tokenizer(conn: sqlite3.Connection) -> None:
    """Migrate facts_fts to use the trigram tokenizer for CJK support."""
    # 1. Drop existing virtual table
    conn.execute("DROP TABLE IF EXISTS facts_fts")
    # 2. Recreate with trigram tokenizer
    conn.execute(
        """
        CREATE VIRTUAL TABLE facts_fts
            USING fts5(content, tags, content=facts, content_rowid=fact_id, tokenize="trigram")
        """
    )
    # 3. Populate index from ALL facts (including soft-deleted merged_into IS NOT NULL).
    # Filtering to active-only here would silently break reactivation: if a merged fact
    # is later revived via UPDATE merged_into = NULL, it would be absent from the FTS5
    # index and invisible to search. Query-time filtering (WHERE merged_into IS NULL in
    # the JOIN to the content= source table) is already handled by the content= FTS5
    # configuration, so indexing full set is the safe choice.
    conn.execute(
        """
        INSERT INTO facts_fts(rowid, content, tags)
        SELECT fact_id, content, tags FROM facts
        """
    )


def _migration_v6_fts_fix_merged_coverage(conn: sqlite3.Connection) -> None:
    """Rebuild facts_fts to include ALL facts, not just active ones.

    v5 migration incorrectly populated facts_fts only from active facts
    (WHERE merged_into IS NULL). This breaks the soft-delete reactivation
    contract: when a merged fact is revived via UPDATE merged_into = NULL,
    the facts_au trigger fires a delete-then-insert sequence in FTS5. The
    delete half emits a negative phantom entry for a rowid that was never in
    the index, corrupting FTS5 internal state.

    The 'rebuild' command re-reads ALL rows from the content= source table
    (facts), producing a correct full-coverage FTS5 index. Query-time JOINs
    on merged_into IS NULL handle active-only filtering at search time.

    NOTE: For content= FTS5 tables, SELECT rowid FROM facts_fts reads from
    the content source table (not the FTS shadow tables), so a rowid comparison
    cannot detect partial coverage. The rebuild is always run: rebuilding a
    correct index is idempotent and produces a correct index.
    """
    conn.execute("INSERT INTO facts_fts(facts_fts) VALUES ('rebuild')")


_MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migration_v1_ensure_hrr_vector,
    _migration_v2_documents,
    _migration_v3_document_hash,
    _migration_v4_merged_into,
    _migration_v5_trigram_tokenizer,
    _migration_v6_fts_fix_merged_coverage,
]


def _get_schema_version(conn: sqlite3.Connection) -> int | None:
    """Return the recorded schema version, or None if the table does not exist."""
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
    except sqlite3.OperationalError:
        # schema_version table does not exist yet.
        return None
    return int(row["version"]) if row is not None else None


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    # Keep exactly one row: the current schema version.
    conn.execute("DELETE FROM schema_version")
    conn.execute(
        "INSERT INTO schema_version (version) VALUES (?)",
        (version,),
    )


def _detect_schema_version(conn: sqlite3.Connection) -> int:
    """Infer the schema version for legacy DBs without schema_version table.

    Matches from newest to oldest so that a fresh database created from the
    latest _SCHEMA is immediately recognised as up-to-date.
    """
    fact_columns = {row[1] for row in conn.execute("PRAGMA table_info(facts)").fetchall()}
    doc_columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    
    fts_sql_row = conn.execute("SELECT sql FROM sqlite_master WHERE name='facts_fts'").fetchone()
    has_trigram = False
    if fts_sql_row and fts_sql_row["sql"] and "trigram" in fts_sql_row["sql"]:
        has_trigram = True

    # `_SCHEMA` creates the latest tables/columns on a fresh DB, but on a
    # legacy DB the existing `facts` table may still lack columns that the
    # migrations are responsible for adding. Match the newest version only
    # when *both* the facts columns and the documents columns are present.
    if (
        has_trigram
        and "merged_into" in fact_columns
        and "text_hash" in doc_columns
        and "source_doc_id" in fact_columns
        and "hrr_vector" in fact_columns
        and "documents" in tables
    ):
        # v5 and v6 have identical schema structure (same tables/columns/tokenizer).
        # We cannot distinguish them by schema alone. Always return 5 so that v6
        # migration (FTS5 rebuild) runs. The rebuild is idempotent and safe to
        # run on an already-correct index.
        return 5
    if (
        "merged_into" in fact_columns
        and "text_hash" in doc_columns
        and "source_doc_id" in fact_columns
        and "hrr_vector" in fact_columns
        and "documents" in tables
    ):
        return 4
    if (
        "text_hash" in doc_columns
        and "source_doc_id" in fact_columns
        and "hrr_vector" in fact_columns
        and "documents" in tables
    ):
        return 3
    if "source_doc_id" in fact_columns and "documents" in tables:
        return 2
    if "hrr_vector" in fact_columns:
        return 1
    return 0


def _run_migrations(conn: sqlite3.Connection, db_path: Path) -> None:
    """Apply pending migrations, backing up the database before any change.

    Foreign keys are disabled during migrations so that ALTER/CREATE statements
    are not blocked by constraints, then re-enabled and checked afterwards.
    Pragma changes must happen outside of any transaction to take effect.
    """
    # SQLite: PRAGMA foreign_keys has no effect inside a transaction. Commit
    # first to guarantee we are outside any transaction, then disable FK
    # enforcement for the migration work.
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.commit()

    try:
        current = _get_schema_version(conn)
        if current is None:
            # Baseline detection for pre-migration databases.
            current = _detect_schema_version(conn)
            _set_schema_version(conn, current)
            conn.commit()

        target = len(_MIGRATIONS)
        if current < target:
            # Backup once before applying any new migrations. In WAL mode the
            # main .db file may lag the WAL, so checkpoint first to ensure the
            # backup is complete. Do not overwrite an existing backup.
            backup_path = Path(f"{db_path}.bak.v{current}")
            if not backup_path.exists():
                conn.execute("PRAGMA wal_checkpoint(FULL)")
                shutil.copy2(db_path, backup_path)

            for version in range(current + 1, target + 1):
                _MIGRATIONS[version - 1](conn)
                _set_schema_version(conn, version)
                conn.commit()
    finally:
        # Re-enable foreign keys on every exit path (including the common
        # "already up-to-date" case). Ensure no active transaction when
        # toggling the pragma.
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                f"Foreign key violations after migration: {violations}"
            )
