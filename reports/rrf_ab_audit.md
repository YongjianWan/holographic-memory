# RRF A/B Audit

## Safety

- Source database was copied with SQLite backup API.
- Report reads the copied snapshot only; it does not call `search()` and does not mutate retrieval_count or last_accessed_at.
- Default search is FTS5+Jaccard; 3-way results shown here are a hypothetical comparison path.
- The audit measures ranking movement only; it does not claim relevance quality without human labels.
- Source DB: `C:\Users\sdses\AppData\Local\hermes\memory_store.db`
- Snapshot DB: `reports\snapshots\memory_store_rrf_ab_audit_20260629_154036.db`

## Summary

- generated_at: 2026-06-29T15:40:39
- facts_active: 2195
- query_count: 20
- median_top5_overlap: 0.8
- min_top5_overlap: 0.4
- top1_changed_count: 12
- hrr_only_top3_query_count: 0
- recommendation: hrr_changes_rankings_materially_needs_human_relevance_judgment

## Queries

| query | top5_overlap | top1_changed | hrr_only_top3_count | top_3way_ids | top_2way_ids |
|---|---:|---|---:|---|---|
| Holographic memory provider | 0.8 | False | 0 | [1001115, 1, 1001116, 1001590, 22] | [1001115, 1, 24, 1001116, 22] |
| fact_provenance legacy_unknown | 0.8 | False | 0 | [1001370, 1001367, 1001251, 1001498, 1001247] | [1001370, 1001251, 1001153, 1001498, 1001367] |
| source_doc_id provenance | 0.8 | True | 0 | [1001366, 1001248, 1001494, 1001307, 1001367] | [1001494, 1001366, 1001248, 1001307, 1001773] |
| HRR bank sharding | 0.8 | False | 0 | [1001375, 1002205, 1001583, 1001402, 1001225] | [1001375, 1001583, 1002205, 1001402, 1001982] |
| category source_doc shard256 | 1.0 | True | 0 | [1001312, 1001313, 1001434, 1001376, 1001406] | [1001406, 1001312, 1001376, 1001434, 1001313] |
| dirty fact candidates | 0.8 | True | 0 | [1001536, 1001535, 1001338, 1001371, 1001474] | [1001535, 1001474, 1001536, 1001239, 1001371] |
| Gate A Gate B scope | 0.4 | True | 0 | [1002204, 1001974, 1001936, 1001244, 1002205] | [1001559, 1001402, 1001582, 1002204, 1002205] |
| P2 graph edge veto | 1.0 | True | 0 | [1001360, 1001260, 1001388, 1001156, 1001186] | [1001156, 1001360, 1001260, 1001186, 1001388] |
| retain_document extraction | 1.0 | False | 0 | [1001152, 1001296, 1001178, 1001312, 1001245] | [1001152, 1001178, 1001296, 1001245, 1001312] |
| LLM extractor rejects chatter | 0.4 | True | 0 | [3, 1001286, 1001179, 1001417, 1001190] | [28, 1001190, 1001179, 1001189, 1001191] |
| retrieval_count side effect | 1.0 | False | 0 | [1001221, 1001795, 1001633, 1001704, 1001710] | [1001221, 1001704, 1001633, 1001795, 1001710] |
| RRF FTS Jaccard HRR | 0.6 | True | 0 | [1002170, 1002155, 1001274, 1001384, 25] | [1002155, 1001609, 1001384, 1001700, 25] |
| 无常驻进程 | 0.8 | True | 0 | [1001119, 1001593, 1000080, 1001683, 1001825] | [1001593, 1001119, 1000080, 1001683, 1001827] |
| 关机即文件 | 1.0 | True | 0 | [1002061, 1001686, 1002008, 1001685, 1002064] | [1001686, 1002061, 1002008, 1001685, 1002064] |
| 软删除 merged_into | 1.0 | False | 0 | [1001154, 1002098, 1001536, 1002029, 26] | [1001154, 26, 1001536, 1002098, 1002029] |
| 迁移前备份 | 0.4 | False | 0 | [1001446, 29, 1001862, 154, 1002097] | [1001446, 29, 203, 1001164, 1001479] |
| 事实废话判定边界 | 0.6 | False | 0 | [1001191, 1001490, 1001537, 1001485, 1002126] | [1001191, 1001490, 1001537, 1001481, 1001501] |
| 项目元文档 原子提炼 | 0.4 | True | 0 | [1001663, 1001469, 1001763, 1001776, 1001472] | [28, 1001663, 1001190, 1001191, 1001469] |
| legacy Hindsight 长 fact | 0.4 | True | 0 | [1001912, 1001206, 1001663, 1001366, 1001249] | [1001532, 1002083, 1001912, 24, 1001663] |
| DeepSeek retain routing | 0.6 | True | 0 | [1001315, 1001114, 1000902, 1001317, 1001645] | [1000902, 1000736, 88, 1001114, 1001315] |

## Top Differences

| query | 3-way top1 | 2-way top1 |
|---|---|---|
| source_doc_id provenance | 1001366: source_doc_id is a legacy single-value attribution, not full provenance. | 1001494: source_doc_id 是单值归属，不是完整 provenance；发生 merge 后不能用它推导完整来源。 |
| category source_doc shard256 | 1001312: retain_document delays category bank rebuilds during batch fact writes. | 1001406: Priority on splitting by source_doc_id/doc group, category bucketing, or downgrading HRR from default search. |
| dirty fact candidates | 1001536: 偿还计划：复核当前快照dirty fact候选，确认后通过merged_into软删除。 | 1001535: 当前稳定快照后仍有少量meta/dirty candidates需要人眼确认。 |
| Gate A Gate B scope | 1002204: Scope many-to-many (scopes/fact_scopes) is gated on Gate B. | 1001559: Scope Gate B首次审计判定为NO-GO。 |
| P2 graph edge veto | 1001360: P2 graph edges were vetoed by real data. | 1001156: fact_edges 图边 + CTE 多跳（P2）被 veto 冻结。 |
| LLM extractor rejects chatter | 3: Platform uses three vertical LLMs: general LLM, investment attraction vertical LLM, report generation LLM. Data sources include Haier enterprise database (30M+), Jinan policy/land/fund database, industry dynamics, government cloud computing power. | 28: holographic memory 新增文档保留流程：retain_document 存储原始文本，按 SHA256 去重，通过 FactExtractor 协议提取原子 facts。支持 pluggable extractor：_LocalFallbackExtractor（句子拆分，标记 fallback）和 _LLMExtractor（注入 model_call）。长文档按段落/句边界分块，默认 max_chunk_tokens=6000。 |
| RRF FTS Jaccard HRR | 1002170: 三条硬约束：A.FTS5粗筛+Jaccard精判，不用HRR（entities缺席+同类信号冗余）。语义近重复故意留给P1。 | 1002155: RRF融合三路：FTS5/Jaccard/HRR，只用名次不用原始分。 |
| 无常驻进程 | 1001119: 核心红线之一：无常驻进程、无外部依赖。 | 1001593: 该插件无常驻进程和外部向量服务。 |
| 关机即文件 | 1002061: 关机即文件、开机即用、无启动序列。 | 1001686: Holo 命根子是「关机即文件、开机即用，无启动序列」。 |
| 项目元文档 原子提炼 | 1001663: 文章入口将长文档提炼为多条 fact 并保存原文。 | 28: holographic memory 新增文档保留流程：retain_document 存储原始文本，按 SHA256 去重，通过 FactExtractor 协议提取原子 facts。支持 pluggable extractor：_LocalFallbackExtractor（句子拆分，标记 fallback）和 _LLMExtractor（注入 model_call）。长文档按段落/句边界分块，默认 max_chunk_tokens=6000。 |
| legacy Hindsight 长 fact | 1001912: When the query side encounters a legacy fact without a provenance row, it should project it as `legacy_unknown` at read time. | 1001532: 偿还计划：不修旧账，只保护新账，后续查询层优先读fact_provenance，无行时返回legacy unknown。 |
| DeepSeek retain routing | 1001315: It remains pinned to DeepSeek (deepseek-v4-flash by default). | 1000902: DeepSeek的依据是中科院的一份报告。 |
