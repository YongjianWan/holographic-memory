"""HRR quality audit: side-by-side 3-way vs 2-way top-5 for diverged queries."""
import os
import sys
import pathlib

# Patch sys.path to find both the plugin and hermes internals
HERMES_AGENT = r"C:\Users\sdses\AppData\Local\hermes\hermes-agent"
HERE = str(pathlib.Path(__file__).parent)
sys.path.insert(0, HERMES_AGENT)
sys.path.insert(0, HERE)

from store import MemoryStore
from retrieval import FactRetriever

hermes_home = os.environ.get("HERMES_HOME") or str(
    pathlib.Path.home() / "AppData" / "Local" / "hermes"
)
db_path = pathlib.Path(hermes_home) / "memory_store.db"
if not db_path.exists():
    print(f"ERROR: database not found at {db_path}")
    sys.exit(1)

print(f"Using DB: {db_path}  ({db_path.stat().st_size // 1024} KB)\n")

store = MemoryStore(db_path=str(db_path))
retriever = FactRetriever(store)

QUERIES = [
    "投促局项目",
    "凌云志企业",
    "发改委",
    "李善光",
    "Python 偏好",
    "holographic 记忆",
    "trust score",
    "migration schema",
    "FTS5 分词",
    "向量相似度",
    "毕局",
    "企业评分",
    "chat 入口",
    "数据库备份",
    "RRF fusion",
]

TOPK = 5

original_hrr = retriever._hrr_ranking

def search_3way(query):
    retriever._hrr_ranking = original_hrr
    return retriever.search(query, limit=TOPK, min_trust=0.0)

def search_2way(query):
    retriever._hrr_ranking = lambda *a, **kw: []
    try:
        return retriever.search(query, limit=TOPK, min_trust=0.0)
    finally:
        retriever._hrr_ranking = original_hrr

diverged = []
overlaps = []

for q in QUERIES:
    r3 = search_3way(q)
    r2 = search_2way(q)
    ids3 = {r["fact_id"] for r in r3[:TOPK]}
    ids2 = {r["fact_id"] for r in r2[:TOPK]}
    overlap = len(ids3 & ids2) / TOPK
    overlaps.append(overlap)
    if overlap < 1.0:
        diverged.append((q, overlap, r3, r2))

overlaps.sort()
median_overlap = overlaps[len(overlaps) // 2]

print(f"Queries: {len(QUERIES)}  |  Diverged: {len(diverged)}  |  Median overlap: {median_overlap:.2f}\n")

print("=" * 80)
print("DIVERGED QUERIES (where HRR changed the top-5)")
print("=" * 80)

for q, overlap, r3, r2 in diverged:
    ids3 = {r["fact_id"] for r in r3[:TOPK]}
    ids2 = {r["fact_id"] for r in r2[:TOPK]}
    hrr_added = ids3 - ids2
    hrr_removed = ids2 - ids3

    print(f"\nQuery: [{q}]  overlap={overlap:.2f}")
    print(f"  HRR injected into top-5: {hrr_added}  |  HRR evicted from top-5: {hrr_removed}")

    print(f"  3-way top-{TOPK}:")
    for i, r in enumerate(r3[:TOPK]):
        tag = " <- HRR added this" if r["fact_id"] in hrr_added else ""
        print(f"    {i+1}. id={r['fact_id']} | {r['content'][:100]}{tag}")

    print(f"  2-way top-{TOPK}:")
    for i, r in enumerate(r2[:TOPK]):
        tag = " <- HRR evicted this" if r["fact_id"] in hrr_removed else ""
        print(f"    {i+1}. id={r['fact_id']} | {r['content'][:100]}{tag}")

store.close()

print("\n" + "=" * 80)
print("VERDICT: check each '← HRR added this' line.")
print("  Relevant? -> HRR helping.")
print("  Word-overlap noise, wrong topic? -> HRR hurting, revert to 2-way.")
print("=" * 80)
