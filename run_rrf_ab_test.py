"""RRF A/B test runner.

Runs 30 queries on the desktop-extracted corpus and computes the overlap
between 3-way RRF and 2-way RRF top-5 results to determine if HRR is noise.
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Hermes stubs
if "hermes_state" not in sys.modules:
    hermes_state = types.ModuleType("hermes_state")
    hermes_state.apply_wal_with_fallback = lambda conn, db_label="": None
    sys.modules["hermes_state"] = hermes_state

if "hermes_constants" not in sys.modules:
    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: Path(tempfile.gettempdir())
    hermes_constants.display_hermes_home = lambda: tempfile.gettempdir()
    sys.modules["hermes_constants"] = hermes_constants

import store
from retrieval import FactRetriever

DB_PATH = Path(tempfile.gettempdir()) / "holographic_corpus_audit.db"

QUERIES = [
    "AI智能检索",
    "梁局汇报",
    "陈楚俞 考勤",
    "招商平台",
    "招商供应商",
    "考勤用工明细",
    "大模型公文写作",
    "AI辅助围标",
    "围标治理",
    "数据字段",
    "技术摸底",
    "政策评估",
    "招商对策",
    "神思需求",
    "智能体建设",
    "李善光",
    "秦高翔",
    "朱家腾",
    "万永健",
    "市长 汇报",
    "招商 平台",
    "考勤 明细",
    "公文写作",
    "围标",
    "智能体",
    "技术框架",
    "技术债",
    "招商对策报告",
    "进度表",
    "报销 研发",
]

def main() -> None:
    if not DB_PATH.exists():
        print(f"Database {DB_PATH} not found. Running corpus_audit.py to build it...")
        import subprocess
        subprocess.run([sys.executable, "corpus_audit.py"], check=True)

    db = store.MemoryStore(db_path=str(DB_PATH), hrr_dim=1024)
    retriever = FactRetriever(store=db, hrr_dim=1024)

    overlaps = []
    print(f"{'Query':<30} | {'3-way Top-5':<18} | {'2-way Top-5':<18} | Overlap")
    print("-" * 80)

    for query in QUERIES:
        pool = 100
        fts_ranking = retriever._fts_ranking(query, None, 0.0, pool)
        jaccard_ranking = retriever._jaccard_ranking(query, None, 0.0, pool)
        hrr_ranking = retriever._hrr_ranking(query, None, 0.0, pool)
        
        candidate_ids = set(fts_ranking) | set(jaccard_ranking) | set(hrr_ranking)
        if not candidate_ids:
            overlaps.append(1.0)
            print(f"{query:<30} | {str([]):<18} | {str([]):<18} | 1.00 (Empty)")
            continue

        rows = retriever._fetch_facts(candidate_ids, None, 0.0)
        
        scored_3way = []
        scored_2way = []
        for fact in rows:
            fid = fact["fact_id"]
            rrf_score_2way = 0.0
            if fid in fts_ranking:
                rrf_score_2way += 1.0 / (60 + fts_ranking[fid])
            if fid in jaccard_ranking:
                rrf_score_2way += 1.0 / (60 + jaccard_ranking[fid])

            rrf_score_3way = rrf_score_2way
            if fid in hrr_ranking:
                rrf_score_3way += 1.0 / (60 + hrr_ranking[fid])

            trust_boost = 1.0 + 0.2 * (fact["trust_score"] - 0.5)
            
            scored_2way.append((fid, rrf_score_2way * trust_boost))
            scored_3way.append((fid, rrf_score_3way * trust_boost))

        scored_2way.sort(key=lambda x: x[1], reverse=True)
        scored_3way.sort(key=lambda x: x[1], reverse=True)
        
        ids_2way = [x[0] for x in scored_2way[:5]]
        ids_3way = [x[0] for x in scored_3way[:5]]

        intersection = set(ids_3way) & set(ids_2way)
        overlap = len(intersection) / max(len(ids_3way), 1)
        overlaps.append(overlap)

        print(f"{query:<30} | {str(ids_3way):<18} | {str(ids_2way):<18} | {overlap:.2f}")

    overlaps.sort()
    n = len(overlaps)
    median_overlap = overlaps[n // 2] if n % 2 != 0 else (overlaps[n // 2 - 1] + overlaps[n // 2]) / 2.0
    print("-" * 80)
    print(f"Total Queries Evaluated: {len(QUERIES)}")
    print(f"Overlap Stats: Min={overlaps[0]:.2f}, Max={overlaps[-1]:.2f}, Median={median_overlap:.2f}")
    
    if median_overlap > 0.90:
        print("\n[RESULT] Median overlap > 0.90. HRR leg has negligible impact and is likely NOISE.")
    else:
        print("\n[RESULT] Median overlap <= 0.90. HRR leg is contributing unique ranking signals.")

if __name__ == "__main__":
    main()
