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
  - Windows pytest: `117 passed in 12.35s`（v10 前一次完整基线）。
  - v10 targeted tests: `34 passed in 5.31s`（`tests/test_migrations.py` + `tests/test_retain_document.py`）。
  - provenance visibility targeted tests: `48 passed in 4.31s`（`tests/test_retain_document.py` + `tests/test_retrieval_rrf.py` + `tests/test_consolidation.py`）。
  - WSL 环境没有 `python`/`pytest` 命令；该项目当前以 Windows Python 作为有效验证入口。
- **稳定快照 ledger（2026-06-24 15:03:36）**：
  - `facts_total=3181`，`facts_active=1034`，`facts_soft_deleted=2147`，`documents_total=9`，schema v10 代码已落地；生产快照读取时仍需按迁移前/后具体状态注明。
  - `integrity_check=ok`，foreign key violations 为 0。
  - **Active 数量对平对账单（1051 -> 1034，净减少 17）**：
    - `1034 = 1051 + 6 (Doc 6) - 22 (Doc 8) - 1 (Doc None)`
    - **Doc 6 (招商会议.txt) 净增加 6**：新增 248 条，软删除（合并）243 条，复活 1 条（248 - 243 + 1 = +6）
    - **Doc 8 (招商2.txt) 净减少 22**：新增 192 条，软删除（合并）223 条，复活 9 条（192 - 223 + 9 = -22）
    - **Doc None (系统内置/无源事实) 净减少 1**：软删除 1 条，新增 0 条（-1）
  - active category：project 917，personal 111，user_pref 5，general 1。
  - 所有 2147 条 soft-deleted facts 当前都指向 `999999 System audit soft-delete marker`，说明当前库已被清理/重抽样改写，不能沿用旧的 2078 active 口径。
  - `project` bank 当前 fact_count 933，按 1024 维估算 SNR 约 1.048，仍低于 2.0。

## 进行中

- [x] 清理 `SESSION.md` 断裂/重复叙述。
- [x] 识别 CRLF / trailing whitespace 噪音。
- [x] 完成第 1 步提交。
- [x] 生成稳定 DB 快照 ledger。
- [x] 增加提取入口守卫。
- [x] 修复批量 retain 重复重建 category bank。
- [x] 删除仓库内 `SOUL.md` 旧入口；外部 SOUL 的协作纪律已并入 `AGENTS.md` / `docs/宪法.md`。
- [x] 建立 checkpoint commit `4f9aef0 chore: checkpoint holographic workspace state`，作为后续文档清理前的安全点。
- [x] 对齐 `SESSION.md` / `ROADMAP.md` / `TECH_DEBT.md` 的当前状态口径。
- [x] 将旧 `SESSION.md` 状态块归档到 `docs/achieve/session_2026-06-24_legacy_status.md`，避免信息只存在于 git 历史里。
- [x] 落地 migration v10 `fact_provenance`：新 document retain / merge 记录来源账本，旧库不写占位，legacy unknown 由查询侧读时派生。
- [x] 补齐 provenance 可见化：`list_facts` / `search_facts` / RRF retrieval 输出 `provenance` 摘要；无行时读时返回 `legacy_unknown`，不写占位。
- [x] 增加项目文档 retain 脚本：`tests/scripts/run_retain_project_docs.py --dry-run` 已确认 11 个 canonical docs；当前 shell 无 LLM API key，尚未写入 live DB。

## 下一步顺序

1. **导入项目 canonical docs（有 LLM key 的 shell 中执行）**：运行 `tests/scripts/run_retain_project_docs.py --yes`，脚本会先备份 live DB；禁止 fallback 导入。
2. **整库干净度人工确认**：对最新快照中识别出的 6 条 meta candidates 以及 dirty 候选事实进行人工清洗和标记处理。
3. **Source Provenance 报告面细化**：工具输出已经带 `provenance` 摘要；如需审计报告/只读脚本输出更完整来源分布，再补报告层，不再改 schema。
4. **解 HRR 饱和方案解耦实施**：
   - 探讨轻量化、非侵入性、可逆的 HRR bank 物理切分方案（如直接按 `source_doc_id` 切分并聚合 memory bank，或使用粗分类打标），以缓解 `project` bank 的容量压力，彻底与 `facts.scope` 解耦。
5. **Scope 状态：veto / 待证（与 P2 同构，不可逆闸）**：
   - 彻底冻结 Scope 拆分的开发决策。
   - **解冻条件**：在真实使用中撞到“必须依靠域过滤才能答得了”的真实查询（需求驱动），而非“数据攒够”或“分类标签重构”等伪数据驱动。在此之前，不编写任何 Scope 相关的 schema 迁移或处理代码。

## 已知陷阱（临时）

- `project` category 仍然过宽；当前快照 fact_count 933，1024 维估算 SNR 约 1.048。
- **评估器判定边缘指令/主客观事实系统性不稳**：例如 ID 40（"算法跑分不限五个..."）与 ID 1000023（"汇报 PPT 不能展示零"）等边缘指令句，评估器极易抖动。在 Gate A 的 50 条肉眼 Go/No-Go 判定中，决不能迷信评估器单次结果，必须依靠人眼进行最终裁决。
- 当前 reports 目录包含多轮脚本产物，不能默认 `reports/scope_gate_audit.md` 就是最新全库报告。
- 不要直接在活 WAL 库上做结论性审计；先快照，再读快照。
- 事实/对话噪音仍是主风险：提取器要拒收问安、睡觉提醒、聊天节奏、临时隐喻和心理归因，只保留长期可召回的事实、规约、客观结论和明确建议。

## 决策记录

- **Control Group 基准锁定（恢复至 27 条）**：已查明 27 变 26 的根因是上一代 AI 助手遇到评估器对 Fact ID 40（`"算法跑分不限五个..."`）判定抖动时，手动将其从 `_control_fact_ids.txt` 中剔除以凑出 "100% 一致性"（这造成了基准漂移）。我们已经将 ID 40 重新放回，将 Control Group 锁定为原始的 27 条事实，用于度量评估器的客观测量噪声（约 96.3% 一致性），决不再人工调整基准。
- **评估器判定抖动与过抽率**：对评估器主客观判定边界的 ±3.8% 抖动（b 档）收手，对 26.6% 的过抽率依靠出口闸承接；把精力集中在基准物理锁定与对齐上。
- **scope 不可逆门**：在出现真实域过滤需求前，不新增 `facts.scope`、`fact_scopes` 或 scope-driven bank schema。
- **source_doc_id 边界**：`source_doc_id` 是单值归属，不是完整 provenance；发生 merge 后不能用它推导完整来源。
- **provenance 解耦于 scope Gate B**：`fact_provenance` 的动机是 merge 后来源可审计，不是 scope 分域；v10 已落地，不等 Gate B。
- **legacy provenance 不回填**：当前历史 merge 链已被 `999999` marker 拍平，旧 active facts 无 provenance 行是诚实状态；`legacy_unknown` 必须读时派生，禁止写占位。
- **有效期语义待设计**：`trust` 衰减只表示“越老越不确信”，不等于明确失效时点；“本周要交付”这类过期即死的信息归后续 extractor profile / lifecycle 设计，现在不提前写 schema。
- **事实/废话判定边界规则**：LLM 提取 Prompt 必须做客观的“事实/对话噪音”判定，拒收纯互动、聊天状态描述、劝慰 and 隐喻性表述。
- **强模型 + grep/FTS 路线**：embedding 缺失是有意取舍，不是当前 bug。检索层负责可审计候选召回和 provenance，理解留给当下 LLM；召回不足优先做 query reformulation，不先引入向量服务。
- **P1-4 定位与红线定型**：只做 induction（抽结构不抽人），拒做 deduction/abduction（禁动机推断）。引入 `source_fact_ids >= 2` 非空硬闸。承认通用模型天花板，不加 embedding/自训模型等任何依赖，不行则砍。gated on Gate A 审计。
- **生产库测试场纪律**：任何会写真实 `memory_store.db` 的动作都必须先备份，并把 backup 用作前后 diff 基准。
- **Gate A 人手复核通过并正式 GO (2026-06-24)**：对分层抽样的 50 条事实进行了人眼审计，判定 40 条 PASS / 10 条 FAIL，真实可信 GO 率达到 80.0%。规则已拉直：会议发言事件均计为客观事件记录（PASS，包括 1000901/1000818），去情境化无主语泛论（970）计为 FAIL，1000023（汇报PPT不能展示零）锁定为跨版本通用汇报规约（PASS）。决议通过 Gate A 关卡，正式进入下一步。
- **Gate B 首次审计判定为 NO-GO (2026-06-24)**：
  - **当前状态**：`scope` 归入 **veto / 待证** 状态（与 P2 同构）。
  - **NO-GO 根因**：① 分类器尺子不可信（粗暴塞筐且混合了资产与噪音）；② 尚无“必须按域过滤检索才答得了”的真实查询需求，证据不足（“数据不够”）。
  - **解冻条件**：真实使用中撞到该类非它不可的需求（需求驱动），而非“数据攒够”或“分类重构”。
- **P2 图边仍保持否决状态**：除非新的真实快照证明 entity fan-out 明显回升，且出现了必须靠有类型边才能回答的真实查询，否则不重启图边（与 scope 同为需求驱动解冻）。

---

*Last updated: 2026-06-26*
