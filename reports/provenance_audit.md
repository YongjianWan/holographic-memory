# Provenance Audit

## Safety

- Source database was copied with SQLite backup API.
- Report reads the copied snapshot only; it does not mutate facts, schema, documents, or provenance.
- `legacy_unknown` is derived at read time from missing `fact_provenance` rows; this report does not write placeholder provenance.
- Source DB: `C:\Users\sdses\AppData\Local\hermes\memory_store.db`
- Snapshot DB: `reports\snapshots\memory_store_provenance_audit_20260629_154307.db`

## Integrity

- generated_at: 2026-06-29T15:43:07
- integrity_check: ok
- foreign_key_violations: 0
- has_provenance_table: True

## Coverage

- facts_active: 2195
- active_known: 1162 (52.94%)
- active_legacy_unknown: 1033 (47.06%)
- provenance_rows_total: 1169
- provenance_rows_for_active: 1165
- active_multi_doc_facts: 2
- source_doc_mismatch_sample_count: 2

## Active Coverage By Category

| category | active_facts | known_facts | legacy_unknown | known_pct | provenance_rows |
|---|---:|---:|---:|---:|---:|
| project | 2079 | 1162 | 917 | 55.89 | 1165 |
| personal | 110 | 0 | 110 | 0.0 | 0 |
| user_pref | 5 | 0 | 5 | 0.0 | 0 |
| general | 1 | 0 | 1 | 0.0 | 0 |

## Provenance By Relation

| relation | rows |
|---|---:|
| origin | 1166 |
| merge | 3 |

## Documents

| doc_id | active_facts | distinct_facts | provenance_rows | source |
|---:|---:|---:|---:|---|
| 21 | 247 | 247 | 247 | docs\achieve\holo-改造方案.md |
| 25 | 209 | 209 | 209 | docs\宪法.md |
| 15 | 130 | 130 | 130 | AGENTS.md |
| 16 | 117 | 117 | 117 | CHANGELOG.md |
| 18 | 96 | 98 | 98 | SESSION.md |
| 22 | 92 | 94 | 94 | docs\achieve\session_2026-06-24_legacy_status.md |
| 17 | 77 | 77 | 78 | ROADMAP.md |
| 20 | 71 | 71 | 71 | docs\achieve\CODE_SUMMARY.md |
| 19 | 66 | 66 | 66 | TECH_DEBT.md |
| 23 | 45 | 45 | 45 | docs\achieve\并发补丁_多agent共享库.md |
| 24 | 14 | 14 | 14 | docs\README.md |
| 1 | 0 | 0 | 0 | C:\Users\sdses\Desktop\现状（部分）.txt |
| 2 | 0 | 0 | 0 | C:\Users\sdses\Desktop\梁局汇报PPT-实际演示版.md |
| 3 | 0 | 0 | 0 | C:\Users\sdses\Desktop\今日.md |
| 4 | 0 | 0 | 0 | C:\Users\sdses\Desktop\AI智能检索与公文写作系统_需求文档.md |
| 5 | 0 | 0 | 0 | C:\Users\sdses\Desktop\ppt修改.txt |
| 6 | 0 | 0 | 0 | C:\Users\sdses\Desktop\招商会议.txt |
| 7 | 0 | 0 | 0 | C:\Users\sdses\Desktop\土地数据.txt |
| 8 | 0 | 0 | 0 | C:\Users\sdses\Desktop\招商2.txt |
| 9 | 0 | 0 | 0 | C:\Users\sdses\Desktop\工作心理问题.txt |

## Multi-Document Fact Samples

| fact_id | source_doc_id | doc_count | sources | content |
|---:|---:|---:|---|---|
| 1001112 | 15 | 2 | AGENTS.md,docs\achieve\CODE_SUMMARY.md | 跑测试命令为 pytest tests/。 |
| 1001804 | 21 | 2 | docs\achieve\holo-改造方案.md,docs\宪法.md | C. merge 改写 content 防 UNIQUE 冲突。 |

## Source Doc Mismatch Samples

| fact_id | source_doc_id | provenance_doc_id | relation | source_fact_id | source | content |
|---:|---:|---:|---|---:|---|---|
| 1001112 | 15 | 20 | merge | 56 | docs\achieve\CODE_SUMMARY.md | 跑测试命令为 pytest tests/。 |
| 1001804 | 21 | 25 | merge | 113 | docs\宪法.md | C. merge 改写 content 防 UNIQUE 冲突。 |
