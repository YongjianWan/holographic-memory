"""Tests for the read-only recall audit probe logic.

The recall audit surfaces synonym/jargon recall misses for hand-labeling: each
probe is a query that deliberately phrases a known fact with a *different* term,
so a MISS means FTS5/Jaccard could not bridge the wording gap (a lexicon seed
candidate). These tests pin the HIT/MISS classification on a tiny temp store so
the behavior is regression-covered without touching the live database.
"""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

from holographic.retrieval import FactRetriever
from holographic.store import MemoryStore

SCRIPT = Path(__file__).parent / "scripts" / "run_recall_audit.py"
SPEC = importlib.util.spec_from_file_location("recall_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
recall = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recall)


def _store_with_facts() -> MemoryStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    store = MemoryStore(db_path=tmp.name, default_trust=0.5, hrr_dim=256)
    store.add_fact("The deduplication guard runs before the INSERT statement")
    store.add_fact("The graphics card RTX 4090 has strong rendering performance")
    # Decoys that strongly match the MISS probe's wording, so the synonym-only
    # target is pushed out of a small top-K (mirrors a large real corpus where a
    # miss means the fact ranks below the cutoff, not that nothing is returned).
    store.add_fact("CPU benchmark score measures raw processor throughput")
    store.add_fact("A higher benchmark score means faster processor performance")
    store.add_fact("Benchmark score charts rank each processor by speed")
    return store


def test_probe_hit_when_query_shares_wording() -> None:
    store = _store_with_facts()
    retriever = FactRetriever(store=store, hrr_dim=256)
    try:
        result = recall.evaluate_probe(
            retriever,
            {"query": "deduplication guard INSERT", "expect": "deduplication"},
        )
        assert result["hit"] is True
        assert result["matched_fact_id"] is not None
    finally:
        store.close()
        Path(store.db_path).unlink(missing_ok=True)


def test_probe_miss_when_only_a_synonym_bridges_the_gap() -> None:
    store = _store_with_facts()
    retriever = FactRetriever(store=store, hrr_dim=256)
    try:
        # "GPU" never appears in the corpus; only the synonym "graphics card"
        # does. Lexical search cannot bridge GPU -> graphics card, so this is a
        # genuine recall miss and a lexicon seed candidate.
        result = recall.evaluate_probe(
            retriever,
            {"query": "benchmark score processor", "expect": "graphics card"},
            limit=2,
        )
        assert result["hit"] is False
        assert result["matched_fact_id"] is None
    finally:
        store.close()
        Path(store.db_path).unlink(missing_ok=True)
