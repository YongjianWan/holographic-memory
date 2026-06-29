# SESSION.md — 当前工作状态

> 这个文件回答："上次干到哪了、现在在搞什么、有什么临时坑"。
> 跟 TECH_DEBT 的区别：TECH_DEBT 记"欠的债"，SESSION 记"手头的活和临时记忆"。
> 每次开工读它，收工更新它。

## 当前焦点

本轮（2026-06-27 ~ 2026-06-29）核心工作已全部完成并归档到 [CHANGELOG.md](./CHANGELOG.md) `[Unreleased]`：

- v10/v11 schema 落地：`fact_provenance`、`last_accessed_at`、`semantic_equivalence_*`。
- HRR bank 分片解耦：`source_doc_id + shard256`，最大 bank 从 2083 降到 256，SNR 0.701 → 2.0。
- 49 条 dirty/meta 候选人工裁决完成：45 keep / 4 dirty / 0 pending。
- Source provenance 只读报告面补齐。
- 默认 search 保留 FTS5+Jaccard+HRR 三路 RRF（用户拍板）。
- 文档治理：新增根 `README.md`，拆分 `CHANGELOG.md [Unreleased]`，补充决策记录。

2026-06-29 增量（账本对齐 + 小修，未提交）：

- AGENTS.md §阅读顺序 末尾加「提新需求前先过 ROADMAP 防重提清单」指针，降低新 AI 重提被 veto 方向的成本。
- 修 `fact_store(action='consolidate')` 无 LLM 时的误导报错：`_resolve_model_call` 故意 pin 死 DeepSeek、从不读 `OPENAI_API_KEY`，旧报错却谎称两者皆可，会把用户引向死路；改为只提 DeepSeek。回归测试 `tests/test_model_routing.py::test_consolidate_without_llm_reports_deepseek_only`（RED→GREEN）。
- 账本对齐：核对源码后确认 retain/consolidate 的 env-var LLM 注入早已实现，TECH_DEBT L3 与 ROADMAP「工具面 retain 默认无 LLM」描述过期，已改写为「故意 pin DeepSeek、无 OPENAI fallback」的真实残留。
- 调查结论（未动）：收紧提取过滤器非干净增量——4 条 dirty 与人工 keep 的「380 active facts」结构同形，正则分不开，硬加违「宁漏不误」；且泄漏是 legacy 已软删、prompt 已覆盖该类。

当前稳定快照：`facts_active=2195`，`facts_total=4347`，`documents_total=20`，schema v11。

## 下一步顺序

0. **召回审计（当前唯一不 gated、能立刻往前推一格的事）**：2026-06-29 决议补丁定性。一步同时喂三件事——(1) 量出 miss 里“黑话 vs 通用同义”各占多少 → 回答“黑话有多少”+“word2vec 划不划算”；(2) 手标几十条黑话同义对 → 填 v11 `semantic_equivalence_*`（当前 0 条）当 lexicon 初始种子，**不等 P1-2**；(3) 这批手标当 P1-2 解禁后的验证基准。其余（lexicon 产出、word2vec 议不议）全 gated 排在它后面。⚠️ 按陷阱：审计走真实库**快照**，不在活 WAL 上做结论。
1. **Legacy 长 fact 粒度债（低风险后续）**：15 条 doc=None 老 Hindsight 长 fact 已判 keep，但粒度偏粗；后续若要偿还，应在新 fact 写入验证充分后做“新增更细事实 + 旧粗 fact 软删除/合并”的可审计流程，不物理 DELETE。
2. **Scope 状态：veto / 待证（与 P2 同构，不可逆闸）**：
   - 彻底冻结 Scope 拆分的开发决策。
   - **解冻条件**：在真实使用中撞到“必须依靠域过滤才能答得了”的真实查询（需求驱动），而非“数据攒够”或“分类标签重构”等伪数据驱动。在此之前，不编写任何 Scope 相关的 schema 迁移或处理代码。

## 已知陷阱（临时）

- `project` category 已分片，不再是单一扁平 bank；2026-06-27 之前记录的 "fact_count 2083/SNR 0.701" 是分片前的旧状态。
- **评估器判定边缘指令/主客观事实系统性不稳**：例如 ID 40（"算法跑分不限五个..."）与 ID 1000023（"汇报 PPT 不能展示零"）等边缘指令句，评估器极易抖动。在 Gate A 的 50 条肉眼 Go/No-Go 判定中，决不能迷信评估器单次结果，必须依靠人眼进行最终裁决。
- 当前 reports 目录包含多轮脚本产物，不能默认 `reports/scope_gate_audit.md` 就是最新全库报告。
- 不要直接在活 WAL 库上做结论性审计；先快照，再读快照。
- 事实/对话噪音仍是主风险：提取器要拒收问安、睡觉提醒、聊天节奏、临时隐喻和心理归因，只保留长期可召回的事实、规约、客观结论和明确建议。

## 决策记录

完整决策记录已迁移到 [CHANGELOG.md](./CHANGELOG.md) `[Unreleased]` §Decision records。本节仅保留最近需要反复查看的速查：

- **Gate A**：2026-06-24 人手复核 50 条，40 PASS / 10 FAIL，GO 率 80%，正式 GO。
- **Gate B**：scope 首次审计 NO-GO，转入 **veto / 待证** 状态；解冻条件为真实域过滤需求出现。
- **P2 图边**：继续否决，除非真实快照证明 entity fan-out 明显回升且出现必须靠图才能回答的真实查询。
- **Control Group**：恢复并锁定为 27 条事实，禁止人工调整基准。

---

*Last updated: 2026-06-29*
