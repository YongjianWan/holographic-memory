# SESSION.md — 当前工作状态

> 这个文件回答："上次干到哪了、现在在搞什么、有什么临时坑"。
> 跟 TECH_DEBT 的区别：TECH_DEBT 记"欠的债"，SESSION 记"手头的活和临时记忆"。
> 每次开工读它，收工更新它。

## 当前焦点

- **1-4 顺序已完成**：
  1. 文档口径和 CRLF/trailing whitespace 噪音已收束，并先提交 `7c64ba8 docs: realign holographic audit state`。
  2. 已用 SQLite backup API 生成稳定快照审计，报告见 `reports/current_db_ledger.md` / `.json`。
  3. `_LLMExtractor` 增加本地事实/废话守卫，拒收对话状态、睡觉提醒、弹药隐喻、记忆槽位、心理动机推断和模型自言自语。
  4. `retain_document` 批量写入时延迟 category bank 重建，整批完成后每个 category 只重建一次。
- **代码验证**：
  - Windows Python: `import holographic` 通过。
  - Windows pytest: `117 passed in 12.35s`。
  - WSL 环境没有 `python`/`pytest` 命令；该项目当前以 Windows Python 作为有效验证入口。
- **稳定快照 ledger（2026-06-24 15:03:36）**：
  - `facts_total=2741`，`facts_active=1051`，`facts_soft_deleted=1690`，`documents_total=9`，schema v8。
  - `integrity_check=ok`，foreign key violations 为 0。
  - active category：project 933，personal 111，user_pref 6，general 1。
  - 所有 1690 条 soft-deleted facts 当前都指向 `999999 System audit soft-delete marker`，说明当前库已被清理/重抽样改写，不能沿用旧的 2078 active 口径。
  - `project` bank 当前 fact_count 933，按 1024 维估算 SNR 约 1.048，仍低于 2.0。

## 进行中

- [x] 清理 `SESSION.md` 断裂/重复叙述。
- [x] 识别 CRLF / trailing whitespace 噪音。
- [x] 完成第 1 步提交。
- [x] 生成稳定 DB 快照 ledger。
- [x] 增加提取入口守卫。
- [x] 修复批量 retain 重复重建 category bank。

## 下一步顺序

1. 对 `reports/current_db_ledger.md` 中的 dirty/meta 候选做更精细的人工复核；当前简单候选规则仍会把长但有效的事实列入候选。
2. 基于稳定快照重新跑 scope gate，而不是沿用旧 `scope_gate_audit.md`。
3. 决定是否把当前 reports / trial scripts 中的历史产物归档或 ignore，降低工作树噪音。

## 已知陷阱（临时）

- `project` category 仍然过宽；当前快照 fact_count 933，1024 维估算 SNR 约 1.048。
- 当前 reports 目录包含多轮脚本产物，不能默认 `reports/scope_gate_audit.md` 就是最新全库报告。
- 不要直接在活 WAL 库上做结论性审计；先快照，再读快照。
- 事实/对话噪音仍是主风险：提取器要拒收问安、睡觉提醒、聊天节奏、临时隐喻和心理归因，只保留长期可召回的事实、规约、客观结论和明确建议。

## 决策记录

- **scope 不可逆门**：在稳定快照和人工复核完成前，不新增 `facts.scope`、`fact_scopes` 或 provenance migration。
- **source_doc_id 边界**：`source_doc_id` 是单值归属，不是完整 provenance；发生 merge 后不能用它推导完整来源。
- **事实/废话判定边界规则**：LLM 提取 Prompt 必须做客观的“事实/对话噪音”判定，拒收纯互动、聊天状态描述、劝慰和隐喻性表述。
- **生产库测试场纪律**：任何会写真实 `memory_store.db` 的动作都必须先备份，并把 backup 用作前后 diff 基准。
- **P2 图边仍保持否决状态**：除非新的真实快照证明 entity fan-out 明显回升，否则不重启 shared-entity 图边。

---

*Last updated: 2026-06-24*
