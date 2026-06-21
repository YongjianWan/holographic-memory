"""
SQLite-backed fact store with entity resolution and trust scoring.
Single-user Hermes memory store plugin.
"""

import difflib
import hashlib
import logging
import math
import re
import shutil
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

try:
    from . import holographic as hrr
except ImportError:
    import holographic as hrr  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

# Optional tiktoken for a more realistic content-item count in HRR capacity
# warnings. If unavailable we fall back to the same whitespace split used by
# encode_text(). The core package does not depend on tiktoken.
try:
    import tiktoken

    _CONTENT_ITEM_ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover - tiktoken is optional
    _CONTENT_ITEM_ENCODING = None


def _content_item_count(content: str) -> int:
    """Count discrete content items for HRR capacity estimation.

    Mirrors encode_text tokenisation when tiktoken is unavailable. When
    tiktoken is present we use its token count, which is much more meaningful
    for Chinese text where whitespace split would treat a whole sentence as one
    item.
    """
    if _CONTENT_ITEM_ENCODING is not None:
        return len(_CONTENT_ITEM_ENCODING.encode(content))
    return len(content.split())


_SENTENCE_END_RE = re.compile(r"([。！？.!?])")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, preserving Chinese and ASCII sentence endings."""
    parts = _SENTENCE_END_RE.split(text)
    sentences: list[str] = []
    i = 0
    while i < len(parts):
        if i + 1 < len(parts) and parts[i + 1] in "。！？.!?":
            sentences.append(parts[i] + parts[i + 1])
            i += 2
        else:
            if parts[i].strip():
                sentences.append(parts[i])
            i += 1
    return [s.strip() for s in sentences if s.strip()]


def _hard_split_text(text: str, max_tokens: int) -> list[str]:
    """Emergency split when a single sentence exceeds max_tokens."""
    chunks: list[str] = []
    while text:
        if _CONTENT_ITEM_ENCODING is not None:
            # Binary search the longest prefix that fits within the budget.
            low, high = 1, len(text)
            while low < high:
                mid = (low + high + 1) // 2
                if _content_item_count(text[:mid]) <= max_tokens:
                    low = mid
                else:
                    high = mid - 1
            split_at = low
        else:
            # Roughly 4 chars per token for CJK; 6 for Latin.
            split_at = max_tokens * 4
        chunk = text[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        text = text[split_at:].strip()
    return chunks


def _chunk_text(raw_text: str, max_tokens: int) -> list[str]:
    """Split a long document into LLM-friendly chunks.

    Splits first at paragraph boundaries, then at sentence boundaries, and only
    performs hard splits when a single sentence is still too long. Preserves as
    much context as possible while staying under the token budget.
    """
    if _content_item_count(raw_text) <= max_tokens:
        return [raw_text]

    paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    current_tokens = 0

    for para in paragraphs:
        para_tokens = _content_item_count(para)
        if para_tokens > max_tokens:
            # Flush whatever is currently buffered.
            if current:
                chunks.append(current)
                current = ""
                current_tokens = 0
            # Split oversized paragraph by sentence.
            for sent in _split_sentences(para):
                sent_tokens = _content_item_count(sent)
                if sent_tokens > max_tokens:
                    if current:
                        chunks.append(current)
                        current = ""
                        current_tokens = 0
                    chunks.extend(_hard_split_text(sent, max_tokens))
                elif current_tokens + sent_tokens > max_tokens:
                    chunks.append(current)
                    current = sent
                    current_tokens = sent_tokens
                else:
                    current = f"{current} {sent}".strip() if current else sent
                    current_tokens += sent_tokens
        elif current_tokens + para_tokens > max_tokens:
            if current:
                chunks.append(current)
            current = para
            current_tokens = para_tokens
        else:
            current = f"{current}\n\n{para}".strip() if current else para
            current_tokens += para_tokens

    if current:
        chunks.append(current)
    return chunks


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
    hrr_vector      BLOB
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
    USING fts5(content, tags, content=facts, content_rowid=fact_id);

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


# ------------------------------------------------------------------------------
# Schema migrations
# ------------------------------------------------------------------------------


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


_MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migration_v1_ensure_hrr_vector,
    _migration_v2_documents,
    _migration_v3_document_hash,
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
    # `_SCHEMA` creates the latest tables/columns on a fresh DB, but on a
    # legacy DB the existing `facts` table may still lack columns that the
    # migrations are responsible for adding. Match the newest version only
    # when *both* the facts columns and the documents columns are present.
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


# ------------------------------------------------------------------------------
# Document extraction protocol
# ------------------------------------------------------------------------------


class FactExtractor(Protocol):
    """Pluggable extractor: turns a raw document into atomic fact strings."""

    kind: str

    def extract(self, raw_text: str, category: str) -> list[str]:
        ...


class _LocalFallbackExtractor:
    """Crash-only extractor when no LLM is available.

    Produces text fragments, not true atomic facts. Facts emitted by this
    extractor are tagged as fallback and receive a lower initial trust score.
    """

    kind: str = "fallback"

    def __init__(self, min_length: int = 20) -> None:
        self.min_length = min_length

    def extract(self, raw_text: str, category: str) -> list[str]:
        raw_text = raw_text.strip()
        if not raw_text:
            return []
        # Split on sentence boundaries; this is intentionally coarse.
        sentences = re.split(r"(?<=[.!?])\s+", raw_text)
        seen: set[str] = set()
        facts: list[str] = []
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < self.min_length:
                continue
            if sentence in seen:
                continue
            seen.add(sentence)
            facts.append(sentence)
        return facts


class _LLMExtractor:
    """LLM-based atomic-fact extractor.

    The actual API call is injected via ``model_call`` so the core package
    does not depend on any SDK. If the call fails, an empty list is returned
    and the caller is expected to leave an orphan document for retry.
    """

    kind: str = "llm"

    def __init__(self, model_call: Callable[[str], str]) -> None:
        self.model_call = model_call

    def extract(self, raw_text: str, category: str) -> list[str]:
        prompt = self._build_prompt(raw_text, category)
        try:
            response = self.model_call(prompt)
        except Exception:
            return []
        return self._parse_response(response)

    def _build_prompt(self, raw_text: str, category: str) -> str:
        return (
            "You are an atomic-fact extractor. Extract one atomic fact per line from the text below.\n\n"
            "Hard rules:\n"
            "- ONE fact per line. No compound sentences.\n"
            "- Each fact must be self-contained: understandable without the surrounding text.\n"
            "- Preserve exact names, dates, numbers, versions, and scores.\n"
            "- Do NOT use bullets, numbers, markdown, or introductory phrases like 'The fact is'.\n"
            "- If the text contains multiple related claims, split them into separate facts.\n"
            "- Aim for 5-25 words per fact. Never exceed 60 words / 80 tokens per fact.\n"
            "- For Chinese text, split at Chinese sentence/clause boundaries (，。；：） and keep each fact short.\n\n"
            "Good examples:\n"
            "- 投促局项目由李善光负责，当前状态为开发中。\n"
            "- 凌云志企业综合评分为85分，投资意愿88分。\n"
            "- 发改委项目要求所有功能入口整合为Chat形式。\n\n"
            "Bad example (too coarse, do NOT output like this):\n"
            "- 投促局项目由李善光负责且已四次汇报，毕局确认，凌云志85分，发改委要Chat入口。\n\n"
            f"Category: {category}\n\n"
            "---\n"
            f"{raw_text}\n"
            "---\n\n"
            "Atomic facts:"
        )

    def _parse_response(self, response: str) -> list[str]:
        facts: list[str] = []
        seen: set[str] = set()
        for line in response.splitlines():
            line = line.strip().strip("-\u2022*•").strip()
            if len(line) < 12:
                continue
            if line in seen:
                continue
            seen.add(line)
            facts.append(line)
        return facts


# ------------------------------------------------------------------------------
# Migration runner
# ------------------------------------------------------------------------------


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

# Trust adjustment constants
_HELPFUL_DELTA   =  0.05
_UNHELPFUL_DELTA = -0.10
_TRUST_MIN       =  0.0
_TRUST_MAX       =  1.0
_FALLBACK_TRUST  =  0.25  # trust score for fallback-extracted facts

# Entity extraction patterns
_RE_CAPITALIZED  = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
_RE_DOUBLE_QUOTE = re.compile(r'"([^"]+)"')
_RE_SINGLE_QUOTE = re.compile(r"'([^']+)'")
_RE_AKA          = re.compile(
    r'(\w+(?:\s+\w+)*)\s+(?:aka|also known as)\s+(\w+(?:\s+\w+)*)',
    re.IGNORECASE,
)

# Quoted strings often capture whole phrases/sentences (e.g. a task body) rather
# than named entities. Reject candidates that are too long or contain sentence-
# level punctuation. This is a write-time guard; existing dirty entities still
# need a normalization pass.
_MAX_QUOTED_ENTITY_LEN = 20
_RE_SENTENCE_PUNCT     = re.compile(r"[。！？；，、：,;:!?\n\r]")

# Dates, versions, and bare digit sequences — all count toward content specificity.
# Version-like tokens treat '.', '_', '-' as equivalent separators so that
# "K2.7", "K2_7", and "K2-7" share the same numeric signature.
_RE_NUMERIC_DETAIL = re.compile(
    r'\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|(\d+(?:[._-]\d+)+)|(\d+)',
    re.IGNORECASE,
)


def _clamp_trust(value: float) -> float:
    return max(_TRUST_MIN, min(_TRUST_MAX, value))


def _tokenize(text: str) -> set[str]:
    """Simple whitespace tokenization with lowercasing and punctuation stripping.

    Mirrors the tokenizer used by retrieval.py so that write-time Jaccard
    and read-time Jaccard operate on the same token sets.
    """
    if not text:
        return set()
    tokens = set()
    for word in text.lower().split():
        cleaned = word.strip(".,;:!?\"'()[]{}#@<>")
        if cleaned:
            tokens.add(cleaned)
    return tokens


def _extract_numeric_signature(text: str) -> set[str]:
    """Extract normalized numeric/date/version markers from text.

    Version-like tokens with '.', '_', or '-' separators are normalized to
    use '.', so "K2_7" and "K2.7" produce the same signature.
    """
    sig: set[str] = set()
    for m in _RE_NUMERIC_DETAIL.finditer(text):
        if m.group(1):
            # Version-like: normalize separators.
            sig.add(m.group(1).replace("_", ".").replace("-", "."))
        elif m.group(2):
            sig.add(m.group(2))
        else:
            sig.add(m.group(0))
    return sig


def _numeric_hit_count(text: str) -> int:
    """Count distinct numeric/date/version tokens in text."""
    return len(_extract_numeric_signature(text))


def _numeric_signature(text: str) -> frozenset[str]:
    """Return the set of numeric/date/version markers in text.

    Used as a gate in entity clustering: two names whose numeric signatures
    differ are likely a series-vs-version or version-vs-version relationship,
    not lexical variants of the same entity.
    """
    return frozenset(_extract_numeric_signature(text))


def _content_specificity(content: str, entity_count: int) -> float:
    """Higher = more specific content. Used when merging near-duplicate facts.

    Prefers content with linked entities and numeric details, while lightly
    penalizing overly long prose.
    """
    content = content.strip()
    if not content:
        return 0.0
    length = max(len(content), 10)
    return (entity_count + _numeric_hit_count(content)) / math.log(length)


def _snr(dim: int, n_items: int) -> float:
    """HRR signal-to-noise ratio for n_items bundled into dim dimensions."""
    if n_items <= 0:
        return float("inf")
    return math.sqrt(dim / n_items)


def _split_aliases(aliases: str | None) -> list[str]:
    """Split a comma-separated alias string into a list."""
    if not aliases:
        return []
    return [a.strip() for a in aliases.split(",") if a.strip()]


def _entity_specificity(name: str) -> int:
    """Score entity name specificity: higher = more specific.

    Prefers names with version/digit markers and longer forms, so that
    "K2.7" wins over "K2" even if the shorter name has more links.
    """
    stripped = name.strip()
    if not stripped:
        return 0
    digit_count = sum(1 for c in stripped if c.isdigit())
    punct_count = sum(1 for c in stripped if not c.isalnum() and not c.isspace())
    return digit_count * 2 + punct_count + len(stripped)


class _UnionFind:
    """Simple union-find for entity clustering."""

    def __init__(self, items: list[int]) -> None:
        self._parent: dict[int, int] = {item: item for item in items}

    def find(self, item: int) -> int:
        parent = self._parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]  # path compression
            item = parent[item]
        return item

    def union(self, a: int, b: int) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a != root_b:
            self._parent[root_b] = root_a


class MemoryStore:
    """SQLite-backed fact store with entity resolution and trust scoring."""

    def __init__(
        self,
        db_path: "str | Path | None" = None,
        default_trust: float = 0.5,
        hrr_dim: int = 1024,
        near_duplicate_threshold: float = 0.8,
    ) -> None:
        if db_path is None:
            from hermes_constants import get_hermes_home
            db_path = str(get_hermes_home() / "memory_store.db")
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_trust = _clamp_trust(default_trust)
        self.near_duplicate_threshold = max(0.0, min(1.0, near_duplicate_threshold))
        self.hrr_dim = hrr_dim
        self._hrr_available = hrr._HAS_NUMPY
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create tables, indexes, and triggers if they do not exist, then run migrations."""
        # Use the shared WAL-fallback helper so memory_store.db degrades
        # gracefully on NFS/SMB/FUSE-mounted HERMES_HOME (same issue as
        # state.db / kanban.db — see hermes_state._WAL_INCOMPAT_MARKERS).
        from hermes_state import apply_wal_with_fallback
        apply_wal_with_fallback(self._conn, db_label="memory_store.db (holographic)")
        self._conn.executescript(_SCHEMA)
        _run_migrations(self._conn, self.db_path)
        self._conn.commit()

    def _warn_hrr_capacity(self, content: str, entity_names: list[str]) -> None:
        """Warn when a single fact bundles too many items for its HRR dimension.

        The HRR vector for a fact stores one bound component per content item
        (token) plus one per entity. For dim=1024 the SNR drops below 2.0 once
        the total exceeds dim/4 (256 items), which is a hard signal that the
        fact should be split into smaller atomic facts.
        """
        n_content = _content_item_count(content)
        n_entities = len(entity_names)
        n_items = n_content + n_entities
        if n_items > self.hrr_dim // 4:
            snr = _snr(self.hrr_dim, n_items)
            logger.warning(
                "HRR capacity warning: fact bundles %d content items + %d entities = %d "
                "items (dim=%d, SNR=%.2f). Split into atomic facts for reliable retrieval.",
                n_content,
                n_entities,
                n_items,
                self.hrr_dim,
                snr,
            )

    # ------------------------------------------------------------------
    # Near-duplicate detection / merge
    # ------------------------------------------------------------------

    def _find_near_duplicate(
        self,
        content: str,
        category: str,
        threshold: float | None = None,
    ) -> int | None:
        """Find a lexically near-duplicate fact in the same category.

        Uses FTS5 for coarse retrieval and Jaccard token overlap for the
        final decision. Does not update retrieval_count and ignores trust
        filters so that low-trust duplicates are still detected.
        """
        if threshold is None:
            threshold = self.near_duplicate_threshold

        query_tokens = _tokenize(content)
        if not query_tokens:
            return None

        # Build an OR-ed FTS5 query from content tokens. Quoting each token
        # avoids FTS5 syntax errors from punctuation/reserved words.
        match_query = " OR ".join(f'"{tok}"' for tok in query_tokens)

        try:
            rows = self._conn.execute(
                """
                SELECT f.fact_id, f.content, f.tags
                FROM facts_fts
                JOIN facts f ON f.fact_id = facts_fts.rowid
                WHERE facts_fts MATCH ?
                  AND f.category = ?
                ORDER BY facts_fts.rank
                LIMIT 100
                """,
                (match_query, category),
            ).fetchall()
        except sqlite3.Error:
            # Malformed FTS5 query or transient error — fall back to no match.
            return None

        if not rows:
            return None

        new_tokens = _tokenize(content)
        best_id: int | None = None
        best_score = 0.0

        for row in rows:
            candidate_tokens = _tokenize(row["content"]) | _tokenize(row["tags"])
            if not candidate_tokens:
                continue
            intersection = len(new_tokens & candidate_tokens)
            union = len(new_tokens | candidate_tokens)
            score = intersection / union if union else 0.0
            if score > best_score:
                best_score = score
                best_id = int(row["fact_id"])

        if best_id is not None and best_score >= threshold:
            return best_id
        return None

    def _merge_into(
        self,
        existing_id: int,
        content: str,
        tags: str,
        source_doc_id: int | None = None,
    ) -> int:
        """Merge a newly seen fact into an existing one.

        Returns the existing fact_id. Content may be replaced if the new
        wording is more specific; metadata (tags, trust, retrieval_count) is
        always merged. The source document link is kept if already set,
        otherwise the new one is applied.
        """
        row = self._conn.execute(
            "SELECT fact_id, content, tags, trust_score, category, source_doc_id "
            "FROM facts WHERE fact_id = ?",
            (existing_id,),
        ).fetchone()
        if row is None:
            return existing_id

        old_content: str = row["content"]
        old_tags: str = row["tags"] or ""
        old_trust: float = row["trust_score"]
        category: str = row["category"]
        old_source_doc_id: int | None = row["source_doc_id"]

        # Keep an existing source link; otherwise adopt the new one.
        merged_source_doc_id = old_source_doc_id if old_source_doc_id is not None else source_doc_id

        # Entity count for the existing fact (new content entities extracted below).
        old_entity_count = self._conn.execute(
            "SELECT COUNT(*) FROM fact_entities WHERE fact_id = ?",
            (existing_id,),
        ).fetchone()[0]
        new_entity_count = len(self._extract_entities(content))

        old_score = _content_specificity(old_content, old_entity_count)
        new_score = _content_specificity(content, new_entity_count)
        replace_content = new_score > old_score

        # Merge tags.
        merged_tags_set = set(t.strip() for t in old_tags.split(",") if t.strip())
        merged_tags_set.update(t.strip() for t in tags.split(",") if t.strip())
        merged_tags = ", ".join(sorted(merged_tags_set))

        new_trust = max(old_trust, self.default_trust)

        if replace_content:
            try:
                self._conn.execute(
                    """
                    UPDATE facts
                    SET content = ?,
                        tags = ?,
                        trust_score = ?,
                        source_doc_id = ?,
                        retrieval_count = retrieval_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE fact_id = ?
                    """,
                    (content, merged_tags, new_trust, merged_source_doc_id, existing_id),
                )
                self._conn.commit()
                # Re-extract entities and recompute HRR for the new wording.
                self._conn.execute(
                    "DELETE FROM fact_entities WHERE fact_id = ?",
                    (existing_id,),
                )
                new_entity_names = self._extract_entities(content)
                for name in new_entity_names:
                    entity_id = self._resolve_entity(name)
                    self._link_fact_entity(existing_id, entity_id)
                self._warn_hrr_capacity(content, new_entity_names)
                self._compute_hrr_vector(existing_id, content)
                self._rebuild_bank(category)
                return existing_id
            except sqlite3.IntegrityError:
                # New content collides with another row; fall through to metadata-only merge.
                self._conn.rollback()

        # Metadata-only merge (content unchanged or UNIQUE collision).
        self._conn.execute(
            """
            UPDATE facts
            SET tags = ?,
                trust_score = ?,
                source_doc_id = ?,
                retrieval_count = retrieval_count + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE fact_id = ?
            """,
            (merged_tags, new_trust, merged_source_doc_id, existing_id),
        )
        self._conn.commit()
        return existing_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_fact(
        self,
        content: str,
        category: str = "general",
        tags: str = "",
        source_doc_id: int | None = None,
        trust: float | None = None,
    ) -> int:
        """Insert a fact and return its fact_id.

        Checks for near-duplicates (lexical overlap) before INSERT and merges
        into an existing fact when similarity exceeds the configured threshold.
        Falls back to the UNIQUE constraint for exact duplicates.
        """
        with self._lock:
            content = content.strip()
            if not content:
                raise ValueError("content must not be empty")

            initial_trust = _clamp_trust(trust) if trust is not None else self.default_trust

            # First line of defence: lexical near-duplicate detection.
            dup_id = self._find_near_duplicate(content, category)
            if dup_id is not None:
                return self._merge_into(dup_id, content, tags, source_doc_id)

            # Exact duplicate fallback (UNIQUE constraint).
            try:
                cur = self._conn.execute(
                    """
                    INSERT INTO facts (content, category, tags, trust_score, source_doc_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (content, category, tags, initial_trust, source_doc_id),
                )
                self._conn.commit()
                fact_id: int = cur.lastrowid  # type: ignore[assignment]
            except sqlite3.IntegrityError:
                # Duplicate content — return existing id
                row = self._conn.execute(
                    "SELECT fact_id FROM facts WHERE content = ?", (content,)
                ).fetchone()
                return int(row["fact_id"])

            # Entity extraction and linking
            entity_names = self._extract_entities(content)
            for name in entity_names:
                entity_id = self._resolve_entity(name)
                self._link_fact_entity(fact_id, entity_id)

            # Capacity warning before committing the vector.
            self._warn_hrr_capacity(content, entity_names)

            # Compute HRR vector after entity linking
            self._compute_hrr_vector(fact_id, content)
            self._rebuild_bank(category)

            return fact_id

    def retain_document(
        self,
        raw_text: str,
        source: str = "",
        category: str = "general",
        extractor: FactExtractor | None = None,
        max_chunk_tokens: int = 6000,
    ) -> dict:
        """Store a raw document and extract atomic facts from it.

        The document is always persisted first (deduplicated by SHA256 of the
        raw text). Extraction is a separate success/failure unit: if the
        extractor returns nothing, the document remains as an orphan row and
        can be re-extracted later.

        Long documents are chunked before extraction so that LLM-based
        extractors stay within context-window limits without losing paragraph/
        sentence boundaries.

        Returns a dict with ``doc_id``, ``facts_added``, ``extractor_kind``,
        ``fact_ids``, and ``chunks_processed``.
        """
        if extractor is None:
            extractor = _LocalFallbackExtractor()

        raw_text = raw_text.strip()
        if not raw_text:
            raise ValueError("raw_text must not be empty")

        text_hash = _text_hash(raw_text)

        with self._lock:
            # Deduplicate by hash: repeated retains of the same text return the
            # same doc_id without creating a new row.
            self._conn.execute(
                """
                INSERT OR IGNORE INTO documents (raw_text, text_hash, source)
                VALUES (?, ?, ?)
                """,
                (raw_text, text_hash, source),
            )
            self._conn.commit()

            row = self._conn.execute(
                "SELECT doc_id FROM documents WHERE text_hash = ?",
                (text_hash,),
            ).fetchone()
            assert row is not None
            doc_id: int = row["doc_id"]

        # Chunk before extraction so LLM prompts don't overflow. Fallback
        # extractors also benefit from avoiding pathological whole-document
        # splits on Chinese text.
        chunks = _chunk_text(raw_text, max_chunk_tokens)

        fact_ids: list[int] = []
        is_fallback = extractor.kind == "fallback"
        fact_trust = _FALLBACK_TRUST if is_fallback else None

        for chunk in chunks:
            try:
                chunk_facts = extractor.extract(chunk, category)
            except Exception:
                # A failed chunk should not kill the whole document.
                continue
            for fact in chunk_facts:
                fact = fact.strip()
                if not fact:
                    continue
                try:
                    fact_id = self.add_fact(
                        fact,
                        category=category,
                        source_doc_id=doc_id,
                        trust=fact_trust,
                    )
                    fact_ids.append(fact_id)
                except Exception:
                    # A single bad fact should not kill the whole batch.
                    continue

        status = "document_stored_no_facts" if not fact_ids else "ok"
        return {
            "doc_id": doc_id,
            "facts_added": len(fact_ids),
            "extractor_kind": extractor.kind,
            "fact_ids": fact_ids,
            "chunks_processed": len(chunks),
            "status": status,
        }

    def search_facts(
        self,
        query: str,
        category: str | None = None,
        min_trust: float = 0.3,
        limit: int = 10,
    ) -> list[dict]:
        """Full-text search over facts using FTS5.

        Returns a list of fact dicts ordered by FTS5 rank, then trust_score
        descending. Also increments retrieval_count for matched facts.
        """
        with self._lock:
            query = query.strip()
            if not query:
                return []

            params: list = [query, min_trust]
            category_clause = ""
            if category is not None:
                category_clause = "AND f.category = ?"
                params.append(category)
            params.append(limit)

            sql = f"""
                SELECT f.fact_id, f.content, f.category, f.tags,
                       f.trust_score, f.retrieval_count, f.helpful_count,
                       f.created_at, f.updated_at
                FROM facts f
                JOIN facts_fts fts ON fts.rowid = f.fact_id
                WHERE facts_fts MATCH ?
                  AND f.trust_score >= ?
                  {category_clause}
                ORDER BY fts.rank, f.trust_score DESC
                LIMIT ?
            """

            rows = self._conn.execute(sql, params).fetchall()
            results = [self._row_to_dict(r) for r in rows]

            if results:
                ids = [r["fact_id"] for r in results]
                placeholders = ",".join("?" * len(ids))
                self._conn.execute(
                    f"UPDATE facts SET retrieval_count = retrieval_count + 1 WHERE fact_id IN ({placeholders})",
                    ids,
                )
                self._conn.commit()

            return results

    def update_fact(
        self,
        fact_id: int,
        content: str | None = None,
        trust_delta: float | None = None,
        tags: str | None = None,
        category: str | None = None,
    ) -> bool:
        """Partially update a fact. Trust is clamped to [0, 1].

        Returns True if the row existed, False otherwise.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT fact_id, trust_score FROM facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()
            if row is None:
                return False

            assignments: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
            params: list = []

            if content is not None:
                assignments.append("content = ?")
                params.append(content.strip())
            if tags is not None:
                assignments.append("tags = ?")
                params.append(tags)
            if category is not None:
                assignments.append("category = ?")
                params.append(category)
            if trust_delta is not None:
                new_trust = _clamp_trust(row["trust_score"] + trust_delta)
                assignments.append("trust_score = ?")
                params.append(new_trust)

            params.append(fact_id)
            self._conn.execute(
                f"UPDATE facts SET {', '.join(assignments)} WHERE fact_id = ?",
                params,
            )
            self._conn.commit()

            # If content changed, re-extract entities
            if content is not None:
                self._conn.execute(
                    "DELETE FROM fact_entities WHERE fact_id = ?", (fact_id,)
                )
                for name in self._extract_entities(content):
                    entity_id = self._resolve_entity(name)
                    self._link_fact_entity(fact_id, entity_id)
                self._conn.commit()

            # Recompute HRR vector if content changed
            if content is not None:
                self._compute_hrr_vector(fact_id, content)
            # Rebuild bank for relevant category
            cat = category or self._conn.execute(
                "SELECT category FROM facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()["category"]
            self._rebuild_bank(cat)

            return True

    def remove_fact(self, fact_id: int) -> bool:
        """Delete a fact and its entity links. Returns True if the row existed."""
        with self._lock:
            row = self._conn.execute(
                "SELECT fact_id, category FROM facts WHERE fact_id = ?", (fact_id,)
            ).fetchone()
            if row is None:
                return False

            self._conn.execute(
                "DELETE FROM fact_entities WHERE fact_id = ?", (fact_id,)
            )
            self._conn.execute("DELETE FROM facts WHERE fact_id = ?", (fact_id,))
            self._conn.commit()
            self._rebuild_bank(row["category"])
            return True

    def list_facts(
        self,
        category: str | None = None,
        min_trust: float = 0.0,
        limit: int = 50,
    ) -> list[dict]:
        """Browse facts ordered by trust_score descending.

        Optionally filter by category and minimum trust score.
        """
        with self._lock:
            params: list = [min_trust]
            category_clause = ""
            if category is not None:
                category_clause = "AND category = ?"
                params.append(category)
            params.append(limit)

            sql = f"""
                SELECT fact_id, content, category, tags, trust_score,
                       retrieval_count, helpful_count, created_at, updated_at
                FROM facts
                WHERE trust_score >= ?
                  {category_clause}
                ORDER BY trust_score DESC
                LIMIT ?
            """
            rows = self._conn.execute(sql, params).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def record_feedback(self, fact_id: int, helpful: bool) -> dict:
        """Record user feedback and adjust trust asymmetrically.

        helpful=True  -> trust += 0.05, helpful_count += 1
        helpful=False -> trust -= 0.10

        Returns a dict with fact_id, old_trust, new_trust, helpful_count.
        Raises KeyError if fact_id does not exist.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT fact_id, trust_score, helpful_count FROM facts WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"fact_id {fact_id} not found")

            old_trust: float = row["trust_score"]
            delta = _HELPFUL_DELTA if helpful else _UNHELPFUL_DELTA
            new_trust = _clamp_trust(old_trust + delta)

            helpful_increment = 1 if helpful else 0
            self._conn.execute(
                """
                UPDATE facts
                SET trust_score    = ?,
                    helpful_count  = helpful_count + ?,
                    updated_at     = CURRENT_TIMESTAMP
                WHERE fact_id = ?
                """,
                (new_trust, helpful_increment, fact_id),
            )
            self._conn.commit()

            return {
                "fact_id":      fact_id,
                "old_trust":    old_trust,
                "new_trust":    new_trust,
                "helpful_count": row["helpful_count"] + helpful_increment,
            }

    def normalize_entities(
        self,
        edit_threshold: float = 0.85,
        token_threshold: float = 0.9,
    ) -> dict:
        """Merge fragmented entity variants into canonical entities.

        Uses conservative string edit distance and token overlap to cluster
        near-duplicate entity names (e.g. "K2.7", "K2_7", "k2.7"). A
        numeric/date/version signature gate blocks hierarchical pairs such as
        "K2" vs "K2.7" from being treated as writing variants. For each
        cluster, keeps the most specific entity as canonical, moves the other
        names into `aliases`, repoints `fact_entities` foreign keys, and
        recomputes HRR vectors for affected facts.

        Returns a report dict with clusters_merged, entities_merged,
        facts_reindexed, categories_rebuilt.
        """
        with self._lock:
            # Load all entities.
            rows = self._conn.execute(
                "SELECT entity_id, name, aliases, created_at FROM entities"
            ).fetchall()
            if len(rows) < 2:
                return {
                    "clusters_merged": 0,
                    "entities_merged": 0,
                    "facts_reindexed": 0,
                    "categories_rebuilt": [],
                }

            entities = [dict(r) for r in rows]
            entity_ids = [e["entity_id"] for e in entities]
            entities_by_id: dict[int, dict] = {e["entity_id"]: e for e in entities}

            # Fact-link counts per entity (for canonical selection).
            fact_counts: dict[int, int] = {}
            for r in self._conn.execute(
                "SELECT entity_id, COUNT(*) AS c FROM fact_entities GROUP BY entity_id"
            ).fetchall():
                fact_counts[int(r["entity_id"])] = r["c"]

            # Pairwise similarity clustering.
            n = len(entities)
            uf = _UnionFind(entity_ids)

            for i in range(n):
                for j in range(i + 1, n):
                    name_a = entities[i]["name"]
                    name_b = entities[j]["name"]

                    if self._entity_names_match(
                        name_a, name_b, edit_threshold, token_threshold
                    ):
                        uf.union(entities[i]["entity_id"], entities[j]["entity_id"])

            clusters: dict[int, set[int]] = {}
            for eid in entity_ids:
                root = uf.find(eid)
                clusters.setdefault(root, set()).add(eid)

            # Filter to clusters with more than one member.
            merge_clusters = {
                root: members for root, members in clusters.items() if len(members) > 1
            }

            if not merge_clusters:
                return {
                    "clusters_merged": 0,
                    "entities_merged": 0,
                    "facts_reindexed": 0,
                    "categories_rebuilt": [],
                }

            affected_fact_ids: set[int] = set()
            categories_to_rebuild: set[str] = set()
            entities_merged = 0

            for root, members in merge_clusters.items():
                # Sort members to choose canonical:
                # 1. most specific name (digits/punctuation/length)
                # 2. most fact links
                # 3. earliest created
                # 4. lowest entity_id
                sorted_members = sorted(
                    members,
                    key=lambda eid: (
                        -_entity_specificity(entities_by_id[eid]["name"]),
                        -fact_counts.get(eid, 0),
                        entities_by_id[eid]["created_at"] or "",
                        eid,
                    )
                )
                canonical_id = sorted_members[0]
                canonical_entity = entities_by_id[canonical_id]

                # Collect all unique names in the cluster (case-insensitive dedup).
                unique_names: dict[str, str] = {}  # lowercase -> original
                for eid in sorted_members:
                    ent = entities_by_id[eid]
                    for raw_name in [ent["name"]] + _split_aliases(ent["aliases"]):
                        key = raw_name.strip().lower()
                        if key and key not in unique_names:
                            unique_names[key] = raw_name.strip()

                # Aliases = all unique names except the canonical display name.
                canonical_key = canonical_entity["name"].strip().lower()
                alias_names = [
                    name for key, name in unique_names.items() if key != canonical_key
                ]
                alias_str = ", ".join(alias_names)

                # Update canonical entity aliases.
                self._conn.execute(
                    "UPDATE entities SET aliases = ? WHERE entity_id = ?",
                    (alias_str, canonical_id),
                )

                # Repoint fact_entities and track affected facts.
                for eid in sorted_members[1:]:
                    fact_rows = self._conn.execute(
                        "SELECT fact_id FROM fact_entities WHERE entity_id = ?",
                        (eid,),
                    ).fetchall()
                    for fr in fact_rows:
                        affected_fact_ids.add(int(fr["fact_id"]))

                    # Move links to canonical, ignoring duplicates.
                    self._conn.execute(
                        """
                        INSERT OR IGNORE INTO fact_entities (fact_id, entity_id)
                        SELECT fact_id, ? FROM fact_entities WHERE entity_id = ?
                        """,
                        (canonical_id, eid),
                    )
                    self._conn.execute(
                        "DELETE FROM fact_entities WHERE entity_id = ?",
                        (eid,),
                    )
                    self._conn.execute(
                        "DELETE FROM entities WHERE entity_id = ?",
                        (eid,),
                    )
                    entities_merged += 1

            self._conn.commit()

            # Recompute HRR vectors for affected facts.
            if affected_fact_ids and self._hrr_available:
                for fact_id in affected_fact_ids:
                    row = self._conn.execute(
                        "SELECT content, category FROM facts WHERE fact_id = ?",
                        (fact_id,),
                    ).fetchone()
                    if row is None:
                        continue
                    self._compute_hrr_vector(fact_id, row["content"])
                    categories_to_rebuild.add(row["category"])

                for category in categories_to_rebuild:
                    self._rebuild_bank(category)

            return {
                "clusters_merged": len(merge_clusters),
                "entities_merged": entities_merged,
                "facts_reindexed": len(affected_fact_ids),
                "categories_rebuilt": sorted(categories_to_rebuild),
            }

    @staticmethod
    def _entity_names_match(
        name_a: str,
        name_b: str,
        edit_threshold: float,
        token_threshold: float,
    ) -> bool:
        """Return True if two entity names are near-duplicates.

        A numeric/date/version gate runs before any merge decision: if the
        two names carry different numeric signatures, they are treated as
        distinct series/version entities even when their strings are similar.
        """
        if name_a.lower() == name_b.lower():
            return True

        # Numeric signature gate: "K2" vs "K2.7" or "Python" vs "Python 3.12"
        # are hierarchical relationships, not writing variants.
        sig_a = _numeric_signature(name_a)
        sig_b = _numeric_signature(name_b)
        if sig_a or sig_b:
            if sig_a != sig_b:
                return False

        a_lower = name_a.lower()
        b_lower = name_b.lower()

        # Edit distance similarity via difflib.
        edit_sim = difflib.SequenceMatcher(None, a_lower, b_lower).ratio()
        if edit_sim >= edit_threshold:
            return True

        # Token overlap.
        tokens_a = set(re.findall(r"[a-z0-9]+", a_lower))
        tokens_b = set(re.findall(r"[a-z0-9]+", b_lower))
        if not tokens_a or not tokens_b:
            return False
        intersection = len(tokens_a & tokens_b)
        union = len(tokens_a | tokens_b)
        token_sim = intersection / union if union else 0.0
        return token_sim >= token_threshold

    # ------------------------------------------------------------------
    # Entity helpers
    # ------------------------------------------------------------------

    def _extract_entities(self, text: str) -> list[str]:
        """Extract entity candidates from text using simple regex rules.

        Rules applied (in order):
        1. Capitalized multi-word phrases  e.g. "John Doe"
        2. Double-quoted terms             e.g. "Python"
        3. Single-quoted terms             e.g. 'pytest'
        4. AKA patterns                    e.g. "Guido aka BDFL" -> two entities

        Quoted candidates are rejected if they look like a phrase or sentence
        rather than a named entity (too long or containing sentence punctuation).

        Returns a deduplicated list preserving first-seen order.
        """
        seen: set[str] = set()
        candidates: list[str] = []

        def _add(name: str) -> None:
            stripped = name.strip()
            if stripped and stripped.lower() not in seen:
                seen.add(stripped.lower())
                candidates.append(stripped)

        def _looks_like_phrase_not_entity(s: str) -> bool:
            if len(s) > _MAX_QUOTED_ENTITY_LEN:
                return True
            if _RE_SENTENCE_PUNCT.search(s):
                return True
            return False

        for m in _RE_CAPITALIZED.finditer(text):
            candidate = m.group(1)
            if len(candidate) <= _MAX_QUOTED_ENTITY_LEN:
                _add(candidate)

        for m in _RE_DOUBLE_QUOTE.finditer(text):
            candidate = m.group(1)
            if not _looks_like_phrase_not_entity(candidate):
                _add(candidate)

        for m in _RE_SINGLE_QUOTE.finditer(text):
            candidate = m.group(1)
            if not _looks_like_phrase_not_entity(candidate):
                _add(candidate)

        for m in _RE_AKA.finditer(text):
            _add(m.group(1))
            _add(m.group(2))

        return candidates

    def _resolve_entity(self, name: str) -> int:
        """Find an existing entity by name or alias (case-insensitive) or create one.

        Returns the entity_id.
        """
        name_lower = name.strip().lower()

        # Exact name match (case-insensitive, no LIKE wildcards).
        row = self._conn.execute(
            "SELECT entity_id FROM entities WHERE LOWER(name) = ?", (name_lower,)
        ).fetchone()
        if row is not None:
            return int(row["entity_id"])

        # Search aliases — aliases stored as comma-separated.
        # Escape LIKE wildcards in the input to avoid '_' matching any character.
        safe_name = name_lower.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        alias_row = self._conn.execute(
            f"""
            SELECT entity_id FROM entities
            WHERE ',' || LOWER(aliases) || ',' LIKE '%,' || ? || ',%' ESCAPE '\\'
            """,
            (safe_name,),
        ).fetchone()
        if alias_row is not None:
            return int(alias_row["entity_id"])

        # Create new entity
        cur = self._conn.execute(
            "INSERT INTO entities (name) VALUES (?)", (name,)
        )
        self._conn.commit()
        return int(cur.lastrowid)  # type: ignore[return-value]

    def _link_fact_entity(self, fact_id: int, entity_id: int) -> None:
        """Insert into fact_entities, silently ignore if the link already exists."""
        self._conn.execute(
            """
            INSERT OR IGNORE INTO fact_entities (fact_id, entity_id)
            VALUES (?, ?)
            """,
            (fact_id, entity_id),
        )
        self._conn.commit()

    def _compute_hrr_vector(self, fact_id: int, content: str) -> None:
        """Compute and store HRR vector for a fact. No-op if numpy unavailable."""
        with self._lock:
            if not self._hrr_available:
                return

            # Get entities linked to this fact
            rows = self._conn.execute(
                """
                SELECT e.name FROM entities e
                JOIN fact_entities fe ON fe.entity_id = e.entity_id
                WHERE fe.fact_id = ?
                """,
                (fact_id,),
            ).fetchall()
            entities = [row["name"] for row in rows]

            vector = hrr.encode_fact(content, entities, self.hrr_dim)
            self._conn.execute(
                "UPDATE facts SET hrr_vector = ? WHERE fact_id = ?",
                (hrr.phases_to_bytes(vector), fact_id),
            )
            self._conn.commit()

    def _rebuild_bank(self, category: str) -> None:
        """Full rebuild of a category's memory bank from all its fact vectors."""
        with self._lock:
            if not self._hrr_available:
                return

            bank_name = f"cat:{category}"
            rows = self._conn.execute(
                "SELECT hrr_vector FROM facts WHERE category = ? AND hrr_vector IS NOT NULL",
                (category,),
            ).fetchall()

            if not rows:
                self._conn.execute("DELETE FROM memory_banks WHERE bank_name = ?", (bank_name,))
                self._conn.commit()
                return

            vectors = [hrr.bytes_to_phases(row["hrr_vector"]) for row in rows]
            bank_vector = hrr.bundle(*vectors)
            fact_count = len(vectors)

            # Check SNR
            hrr.snr_estimate(self.hrr_dim, fact_count)

            self._conn.execute(
                """
                INSERT INTO memory_banks (bank_name, vector, dim, fact_count, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(bank_name) DO UPDATE SET
                    vector = excluded.vector,
                    dim = excluded.dim,
                    fact_count = excluded.fact_count,
                    updated_at = excluded.updated_at
                """,
                (bank_name, hrr.phases_to_bytes(bank_vector), self.hrr_dim, fact_count),
            )
            self._conn.commit()

    def rebuild_all_vectors(self, dim: int | None = None) -> int:
        """Recompute all HRR vectors + banks from text. For recovery/migration.

        Returns the number of facts processed.
        """
        with self._lock:
            if not self._hrr_available:
                return 0

            if dim is not None:
                self.hrr_dim = dim

            rows = self._conn.execute(
                "SELECT fact_id, content, category FROM facts"
            ).fetchall()

            categories: set[str] = set()
            for row in rows:
                self._compute_hrr_vector(row["fact_id"], row["content"])
                categories.add(row["category"])

            for category in categories:
                self._rebuild_bank(category)

            return len(rows)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a sqlite3.Row to a plain dict."""
        return dict(row)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
