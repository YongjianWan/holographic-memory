# reports/ — 审计与脚本产物目录

> 本目录存放只读审计脚本、DB 操作备份和临时评估报告。
> **它不是当前状态的单一事实源**；当前状态以 [CHANGELOG.md](../CHANGELOG.md) 和 [SESSION.md](../SESSION.md) 为准。

## 目录内容分类

| 类型 | 命名模式 | 说明 |
|------|----------|------|
| 当前 DB ledger | `current_db_ledger.{md,json}` | 最近一次稳定快照统计 |
| DB 操作备份 | `live_backups/memory_store_before_*_YYYYmmdd_HHMMSS.db` | 写库前的 SQLite 备份 |
| 快照副本 | `snapshots/memory_store_*_YYYYmmdd_HHMMSS.db` | 只读审计用的临时快照 |
| Dirty fact 候选 | `dirty_fact_candidates.{md,json}` | 当前整库 dirty/meta 人工复核候选 |
| Dirty fact 裁决记录 | `dirty_fact_apply_YYYYmmdd_HHMMSS.{md,json}` | 某次 soft-delete 操作的记录 |
| HRR bank 审计 | `hrr_bank_partition_audit.{md,json}` / `hrr_bank_resharding.{md,json}` | HRR bank 解耦前后的只读/写库审计 |
| Provenance 审计 | `provenance_audit.{md,json}` | `fact_provenance` 覆盖情况 |
| RRF A/B 审计 | `rrf_ab_audit.{md,json}` | 默认 search 三路 vs 两路 RRF 对比 |
| 召回审计 | `recall_audit.{md,json}` | 同义/黑话探针命中率，列出 miss 供手标黑话/通用同义（lexicon 种子源） |
| Scope gate 审计 | `scope_gate_audit.{md,json}` | scope 可分性只读审计 |
| 其他历史审计 | `*_audit.md`, `*_report.md`, `gate_*_*.md` | 各轮只读审计产物 |

## 如何找到最新报告

1. 优先看文件名中的 **UTC 时间戳 `YYYYmmdd_HHMMSS`**；时间戳越新，报告越新。
2. 其次看 [SESSION.md](../SESSION.md) 或 [CHANGELOG.md](../CHANGELOG.md) 中提到的报告文件名。
3. **不要默认不带时间戳的文件就是最新的**；例如 `scope_gate_audit.md` 可能是旧轮次产物。

## 保留策略

- **`live_backups/`**：每次写库前自动生成，建议保留到下一次重大写库操作确认无误后再清理。
- **`snapshots/`**：只读审计的临时快照，可定期清理；原始数据在 `memory_store.db`。
- **`dirty_fact_candidates.*`**：当前复核状态文件，保留到下一轮复核完成。
- **`dirty_fact_apply_*.*`**：写库操作记录，建议长期保留以支持审计。
- **其他 `*_audit.*`**：可保留最近 2-3 轮，过期后归档或删除。

## 生成方式

所有报告由 `tests/scripts/run_*.py` 生成，不手写。脚本默认先通过 SQLite backup API 创建快照，再对快照做只读分析（写库类脚本除外）。

## 注意事项

- 报告中的数字会过期；做 schema/代码 决策前请以 [SESSION.md](../SESSION.md) 或重新运行脚本为准。
- 不要把本目录下的任何 `.db` 快照误当作 live DB 使用。
