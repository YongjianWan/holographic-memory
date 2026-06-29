# 技术债与代码气味地图

> 只记录**当前活跃**的技术债。已修复的进 CHANGELOG，不留在这。
> 新项目开局：全部为 0。债务是干活过程中长出来的，不是抄来的。

---

## L1 Blocker（违反铁律，必须修）

> 当前无活跃的 L1 Blocker。

## L2 债务（阻塞演进或导致结果不可信）

### 旧库 provenance 无法回填

v10 已经引入 `fact_provenance`，新发生的 document retain / merge 会保留
多来源账本。旧库不能回填：当前历史 soft-deleted facts 的 `merged_into`
已经统一指向 `999999` 审计 marker，真实 merge target 和贡献链不可恢复。

- **当前影响**：旧 active facts 可能没有 provenance 行；查询侧必须把这种
  空行状态读时投影为 `legacy_unknown`，不能存占位或把 `source_doc_id` 当完整来源。
- **偿还计划**：不修旧账，只保护新账。后续查询/报告层统一优先读
  `fact_provenance`，无行时显式返回 legacy unknown。当前已补
  `tests/scripts/run_provenance_audit.py` 只读报告面，用来持续核对 known /
  legacy_unknown 覆盖率和 merge 多来源样本。

### LLM extraction meta 混入 facts

第二批真实数据中，`工作心理问题.txt` 有少量模型自言自语、规则复述和分析
过程被当作 fact 写入。当前稳定快照的 49 条 meta/dirty review candidates
已完成第一轮人眼裁决：45 keep / 4 dirty / 0 pending；4 条 dirty 已通过
`merged_into=999999` 软删除，未物理 DELETE。

- **当前影响**：已确认的 dirty 候选已处理；剩余风险转为后续新导入时的提取边界回归。
- **偿还计划**：
  - **已完成治标**：当前快照候选已复核，确认 dirty 的 fact 已通过 `merged_into` 软删除，不物理 DELETE。
  - **根治方案**：继续收紧提取 Prompt 的事实/废话边界，强制拒收思考过程、自言自语、元指令陈述、聊天状态和纯劝慰隐喻。

### Legacy Hindsight 长 fact 粒度偏粗

当前 dirty review 剩余的 15 条 doc=None 老 Hindsight fact 已判 `keep`，因为它们是历史架构、配置、迁移和工具事实，不属于对话噪音、模型自言自语、触发时间待办或心理动机推断。但它们多由一条 fact 承载多个断言，原子粒度偏粗。

- **当前影响**：检索可用但解释和合并粒度不理想；不构成必须软删除的脏数据。
- **偿还计划**：后续若要偿还，先新增更细粒度 fact 并验证召回/去重，再把旧粗 fact 通过 `merged_into` 软删除或合并，禁止物理 DELETE。



### 实体归一化版本号后缀混淆风险

在 `store.py` 中，`_entity_names_match` 使用数字/版本签名守门。但对于带有不同字母后缀的版本（例如 "GPT-4" 与 "GPT-4o"），它们均提炼出数字签名 `4`。由于两者字符串相似度高，存在误合并为同一实体的风险。

- **当前影响**：有版本后缀细微差异的实体可能被误聚类。
- **偿还计划**：后续在真实数据测试中若发现该误合，需对 `_numeric_signature` 或相似度匹配增加后缀语义排除规则（"宁漏不误"）。

### Category 边界下的写入近重复检测盲区

在 `store.py` 的 `add_fact` 中，探重仅在同 category 内进行（避免 user_pref/project 互相污染）。若用户在不同 category 写入完全相同的 fact，写入探重无法拦截。

- **当前影响**：跨 category 的重复 fact 会漏进库中。
- **偿还计划**：该问题故意留给 P1 批 GC 进行全局收敛，暂不在写入热路径处理。

### `recency_floor` 双重语义耦合

在 `retrieval.py` 和 `memory_gc.py` 中，`recency_floor` 常量（当前为 0.1）背负了两个不同的语义：
1. **GC 衰减层**：作为事实新鲜度（freshness）衰减的物理地板（防乘法链中 trust 被乘以 0 归零）。
2. **检索检索增强映射基准**：作为 retrieval boost 将 `freshness` 线性归一化拉伸到 `[0.9, 1.0]` 的低位锚点（`(freshness - floor) / (1 - floor)`）。

- **当前影响**：两个语义的旋钮被强行焊在了同一个常量上。未来如果有人为了调慢/加速 GC 衰减速率而改动 `recency_floor`（例如设为 0.05），会意外破坏 retrieval 端的线性拉伸比率，产生意料之外的检索排序波动。
- **偿还计划**：将两者的配置/属性解耦，GC 层和 Retrieval 层应各自持有独立的 floor 配置，允许其独立调参。目前因为 0.1 凑巧在两边都适用，暂不修改。


### 评估器在主客观边界上的判定抖动与过抽率（Doc 6 & Doc 8 审计结论）

在对 Doc 6 和 Doc 8 的审计中，评估器表现出约 96.3% 的一致性（26/27 匹配），边缘部分的抖动是通用模型判定“某事实是否有召回价值”时的天花板表现。同时，由于 Prompt 精度限制，Doc 8 中存在约 26.6% 的过抽率（非真实数据污染，而是 Prompt 提取粒度偏粗导致的过度提取）。
- **当前影响**：评估结果包含约 ±3.7% 的测量噪声；无法通过微调 prompt 实现 100% 绝对一致。
- **基准漂移根因（27 变 26）**：上一轮评估中，Control Group 从 27 条缩减为 26 条，并非由于数据库物理丢失，而是因为 AI 助手在运行 `run_evaluator_stability.py` 时发现 **Fact ID 40**（`"算法跑分不限五个，可能一天出来十个或二十个。"`）在两次审计中出现判定分歧（Audit 1: PASS, Audit 2: FAIL），随后**手动在 `_control_fact_ids.txt` 中删除了 ID 40**，以用“缩短尺子”的方式人工制造 100% 的一致性。这本身构成了基准漂移。
- **偿还计划**：
  1. 承认并量化该抖动与过抽率，不再追求消除边缘抖动。
  2. 控制组必须保持绝对物理固定（包含 ID 40，恢复为 27 条），只作为量化“评估器测量噪声”的基准，严禁为了追求“100% 一致性指标”而人工筛选、剔除抖动样本，从而污染基准。



## 架构债务（不阻塞功能，但阻塞演进速度）

### Scope 可分性尚未通过真实数据门

Gate B 首次审计已经判定为 NO-GO：当前分类器尺子不可信，且尚无“必须依靠域过滤才能答得了”的真实查询需求。把 scope 结论焊入 schema，会制造一个长期不可靠的过滤条件。

- **当前影响**：`project` category 仍可能过宽，但不能用想当然的单值 scope 修复。
- **偿还计划**：scope 保持 veto / 待证；只有真实使用中出现非域过滤不可的查询时才重新评估。多对多 scope 不是单值 scope 的自动正确版，也不能与 provenance 混为一谈。

## L3 品味问题（建议修，非债务）

### 工具面 fact_store 提炼故意 pin 死 DeepSeek，无 OPENAI fallback

在 `__init__.py` 中，工具调用的 `retain` / `consolidate` 动作通过 `_resolve_model_call()` 解析 LLM：先走 Hermes 的 `agent.auxiliary_client.call_llm`（provider=deepseek），standalone 时 fallback 到 `DEEPSEEK_API_KEY` 环境变量。env-var 注入已可用（旧债「只能 python API 注入」已过期，2026-06-29 核对源码确认）。当前**残留**是提取/合并被**故意 pin 死 DeepSeek**：standalone 分支不读 `OPENAI_API_KEY`，以免 silently 换 provider/模型导致提取粒度漂移。

- **当前影响**：只设 `OPENAI_API_KEY` 不会启用 retain/consolidate 的 LLM；必须用 DeepSeek 路径。这是设计取舍，不是 bug。
- **已修**：consolidate 无 LLM 时的报错原本谎称「DEEPSEEK_API_KEY or OPENAI_API_KEY not found」，但 `OPENAI_API_KEY` 从不被读取，会把用户引向死路；已改为只提 DeepSeek（回归测试 `tests/test_model_routing.py::test_consolidate_without_llm_reports_deepseek_only`）。
- **偿还条件**：若未来确有用 OpenAI 兼容端点做提取的真实需求，再在 `_resolve_model_call` 显式加分支并同步报错文案；当前无需求不加。

### HRR 容量限制只报警不自动分拆

当单条 fact 长度超过 256（`dim / 4`）时，系统仅触发 `logging.warning` 警告，但事实仍会存入，导致其 HRR 向量信噪比低（变成噪声）。

- **优化计划**：在 P0 探重或 P1 批 GC 中，应加入自动对超长 fact 进行语义分拆的逻辑。

### HRR 默认 search 弱信号边界

2026-06-29 的固定查询 A/B 显示，HRR 会显著重排 FTS5/Jaccard 的结果。用户已拍板：在没有 embedding 语义召回的前提下，HRR 是唯一可行的本地弱语义/结构信号，必须保留在默认 search 的 RRF 融合里。

- **当前影响**：默认 search 使用 FTS5 + Jaccard + HRR 三路 RRF；HRR 仍然只是弱结构信号，不等价于 embedding 语义相似。
- **守住边界**：不要把 HRR 说成真正的词义等价或 embedding 替代品。词语等价走 v11 `semantic_equivalence_*` 本地表扩展 query；是否引入任何外部向量/模型服务仍受无常驻红线约束。

### LLM client 按需构造（不缓存）

`_resolve_model_call` 在每次 `retain` / `consolidate` 操作时重新读取环境变量并实例化 OpenAI client，而非在 `initialize()` 时缓存一个单例。

- **当前影响**：每次写操作多花几毫秒初始化 client；但 retain / consolidate 是低频写路径，开销可忽略。
- **不动的理由**：无状态构造符合"关机即文件、无常驻"的设计洁癖；key 在运行时失效时自然降级而无需缓存失效逻辑；缓存 client 反而引入生命周期管理（绑到 shutdown、失效重建）。**遇到实测瓶颈前不值得处理。**
- **偿还条件**：仅在 retain 明显成为交互瓶颈（例如日均 retain 操作 >50 次、用户可感知延迟）时才考虑。

---

> **当前活跃债务总览**：L1 **0** | L2 **7** | 架构 **1** | L3 **4** | 合计 **12**

---

## 文件级雷区地图

> 记"改动风险高、影响面大"的文件。空表起步，随项目长。

| 文件 | 行数 | 风险 | 状态 |
| ---- | ---- | ---- | ---- |
| — | — | — | 暂无 |

---

## 测试覆盖缺口

> 列没有专属测试覆盖的核心模块。理想状态：空。

### GC 锁竞争的历史 RED 记录不可追溯

当前 GC busy 路径已有双连接、同文件数据库的锁竞争回归测试，覆盖零
`gc_log` 写入和解锁后补跑。现有未提交工作树无法证明该测试在实现前曾被
单独运行并观察到 RED。

- **当前影响**：行为本身有回归覆盖，但不能把历史 TDD 顺序当成有记录事实。
- **偿还计划**：后续并发补丁应拆成独立提交或保留 CI RED/green 证据；本项
  不要求重写已验证实现。

### Scope gate 当前 NO-GO 结论需要守住

Gate B 的 NO-GO 是当前 schema 边界，不是“数据还不够所以等等”的普通待办。后续 agent 容易把 category 过宽、HRR bank 饱和和 scope schema 绑成一个包。

- **当前影响**：若误把 scope 当作 HRR 饱和的默认解，会提前写入不可逆 schema。
- **偿还计划**：任何 scope 设计必须先给出真实查询需求；没有需求只做文档记录，不做 migration。

> 暂无记录。

---

## 规格参考与边界行为（非债务，供 Agent 查阅）

> 已验证的边界安全行为、Exit Code 契约、路径处理矩阵等。
> 这部分是"已知正确行为"的存档，帮 agent 别重复踩已验证过的地方。
> 随项目积累，开局留空。

---

*Last updated: 2026-06-29（活跃债务：L1=0 / L2=7 / 架构=1 / L3=4）*
