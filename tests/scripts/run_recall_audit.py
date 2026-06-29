"""Read-only recall audit: surface synonym/jargon recall misses for hand-labeling.

Why this exists (2026-06-29 decision patch): the mother red line accepts "no
semantic recall" — FTS5/Jaccard match on shared wording, so a query phrased with
a *different* term than the stored fact will miss it. This audit makes those
misses visible so a human can label each one as:

  - 黑话 / jargon  : a self-coined term only the LLM-reading-your-corpus can bridge
                     (e.g. 探重 == 去重). Goes to the lexicon via P1-2/P1-4 later.
  - 通用同义 / common synonym : a dictionary synonym (e.g. 显卡 == GPU). Could be
                     covered by a general thesaurus.
  - absent        : the fact genuinely is not in the corpus (not a recall miss).

The hand-labeled 黑话/通用同义 split is exactly the number needed to answer "how
much jargon is there" and "is word2vec worth it", and the 黑话 pairs become the
initial seeds for the `semantic_equivalence_*` lexicon (no P1-2 required).

Safety: snapshots the source DB with the SQLite backup API and reads the copy
only. It reuses the *default* 3-way RRF ranking (FTS5 + Jaccard + HRR with query
expansion) via FactRetriever internals, so it does not call `search()` and does
not mutate retrieval_count / last_accessed_at on the source.

A probe is `{"query": str, "expect": str | int, "note": str}`:
  - expect as str  -> HIT if any top-K result content contains the substring.
  - expect as int  -> HIT if that fact_id appears in the top-K.

Pass a real probe set with `--probes path.json`. The built-in SEED_PROBES is a
tiny illustration only; real probes must be authored against the live corpus.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PARENT_DIR = PROJECT_ROOT.parent
if "" in sys.path:
    sys.path.remove("")
sys.path.insert(0, str(PARENT_DIR))

# Hermes internals are absent when running outside hermes. Inject minimal stubs
# so the holographic package imports cleanly (idempotent guards).
if "hermes_state" not in sys.modules:
    _hermes_state = types.ModuleType("hermes_state")
    _hermes_state.apply_wal_with_fallback = lambda conn, db_label="": None
    sys.modules["hermes_state"] = _hermes_state

if "hermes_constants" not in sys.modules:
    _hermes_constants = types.ModuleType("hermes_constants")
    _hermes_constants.get_hermes_home = lambda: Path(".")
    _hermes_constants.display_hermes_home = lambda: "."
    sys.modules["hermes_constants"] = _hermes_constants

if "agent.memory_provider" not in sys.modules:
    _memory_provider = types.ModuleType("agent.memory_provider")

    class _MemoryProvider:
        @property
        def name(self) -> str:
            return "stub"

    _memory_provider.MemoryProvider = _MemoryProvider
    sys.modules["agent.memory_provider"] = _memory_provider
    sys.modules.setdefault("agent", types.ModuleType("agent"))

if "tools.registry" not in sys.modules:
    _tools_registry = types.ModuleType("tools.registry")
    _tools_registry.tool_error = lambda message: f"ERROR: {message}"
    sys.modules["tools.registry"] = _tools_registry
    sys.modules.setdefault("tools", types.ModuleType("tools"))

if "hermes_cli.config" not in sys.modules:
    _hermes_cli_config = types.ModuleType("hermes_cli.config")
    _hermes_cli_config.cfg_get = lambda config, *keys, default=None: default
    sys.modules["hermes_cli.config"] = _hermes_cli_config
    sys.modules.setdefault("hermes_cli", types.ModuleType("hermes_cli"))

from holographic.retrieval import FactRetriever, _RRF_K  # noqa: E402


# Tiny illustration only. Real audits MUST pass --probes authored against the
# live corpus; these placeholders just document the probe shape.
SEED_PROBES: list[dict[str, Any]] = [
    {
        "query": "GPU 跑分",
        "expect": "显卡",
        "note": "通用同义示例：显卡 == GPU（词典同义，词林可覆盖）",
    },
    {
        "query": "去重 写入前",
        "expect": "探重",
        "note": "黑话示例：探重 == 去重（自造词，只有读语料的 LLM 能搭桥）",
    },
]


def _default_db_path() -> Path:
    return Path("C:/Users/sdses/AppData/Local/hermes/memory_store.db")


def create_snapshot(source: Path, snapshot_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_dir / f"memory_store_recall_audit_{timestamp}.db"

    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(snapshot)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    return snapshot


class _ReadOnlyStore:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn


def _open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rrf_score(rankings: list[dict[int, int]], fact_id: int) -> float:
    score = 0.0
    for ranking in rankings:
        if fact_id in ranking:
            score += 1.0 / (_RRF_K + ranking[fact_id])
    return score


def default_search_topk(
    retriever: FactRetriever,
    query: str,
    *,
    category: str | None = None,
    min_trust: float = 0.0,
    pool: int = 100,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Top-K of the *default* 3-way RRF path, without `search()` side effects.

    Mirrors `FactRetriever.search` (FTS5 + Jaccard + HRR with query expansion and
    multiplicative trust/recency/speaker boosts) but reads only, so it is safe on
    a read-only snapshot connection.
    """
    expanded = retriever._expand_query_with_equivalences(query)
    fts = retriever._fts_ranking(expanded, category, min_trust, pool)
    jaccard = retriever._jaccard_ranking(expanded, category, min_trust, pool)
    hrr = retriever._hrr_ranking(expanded, category, min_trust, pool)

    candidate_ids = set(fts) | set(jaccard) | set(hrr)
    rows = retriever._fetch_facts(candidate_ids, category, min_trust)
    rankings = [fts, jaccard, hrr]

    scored = []
    for fact in rows:
        fid = int(fact["fact_id"])
        trust_boost = 1.0 + 0.2 * (float(fact["trust_score"]) - 0.5)
        recency_boost = retriever._recency_boost(
            fact.get("last_accessed_at") or fact.get("created_at")
        )
        speaker_penalty = 0.85 if re.match(r"^说话人\s*\d+", fact["content"]) else 1.0
        score = _rrf_score(rankings, fid) * trust_boost * recency_boost * speaker_penalty
        scored.append(
            {"fact_id": fid, "score": round(score, 8), "content": fact["content"]}
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def _probe_matches(expect: Any, fact: dict[str, Any]) -> bool:
    if isinstance(expect, int):
        return fact["fact_id"] == expect
    return str(expect) in str(fact["content"])


def evaluate_probe(
    retriever: FactRetriever,
    probe: dict[str, Any],
    *,
    category: str | None = None,
    min_trust: float = 0.0,
    pool: int = 100,
    limit: int = 5,
) -> dict[str, Any]:
    """Run one probe and classify it as HIT or MISS.

    HIT: the expected fact (by substring or fact_id) appears in the top-K of the
    default search. MISS: it does not — a synonym/jargon recall gap (or an absent
    fact), to be hand-labeled downstream.
    """
    query = str(probe["query"])
    expect = probe["expect"]
    top = default_search_topk(
        retriever,
        query,
        category=category,
        min_trust=min_trust,
        pool=pool,
        limit=limit,
    )
    matched = next((f for f in top if _probe_matches(expect, f)), None)
    return {
        "query": query,
        "expect": expect,
        "note": probe.get("note", ""),
        "hit": matched is not None,
        "matched_fact_id": matched["fact_id"] if matched else None,
        # miss_type is left blank on purpose: the human labels it 黑话 /
        # 通用同义 / absent after reading what came back instead.
        "miss_type": "",
        "top": top,
    }


def build_report(
    snapshot: Path,
    source: Path,
    *,
    probes: list[dict[str, Any]] | None = None,
    category: str | None = None,
    min_trust: float = 0.0,
    pool: int = 100,
    limit: int = 5,
) -> dict[str, Any]:
    probe_set = list(probes if probes is not None else SEED_PROBES)
    conn = _open_readonly(snapshot)
    try:
        store = _ReadOnlyStore(conn)
        retriever = FactRetriever(store=store, hrr_dim=1024)  # type: ignore[arg-type]
        results = [
            evaluate_probe(
                retriever,
                probe,
                category=category,
                min_trust=min_trust,
                pool=pool,
                limit=limit,
            )
            for probe in probe_set
        ]
        facts_active = int(
            conn.execute(
                "SELECT COUNT(*) FROM facts WHERE merged_into IS NULL"
            ).fetchone()[0]
        )
    finally:
        conn.close()

    hits = sum(1 for item in results if item["hit"])
    misses = [item for item in results if not item["hit"]]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_db": str(source),
        "snapshot_db": str(snapshot),
        "read_only": True,
        "facts_active": facts_active,
        "probe_count": len(probe_set),
        "category": category,
        "min_trust": min_trust,
        "pool": pool,
        "limit": limit,
        "summary": {
            "hit_count": hits,
            "miss_count": len(misses),
            "hit_rate": round(hits / max(len(probe_set), 1), 3),
            "note": (
                "Misses are lexicon seed candidates. Hand-label each miss_type as "
                "黑话 / 通用同义 / absent before drawing conclusions about word2vec."
            ),
        },
        "results": results,
    }


def write_reports(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "recall_audit.json"
    md_path = output_dir / "recall_audit.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary = report["summary"]
    lines = [
        "# Recall Audit",
        "",
        "## Safety",
        "",
        "- Source database was copied with SQLite backup API.",
        "- Report reads the copied snapshot only; it does not call `search()` and "
        "does not mutate retrieval_count or last_accessed_at.",
        "- Uses the default 3-way RRF ranking (FTS5 + Jaccard + HRR, with query "
        "expansion).",
        f"- Source DB: `{report['source_db']}`",
        f"- Snapshot DB: `{report['snapshot_db']}`",
        "",
        "## Summary",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- facts_active: {report['facts_active']}",
        f"- probe_count: {report['probe_count']}",
        f"- hit_count: {summary['hit_count']}",
        f"- miss_count: {summary['miss_count']}",
        f"- hit_rate: {summary['hit_rate']}",
        "",
        "> " + summary["note"],
        "",
        "## Misses (lexicon seed candidates — hand-label miss_type)",
        "",
        "| query | expect | miss_type (黑话/通用同义/absent) | note | top1 returned instead |",
        "|---|---|---|---|---|",
    ]
    for item in report["results"]:
        if item["hit"]:
            continue
        top1 = item["top"][0] if item["top"] else {}
        top1_content = str(top1.get("content", "")).replace("|", "\\|").replace("\n", " ")
        query = str(item["query"]).replace("|", "\\|")
        expect = str(item["expect"]).replace("|", "\\|")
        note = str(item["note"]).replace("|", "\\|")
        lines.append(
            f"| {query} | {expect} | {item['miss_type']} | {note} | "
            f"{top1.get('fact_id')}: {top1_content} |"
        )

    lines += [
        "",
        "## Hits",
        "",
        "| query | expect | matched_fact_id |",
        "|---|---|---:|",
    ]
    for item in report["results"]:
        if not item["hit"]:
            continue
        query = str(item["query"]).replace("|", "\\|")
        expect = str(item["expect"]).replace("|", "\\|")
        lines.append(f"| {query} | {expect} | {item['matched_fact_id']} |")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def _load_probes(path: Path | None) -> list[dict[str, Any]] | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "probes" in data:
        data = data["probes"]
    if not isinstance(data, list):
        raise ValueError("probes file must be a JSON list or {\"probes\": [...]}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=_default_db_path())
    parser.add_argument(
        "--probes",
        type=Path,
        help="JSON list of {query, expect, note}. Defaults to the tiny SEED_PROBES.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("reports/snapshots"))
    parser.add_argument("--category")
    parser.add_argument("--min-trust", type=float, default=0.0)
    parser.add_argument("--pool", type=int, default=100)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    db_path = args.db.expanduser().absolute()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    probes = _load_probes(args.probes)
    snapshot = create_snapshot(db_path, args.snapshot_dir)
    report = build_report(
        snapshot,
        db_path,
        probes=probes,
        category=args.category,
        min_trust=args.min_trust,
        pool=args.pool,
        limit=args.limit,
    )
    json_path, md_path = write_reports(report, args.output_dir)
    print(f"snapshot={snapshot}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    print(f"hit_rate={report['summary']['hit_rate']}")
    print(f"miss_count={report['summary']['miss_count']}")


if __name__ == "__main__":
    main()
