# HRR Bank Partition Audit

## Safety

- Source database was copied with SQLite backup API.
- The audit reads the copied snapshot only; it does not write memory_banks, facts, schema, or provenance.
- Schemes below are virtual partitions for measurement, not persisted schema.
- Source DB: `C:\Users\sdses\AppData\Local\hermes\memory_store.db`
- Snapshot DB: `reports\snapshots\memory_store_hrr_bank_audit_20260627_190126.db`

## Summary

- generated_at: 2026-06-27T19:01:26
- active_facts_scanned: 2199
- hrr_dim: 1024
- capacity_items: 256
- recommendation: viable_without_scope / category_source_doc_shard256
- recommendation_reason: all virtual banks are below HRR capacity without adding scope schema

## Scheme Comparison

| scheme | banks | max_fact_count | max_snr | over_capacity | snr_below_2 | missing_hrr |
|---|---:|---:|---:|---:|---:|---:|
| category | 4 | 2083 | 0.701 | 1 | 1 | 0 |
| category_source_doc | 23 | 264 | 1.969 | 1 | 1 | 0 |
| category_document_family | 8 | 895 | 1.07 | 3 | 3 | 0 |
| category_source_doc_shard256 | 24 | 256 | 2.0 | 0 | 0 | 0 |

## Top Banks: category

| bank | facts | snr | over_capacity | doc | source |
|---|---:|---:|---|---:|---|
| cat:project | 2083 | 0.701 | True | None |  |
| cat:personal | 110 | 3.051 | False | 9 | C:\Users\sdses\Desktop\工作心理问题.txt |
| cat:user_pref | 5 | 14.311 | False | None |  |
| cat:general | 1 | 32.0 | False | None |  |

## Top Banks: category_source_doc

| bank | facts | snr | over_capacity | doc | source |
|---|---:|---:|---|---:|---|
| cat:project|doc:6 | 264 | 1.969 | True | 6 | C:\Users\sdses\Desktop\招商会议.txt |
| cat:project|doc:21 | 247 | 2.036 | False | 21 | docs\achieve\holo-改造方案.md |
| cat:project|doc:1 | 227 | 2.124 | False | 1 | C:\Users\sdses\Desktop\现状（部分）.txt |
| cat:project|doc:8 | 218 | 2.167 | False | 8 | C:\Users\sdses\Desktop\招商2.txt |
| cat:project|doc:25 | 208 | 2.219 | False | 25 | docs\宪法.md |
| cat:project|doc:15 | 130 | 2.807 | False | 15 | AGENTS.md |
| cat:project|doc:16 | 117 | 2.958 | False | 16 | CHANGELOG.md |
| cat:personal|doc:9 | 110 | 3.051 | False | 9 | C:\Users\sdses\Desktop\工作心理问题.txt |
| cat:project|doc:18 | 98 | 3.232 | False | 18 | SESSION.md |
| cat:project|doc:22 | 94 | 3.301 | False | 22 | docs\achieve\session_2026-06-24_legacy_status.md |
| cat:project|doc:17 | 77 | 3.647 | False | 17 | ROADMAP.md |
| cat:project|doc:4 | 77 | 3.647 | False | 4 | C:\Users\sdses\Desktop\AI智能检索与公文写作系统_需求文档.md |
| cat:project|doc:20 | 70 | 3.825 | False | 20 | docs\achieve\CODE_SUMMARY.md |
| cat:project|doc:19 | 66 | 3.939 | False | 19 | TECH_DEBT.md |
| cat:project|doc:3 | 47 | 4.668 | False | 3 | C:\Users\sdses\Desktop\今日.md |
| cat:project|doc:5 | 46 | 4.718 | False | 5 | C:\Users\sdses\Desktop\ppt修改.txt |
| cat:project|doc:23 | 45 | 4.77 | False | 23 | docs\achieve\并发补丁_多agent共享库.md |
| cat:project|doc:none | 22 | 6.822 | False | None |  |
| cat:project|doc:24 | 14 | 8.552 | False | 24 | docs\README.md |
| cat:project|doc:7 | 14 | 8.552 | False | 7 | C:\Users\sdses\Desktop\土地数据.txt |

## Top Banks: category_document_family

| bank | facts | snr | over_capacity | doc | source |
|---|---:|---:|---|---:|---|
| cat:project|family:desktop_import | 895 | 1.07 | True | 1 | C:\Users\sdses\Desktop\现状（部分）.txt |
| cat:project|family:repo_root_doc | 488 | 1.449 | True | 15 | AGENTS.md |
| cat:project|family:repo_docs_archive | 456 | 1.499 | True | 20 | docs\achieve\CODE_SUMMARY.md |
| cat:project|family:repo_docs_current | 222 | 2.148 | False | 24 | docs\README.md |
| cat:personal|family:desktop_import | 110 | 3.051 | False | 9 | C:\Users\sdses\Desktop\工作心理问题.txt |
| cat:project|family:legacy_none | 22 | 6.822 | False | None |  |
| cat:user_pref|family:legacy_none | 5 | 14.311 | False | None |  |
| cat:general|family:legacy_none | 1 | 32.0 | False | None |  |

## Top Banks: category_source_doc_shard256

| bank | facts | snr | over_capacity | doc | source |
|---|---:|---:|---|---:|---|
| cat:project|doc:6|shard:00 | 256 | 2.0 | False | 6 | C:\Users\sdses\Desktop\招商会议.txt |
| cat:project|doc:21|shard:00 | 247 | 2.036 | False | 21 | docs\achieve\holo-改造方案.md |
| cat:project|doc:1|shard:00 | 227 | 2.124 | False | 1 | C:\Users\sdses\Desktop\现状（部分）.txt |
| cat:project|doc:8|shard:00 | 218 | 2.167 | False | 8 | C:\Users\sdses\Desktop\招商2.txt |
| cat:project|doc:25|shard:00 | 208 | 2.219 | False | 25 | docs\宪法.md |
| cat:project|doc:15|shard:00 | 130 | 2.807 | False | 15 | AGENTS.md |
| cat:project|doc:16|shard:00 | 117 | 2.958 | False | 16 | CHANGELOG.md |
| cat:personal|doc:9|shard:00 | 110 | 3.051 | False | 9 | C:\Users\sdses\Desktop\工作心理问题.txt |
| cat:project|doc:18|shard:00 | 98 | 3.232 | False | 18 | SESSION.md |
| cat:project|doc:22|shard:00 | 94 | 3.301 | False | 22 | docs\achieve\session_2026-06-24_legacy_status.md |
| cat:project|doc:17|shard:00 | 77 | 3.647 | False | 17 | ROADMAP.md |
| cat:project|doc:4|shard:00 | 77 | 3.647 | False | 4 | C:\Users\sdses\Desktop\AI智能检索与公文写作系统_需求文档.md |
| cat:project|doc:20|shard:00 | 70 | 3.825 | False | 20 | docs\achieve\CODE_SUMMARY.md |
| cat:project|doc:19|shard:00 | 66 | 3.939 | False | 19 | TECH_DEBT.md |
| cat:project|doc:3|shard:00 | 47 | 4.668 | False | 3 | C:\Users\sdses\Desktop\今日.md |
| cat:project|doc:5|shard:00 | 46 | 4.718 | False | 5 | C:\Users\sdses\Desktop\ppt修改.txt |
| cat:project|doc:23|shard:00 | 45 | 4.77 | False | 23 | docs\achieve\并发补丁_多agent共享库.md |
| cat:project|doc:none|shard:00 | 22 | 6.822 | False | None |  |
| cat:project|doc:24|shard:00 | 14 | 8.552 | False | 24 | docs\README.md |
| cat:project|doc:7|shard:00 | 14 | 8.552 | False | 7 | C:\Users\sdses\Desktop\土地数据.txt |
