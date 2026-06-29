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
- **稳定快照 ledger（2026-06-27 18:46:42）**：
  - 项目 canonical docs 已导入 live DB：11 个文档，新增 active facts 1166，新增 documents 11。
  - 写入前备份：`reports/live_backups/memory_store_before_project_docs_20260627_175648.db`。
  - dirty soft-delete 写入前备份：`reports/live_backups/memory_store_before_dirty_apply_20260627_184630.db`。
  - `facts_total=4347`，`facts_active=2195`，`facts_soft_deleted=2152`，`documents_total=20`，schema v11。
  - `integrity_check=ok`，foreign key violations 为 0。
  - **Active 数量对平对账单（1051 -> 1034 -> 2200 -> 2199）**：
    - `1034 = 1051 + 6 (Doc 6) - 22 (Doc 8) - 1 (Doc None)`
    - `2200 = 1034 + 1166 (project canonical docs)`
    - `2199 = 2200 - 1 (dirty Fact 1000145 soft-delete)`
    - **Doc 6 (招商会议.txt) 净增加 6**：新增 248 条，软删除（合并）243 条，复活 1 条（248 - 243 + 1 = +6）
    - **Doc 8 (招商2.txt) 净减少 22**：新增 192 条，软删除（合并）223 条，复活 9 条（192 - 223 + 9 = -22）
    - **Doc None (系统内置/无源事实) 净减少 1**：软删除 1 条，新增 0 条（-1）
  - active category：project 2083，personal 110，user_pref 5，general 1。
  - 所有 2148 条 soft-deleted facts 当前都指向 `999999 System audit soft-delete marker`，说明当前库已被清理/重抽样改写，不能沿用旧的 2078 active 口径。
  - `project` bank 当前 fact_count 2083，按 1024 维估算 SNR 约 0.701，HRR 饱和已是明确下一刀证据。
- **整库 dirty/meta 候选报告（2026-06-27 18:46:43）**：
  - 只读脚本：`tests/scripts/run_dirty_fact_candidates.py`。
  - 输出：`reports/dirty_fact_candidates.md` / `.json`；源库经 SQLite backup API 快照后读取，未修改 live DB。
  - 已通过 `tests/scripts/run_apply_dirty_fact_verdicts.py --apply-likely-dirty --yes` 软删除 Fact `1000145`（心理动机/逃避模式推断），写入 `merged_into=999999`，未物理 DELETE。
  - apply 记录：`reports/dirty_fact_apply_20260627_184631.md` / `.json`。
  - 写后扫描 active facts 2199 条，候选 49 条，全部为 `review`；当前无 `likely_dirty`。
- **HRR bank 解耦只读审计（2026-06-27 19:01:26）**：
  - 只读脚本：`tests/scripts/run_hrr_bank_partition_audit.py`。
  - 输出：`reports/hrr_bank_partition_audit.md` / `.json`；源库经 SQLite backup API 快照后读取，未修改 live DB。
  - 当前 `category` bank：`cat:project` 2083 facts，SNR 0.701，明确超载。
  - `category_source_doc`：23 个虚拟 bank，最大 `cat:project|doc:6` 为 264 facts，SNR 1.969，仍略超 256。
  - `category_document_family`：最大 895 facts，SNR 1.07，不足以解饱和。
  - `category_source_doc_shard256`：24 个虚拟 bank，最大 256 facts，SNR 2.0，`over_capacity=0`；这是当前证据支持的下一步实现候选，且不引入 scope schema。
- **HRR bank 解耦实施 + 落地（2026-06-27 19:30:11）**：
  - 代码：`store._rebuild_bank` 改为写 `cat:{category}|doc:{doc}|shard:{nn}` 派生 bank（按 category 分组、组内按 source_doc_id 再分组、组内按 fact_id 排序、每 256 条一个 shard），不再写单一扁平 `cat:{category}` bank；`store._bank_names_for_docs` 新增按 doc 查 shard bank 名。
  - `retrieval.probe()` 改为先查实体所属 fact 的 source_doc_id，只拉这些 doc 对应的 shard bank 并 bundle 后再 unbind，不再对整个 category 的超位 bank 做 unbind。
  - 新增单测 `tests/test_retrieval_rrf.py::TestHRRBankSharding`（bank 命名分片化 + 跨文档 probe 仍能找到实体）。全量 `pytest`：142 passed。
  - 落地脚本：`tests/scripts/run_hrr_bank_resharding.py --yes`，backup-first（`reports/live_backups/memory_store_before_hrr_resharding_20260627_193011.db`），对 live DB 按当前活跃 category 重跑 `_rebuild_bank`。
  - 结果：`reports/hrr_bank_resharding.md`/`.json`；`project` 最大 bank fact_count 由 2083(SNR 0.701) 降到 256(SNR 2.0)，bank 行数 1→24，`banks_over_capacity` 由 1 降到 0。`integrity_check=ok`，`facts_active` 不变(2199)，未触碰 `facts` 表任何行。
- **宪法 §6.3 补 §6.4(Aiden 拍板)**：项目自身元文档（宪法.md/AGENTS.md/CHANGELOG.md/ROADMAP.md/SESSION.md/TECH_DEBT.md 等）经标准原子提炼管线写入的 fact 不算违反"changelog/操作指令不进 Holo"——该判据原意是禁止存逐字原文，不是禁止对这类文档做和其他文档一样的原子化提炼。`docs/宪法.md` 已补 §6.4 把这条澄清焊死。
- **49 条 review 候选人工裁决·第一批（2026-06-27 21:10:46，Aiden 拍板）**：
  - 49 条里 34 条是项目元文档导入产生的（doc 15/16/18/19/20/21/22/23/25），15 条是 doc=None 的老 Hindsight 时代长 fact（`long_atomicity_check:>240`，跟本次工作无关，留作独立历史债，verdict 仍空）。
  - 34 条项目元文档候选中，按 §6.4 大多数应判 keep；但其中 4 条不是"该不该进 Holo"的问题，是内容本身已经站不住：
    - `1001480`/`1001455`：当天分片改动前写的"当前 fact_count 933/SNR 1.048"快照断言，已被 19:30 的 resharding 证伪（现状 256/2.0），不是"无触发时间的客观断言"。
    - `1001935`/`1001953`：句式是"X 改变后必须重跑 Gate A/B"，按 §6.1 判据其实是带触发条件的待办，不该是 fact；且引用的 1051 快照早已过期（现 2199）。
  - 已用 `tests/scripts/run_apply_dirty_fact_verdicts.py --yes`（backup-first，`reports/live_backups/memory_store_before_dirty_apply_20260627_211046.db`）软删除这 4 条，写入 `merged_into=999999`，未物理 DELETE。`active_before=2199 → active_after=2195`。
  - 其余 30 条项目元文档候选 + 这 4 条的 verdict 已写回 `reports/dirty_fact_candidates.json`/`.md`（30 条 `keep`，4 条 `dirty`）；15 条 doc=None 候选 verdict 仍留空，等独立轮次人工过。
  - apply 记录：`reports/dirty_fact_apply_20260627_211046.md` / `.json`。
- **49 条 review 候选人工裁决·第二批（2026-06-29）**：
  - 剩余 15 条 doc=None 老 Hindsight 长 fact 已过人眼，全部判 `keep`：它们是历史架构/配置/迁移事实，问题是原子粒度偏粗，不是对话噪音、模型自言自语、触发时间待办或心理动机推断。
  - `reports/dirty_fact_candidates.json`/`.md` 已更新为 `45 keep / 4 dirty / 0 pending`。
  - 本批没有新增 dirty fact，未运行 soft-delete 写库脚本，真实 DB active 数不因此变化。
- **Source Provenance 报告面细化（2026-06-29）**：
  - 新增只读脚本 `tests/scripts/run_provenance_audit.py`，通过 SQLite backup API 生成快照后统计 provenance 覆盖，不写 facts/schema/documents/provenance。
  - 输出：`reports/provenance_audit.md` / `.json`；源库快照为 `reports/snapshots/memory_store_provenance_audit_20260629_154307.db`。
  - 结果：`facts_active=2195`，`active_known=1162`（52.94%），`active_legacy_unknown=1033`（47.06%），`provenance_rows_total=1169`，`provenance_rows_for_active=1165`。
  - 多来源 active facts 仅 2 条，`source_doc_id` 与 provenance doc mismatch 样本也为 2 条，均来自 merge 后 survivor 保留单值 `source_doc_id`、而 `fact_provenance` 记录额外来源；这证明报告面能展示“单值归属不是完整 provenance”的边界。
- **RQ：默认 search 保持三路 RRF + v11 等价词表（2026-06-29）**：
  - 新增只读 A/B 脚本 `tests/scripts/run_rrf_ab_audit.py`，先快照 live DB，再比较 FTS5+Jaccard+HRR 三路默认 ranking 与 FTS5+Jaccard 两路 ablation；脚本不调用 `search()`，不污染 `retrieval_count` / `last_accessed_at`。
  - 输出：`reports/rrf_ab_audit.md` / `.json`；结果为 `median_top5_overlap=0.8`，`min_top5_overlap=0.4`，20 条固定查询中 12 条 top1 改变，`hrr_only_top3_query_count=0`。
  - 结论：HRR 对排序有实质影响，且在无 embedding/无语义召回前提下是唯一可行的本地弱语义/结构信号；`FactRetriever.search()` 保持 FTS5+Jaccard+HRR 三路 RRF。
  - 新增 migration v11 `semantic_equivalence_groups` / `semantic_equivalence_terms`，用于导入训练好的词语等价/同义词表；search 会用这张本地 SQLite 表做 query expansion。该表不是 embedding 服务，不引入常驻依赖。

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
- [x] 导入项目 canonical docs：`tests/scripts/run_retain_project_docs.py --yes` 成功写入 live DB；11 个文档全部 `ok`，无 extraction errors。
- [x] 生成整库 dirty/meta 候选人工确认报告；当前只读口径为 50 条候选（1 条 likely_dirty / 49 条 review）。
- [x] 软删除唯一明确 dirty fact `1000145`；写后只读口径为 49 条 review 候选，无 likely_dirty。
- [x] 完成 HRR bank 解耦只读审计；`source_doc_id + shard256` 可把最大 bank 从 2083 压到 256，清掉容量超载。
- [x] 实施 HRR bank 解耦：`_rebuild_bank` 改写为分片 bank，`probe()` 改为按文档定位 shard 再 bundle/unbind；live DB 已用 backup-first 脚本重建，`project` 最大 bank SNR 由 0.701 升到 2.0。
- [x] 宪法 §6.3 补 §6.4：项目自身元文档经原子提炼后可入库，不算违反 changelog/操作指令排除条款。
- [x] 完成当前 49 条 dirty/meta review 候选人工裁决：45 keep / 4 dirty / 0 pending；4 条 dirty 已在第一批软删除，第二批无新增写库动作。
- [x] 补齐 Source Provenance 只读报告面：当前 active facts 中 1162 known / 1033 legacy_unknown，报告明确展示多文档 merge 来源而不改 schema。
- [x] 完成默认 search HRR 去留裁决：基于固定查询 A/B 和用户拍板，`search()` 保持 FTS5+Jaccard+HRR 三路 RRF；v11 增加本地 semantic equivalence 表补词语等价。

## 下一步顺序

1. **Legacy 长 fact 粒度债（低风险后续）**：15 条 doc=None 老 Hindsight 长 fact 已判 keep，但粒度偏粗；后续若要偿还，应在新 fact 写入验证充分后做“新增更细事实 + 旧粗 fact 软删除/合并”的可审计流程，不物理 DELETE。
2. **Scope 状态：veto / 待证（与 P2 同构，不可逆闸）**：
   - 彻底冻结 Scope 拆分的开发决策。
   - **解冻条件**：在真实使用中撞到“必须依靠域过滤才能答得了”的真实查询（需求驱动），而非“数据攒够”或“分类标签重构”等伪数据驱动。在此之前，不编写任何 Scope 相关的 schema 迁移或处理代码。

## 已知陷阱（临时）

- `project` category 已分片（见上方 HRR bank 解耦），不再是单一扁平 bank；2026-06-27 之前记录的"fact_count 2083/SNR 0.701"是分片前的旧状态，已被本节其余条目的新记录取代。
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

*Last updated: 2026-06-27*
