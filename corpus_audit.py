"""Build a fallback-extracted corpus from the desktop files and audit:

1. Fact-label distribution using the stronger classifier (no hand-waving).
2. Entity-extraction quality before vs after the quoted-phrase guard.
3. HRR merge-threshold calibration from pairwise similarities.

Usage:
    python corpus_audit.py
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
import types
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

if "hermes_state" not in sys.modules:
    hermes_state = types.ModuleType("hermes_state")
    hermes_state.apply_wal_with_fallback = lambda conn, db_label="": None
    sys.modules["hermes_state"] = hermes_state

if "hermes_constants" not in sys.modules:
    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: Path(tempfile.gettempdir())
    hermes_constants.display_hermes_home = lambda: tempfile.gettempdir()
    sys.modules["hermes_constants"] = hermes_constants

import store  # noqa: E402
import holographic as hrr  # noqa: E402
from batch_retain_eval import PARSERS, _DeepSeekExtractor  # noqa: E402
from sample_facts_for_review import classify_fact  # noqa: E402

WATCH_DIR = Path("C:/Users/sdses/Desktop")
PATTERNS = ["AI*.md", "今日.md", "梁局*.md", "现状*.txt"]
DB_PATH = Path(tempfile.gettempdir()) / "holographic_corpus_audit.db"

_SENTENCE_PUNCT = re.compile(r"[。！？；，、：,;:!?\n\r]")


def _old_extract_entities(text: str) -> list[str]:
    """The pre-fix extractor: deduplication only, no phrase guard."""
    seen: set[str] = set()
    candidates: list[str] = []

    def _add(name: str) -> None:
        stripped = name.strip()
        if stripped and stripped.lower() not in seen:
            seen.add(stripped.lower())
            candidates.append(stripped)

    for m in store._RE_CAPITALIZED.finditer(text):
        _add(m.group(1))
    for m in store._RE_DOUBLE_QUOTE.finditer(text):
        _add(m.group(1))
    for m in store._RE_SINGLE_QUOTE.finditer(text):
        _add(m.group(1))
    for m in store._RE_AKA.finditer(text):
        _add(m.group(1))
        _add(m.group(2))
    return candidates


def build_corpus(extractor: store.FactExtractor | None = None) -> store.MemoryStore:
    if DB_PATH.exists():
        DB_PATH.unlink()
    memory_store = store.MemoryStore(db_path=str(DB_PATH), hrr_dim=1024)
    files: list[Path] = []
    for pat in PATTERNS:
        files.extend(WATCH_DIR.glob(pat))
    files = sorted({p for p in files if p.suffix.lower() in PARSERS})
    for path in files:
        parser = PARSERS[path.suffix.lower()]
        raw_text = parser(path)
        if raw_text.strip():
            memory_store.retain_document(
                raw_text,
                source=str(path.name),
                category="project",
                extractor=extractor,
            )
    return memory_store


def entity_quality(facts: list[dict]) -> dict:
    """Compare entity extraction before/after the quoted-phrase guard."""
    old_counts = []
    new_counts = []
    old_long = 0
    new_long = 0
    old_dirty_entities: list[str] = []
    new_dirty_entities: list[str] = []

    for fact in facts:
        old_names = _old_extract_entities(fact["content"])
        new_names = fact["entities"]
        old_counts.append(len(old_names))
        new_counts.append(len(new_names))
        for name in old_names:
            if len(name) > 20 or _SENTENCE_PUNCT.search(name):
                old_long += 1
                old_dirty_entities.append(name)
        for name in new_names:
            if len(name) > 20 or _SENTENCE_PUNCT.search(name):
                new_long += 1
                new_dirty_entities.append(name)

    return {
        "facts": len(facts),
        "old_entities_total": sum(old_counts),
        "new_entities_total": sum(new_counts),
        "old_avg_entities_per_fact": round(sum(old_counts) / len(facts), 2) if facts else 0.0,
        "new_avg_entities_per_fact": round(sum(new_counts) / len(facts), 2) if facts else 0.0,
        "old_dirty_entities": old_long,
        "new_dirty_entities": new_long,
        "old_dirty_rate": round(old_long / sum(old_counts), 3) if sum(old_counts) else 0.0,
        "new_dirty_rate": round(new_long / sum(new_counts), 3) if sum(new_counts) else 0.0,
        "old_top_dirty": Counter(old_dirty_entities).most_common(10),
        "new_top_dirty": Counter(new_dirty_entities).most_common(10),
    }


def hrr_calibration(memory_store: store.MemoryStore, sample_size: int = 300) -> dict:
    """Sample fact pairs and report similarity distribution + candidate merges."""
    rows = memory_store._conn.execute(
        """
        SELECT fact_id, content FROM facts
        WHERE hrr_vector IS NOT NULL
        ORDER BY fact_id
        LIMIT ?
        """,
        (sample_size,),
    ).fetchall()
    if len(rows) < 2:
        return {"error": "not enough facts with HRR vectors"}

    ids = [r["fact_id"] for r in rows]
    contents = [r["content"] for r in rows]
    vectors = []
    for fact_id in ids:
        blob = memory_store._conn.execute(
            "SELECT hrr_vector FROM facts WHERE fact_id = ?", (fact_id,)
        ).fetchone()["hrr_vector"]
        vectors.append(hrr.bytes_to_phases(blob))

    sims: list[float] = []
    top_pairs: list[tuple[float, str, str]] = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            sim = float(hrr.similarity(vectors[i], vectors[j]))
            sims.append(sim)
            top_pairs.append((sim, contents[i], contents[j]))

    top_pairs.sort(reverse=True)
    sims.sort()
    n = len(sims)
    return {
        "sampled_facts": len(rows),
        "pair_count": n,
        "similarity_distribution": {
            "min": round(sims[0], 3),
            "p25": round(sims[n // 4], 3),
            "p50": round(sims[n // 2], 3),
            "p75": round(sims[3 * n // 4], 3),
            "p90": round(sims[int(n * 0.9)], 3),
            "p95": round(sims[int(n * 0.95)], 3),
            "p99": round(sims[int(n * 0.99)], 3),
            "max": round(sims[-1], 3),
        },
        "top_10_pairs": [
            {"sim": round(s, 3), "a": a[:120], "b": b[:120]}
            for s, a, b in top_pairs[:10]
        ],
        "candidate_merges": {
            "threshold_0.80": sum(1 for s in sims if s >= 0.80),
            "threshold_0.85": sum(1 for s in sims if s >= 0.85),
            "threshold_0.90": sum(1 for s in sims if s >= 0.90),
            "threshold_0.95": sum(1 for s in sims if s >= 0.95),
        },
    }


def run(extractor: store.FactExtractor | None = None) -> dict:
    print("Building corpus...")
    memory_store = build_corpus(extractor=extractor)

    rows = memory_store._conn.execute(
        "SELECT fact_id, content, source_doc_id FROM facts ORDER BY fact_id"
    ).fetchall()
    source_map = {
        r["doc_id"]: r["source"]
        for r in memory_store._conn.execute("SELECT doc_id, source FROM documents").fetchall()
    }

    facts: list[dict] = []
    labels: Counter[str] = Counter()
    for row in rows:
        fact_id = row["fact_id"]
        content = row["content"]
        entity_rows = memory_store._conn.execute(
            """
            SELECT e.name FROM entities e
            JOIN fact_entities fe ON fe.entity_id = e.entity_id
            WHERE fe.fact_id = ?
            """,
            (fact_id,),
        ).fetchall()
        entities = [r["name"] for r in entity_rows]
        label, reason = classify_fact(content, entities)
        labels[label] += 1
        facts.append(
            {
                "fact_id": fact_id,
                "source": source_map.get(row["source_doc_id"], "?"),
                "content": content,
                "entities": entities,
                "label": label,
                "reason": reason,
            }
        )

    label_distribution = {
        label: {"count": count, "rate": round(count / len(facts), 3) if facts else 0.0}
        for label, count in sorted(labels.items(), key=lambda x: -x[1])
    }

    entity_report = entity_quality(facts)
    hrr_report = hrr_calibration(memory_store)

    report = {
        "files_scanned": sorted({f["source"] for f in facts}),
        "total_facts": len(facts),
        "label_distribution": label_distribution,
        "entity_quality": entity_report,
        "hrr_calibration": hrr_report,
    }

    json_path = PROJECT_ROOT / "corpus_audit_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report written to {json_path}")

    memory_store.close()
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Corpus audit")
    parser.add_argument(
        "--llm",
        choices=["fallback", "deepseek"],
        default="fallback",
        help="Extractor to use (default: fallback)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        help="DeepSeek model name (default: deepseek-v4-flash)",
    )
    args = parser.parse_args()

    extractor: store.FactExtractor | None = None
    if args.llm == "deepseek":
        extractor = _DeepSeekExtractor(model=args.model)

    report = run(extractor=extractor)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
