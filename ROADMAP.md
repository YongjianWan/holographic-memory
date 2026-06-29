# Roadmap

> 长期路线与已知限制。当前手头状态看 [SESSION.md](SESSION.md)；活跃债务看 [TECH_DEBT.md](TECH_DEBT.md)；已落地变更看 [CHANGELOG.md](CHANGELOG.md)；判断准则看 [docs/宪法.md](docs/宪法.md)。
>
> **这份文档的结构 = 项目的真实结构：一套「闸」。** 多数能力不是「待办」，而是被有意识地排进三个篮子——**现在能动（不 gated）**、**等闸再动（gated）**、**已焊死（否决/冻结）**。提新需求前先对照本文件：重了就停；真有新证据，再按对应解冻条件重开。

---

## 1. 当前阶段（一句话）

Holographic Memory 的底盘已经能跑（schema v11，155 个测试全绿），**当前不扩架构**。这一阶段只做三件事：

1. **收口**：把真实库的 provenance 使用面、干净度、检索边界做扎实——大部分已落地（见 §3 已完成）。
2. **推进唯一能动的下一格**：召回审计（见 §4）。这是当前唯一不依赖任何闸、能立刻往前推的事。
3. **守边界**：一堆能力被有意识地否决/冻结（见 §6）。守窄是 Holo 能被别的器官信任地调用的前提，不是局限。

> 母红线不变：**所有 LLM 走一次性 API，系统内无常驻进程，关机即文件、开机即用、无启动序列。** 任何"加后台服务/常驻模型/调度器"的想法先过这把尺子（见 [docs/宪法.md](docs/宪法.md) §0）。

---

## 2. 当前快照（只读报告口径，2026-06-29）

| 项 | 值 |
|---|---|
| schema 版本 | v11 |
| facts | `4347 total / 2195 active / 2152 soft-deleted` |
| active category | `project 2079 / personal 110 / user_pref 5 / general 1` |
| provenance 覆盖 | active 2195 中 `1162 known / 1033 legacy_unknown` |
| HRR bank | 已按 `category + source_doc_id + shard256` 分片；`project` 最大 bank 从 2083(SNR 0.701) 降到 256(SNR 2.0) |
| `semantic_equivalence_*`（lexicon 表） | **0 条**——空表，等召回审计手标种子 |
| 测试 | 155 passing |

> ⚠️ 旧的 `2200/2147/2078/2071/333/1051/1034` 等数字只作历史口径，**不能再驱动 schema 决策**。任何结论性审计先快照、再读快照，不在活 WAL 库上做。

两条主线现状：

- **A. 检索质量（RQ）**：默认 search 保持 FTS5 + Jaccard + HRR 三路 RRF；trust/recency 只做乘法 boost（±10% 限幅）；v11 本地等价词表用于 query expansion（当前空）。
- **B. 库卫生（P0/P1/P2）**：P0 写入探重、P1-1 entity 归一化、documents 表、soft-delete consolidation、GC/recency 壳已落地；P1-2/P1-4 规格在但 gated；P2 图边已被真实数据否决。

---

## 3. 已完成（落地存档，别重做）

- **RRF 三路融合**：默认 search = FTS5 + Jaccard + HRR，按名次融合 `Σ 1/(60+rank)`，不线性相加原始分。2026-06-29 固定查询 A/B（median top5 overlap 0.8、min 0.4、12/20 top1 改变）证明 HRR 实质影响排序，按用户拍板保留。
- **HRR bank 饱和解耦**：`_rebuild_bank` 写 `cat:{category}|doc:{doc}|shard:{nn}`，`probe()` 只 bundle 命中实体所属文档的 shard。不绑定 scope。
- **P0 写入探重**：`add_fact` 的 INSERT 之前 FTS5 粗筛 + Jaccard 精判（不用 HRR、不更新 retrieval_count、不过滤 trust）。
- **P1-1 entity 归一化**：编辑距离 + HRR 聚类 + 数字/版本签名守门（防 K2/K2.7 误并），保守阈值宁漏不误。
- **documents 表 + `text_hash` 去重 + `retain_document` 输入侧闭环**。
- **`fact_provenance`（v10）前向来源账本** + 读时 `provenance` 摘要；旧库不回填，空行读时投影 `legacy_unknown`。
- **soft-delete consolidation**：`merged_into` 软删除，9 条读路径过滤 `merged_into IS NULL`，禁止物理 DELETE。
- **惰性 GC + 实时 retrieval recency 壳**；并发基础补丁（BEGIN IMMEDIATE、GC busy skip、PASSIVE checkpoint）。
- **整库干净度第一轮人工裁决**：49 条候选 → 45 keep / 4 dirty / 0 pending，4 条 dirty 已 `merged_into=999999` 软删。
- **只读审计面**：provenance / dirty 候选 / HRR bank / RRF A/B / 召回审计 脚本均快照优先、不碰活库。
- **工具面提炼路由修复**：`fact_store(retain/consolidate)` 的 env-var LLM 注入（DeepSeek）已通；consolidate 无 LLM 报错不再误导承诺 OPENAI_API_KEY。

---

## 4. 现在能动（不 gated）

### 4.1 召回审计 —— THE 下一步（进行中）

**这是当前唯一不依赖任何闸、能立刻往前推一格的事。** 其余全 gated 排在它后面。

- **目的（一步喂三件事）**：(1) 量出 FTS5/Jaccard miss 里「黑话(自造词) vs 通用同义(词典词)」各占多少 → 回答「黑话有多少」+「word2vec 划不划算」；(2) 手标黑话同义对 → 填 `semantic_equivalence_*` 当 lexicon 初始种子，**不等 P1-2**；(3) 这批手标当 P1-2 解禁后的验证基准。
- **已落地**：`tests/scripts/run_recall_audit.py`（只读、快照优先、复用默认三路 RRF 无 `search()` 副作用），探针 `{query, expect}` 跑 HIT/MISS 报告；单测 `tests/test_recall_audit.py`；已对 live DB 冒烟跑通。
- **待办分工**：
  1. **手写真实探针集**（你为主）——query 故意用目标 fact 里没有的同义/黑话词；自造词只有你知道。喂 `--probes`。
  2. 跑审计出 miss 列表（脚本）。
  3. **人眼手标** miss 类型：黑话 / 通用同义 / absent（评估器在此边界系统性不稳，宪法明令人裁）。
  4. 黑话对填 lexicon 种子。
- **红线**：审计只读快照；lexicon 的**自动产出**仍 gated 继承 P1-2/P1-4，召回审计只解锁「手标种子」这一不依赖上游闸的子集；不因召回不足直接上 embedding。

### 4.2 Legacy 长 fact 粒度债（低风险后续，可不急）

15 条 doc=None 老 Hindsight 长 fact 已判 keep，但一条承载多个断言、粒度偏粗。**不是脏数据，不构成必须处理。** 若偿还，走「新增更细 fact + 旧粗 fact 软删除/合并」的可审计流程，**禁止物理 DELETE**，且需先验证新 fact 的召回/去重。

---

## 5. 等闸再动（Gated —— 闸没开一行代码都别写）

> 每项都明确 gated on 什么。**不许为了早点拿下游而把上游闸提前放开**——那是拿未验证机制喂新需求，典型 runs ahead。

| 能力 | gated on | 边界要点 |
|---|---|---|
| **P1-2 生产策略放开跑** | 真实库四阈值标定完成 | HRR 语义合并阈值不能照搬 Hindsight 的 0.97 cosine 或历史起点值，必须真实数据重标。收敛只留演化链，不合成"当前态"进 facts 表。 |
| **P1-4 跨话题串联** | Gate A 已 GO（2026-06-24），但仍需谨慎 | 只做 induction；不做 deduction/abduction（抽结构不抽人）；硬闸 `source_fact_ids >= 2`；质量不够就砍，不引入 embedding/自训模型/常驻进程。 |
| **同义/黑话 lexicon 自动产出** | 继承 P1-2/P1-4 | 是 P1-2/P1-4 那趟 LLM 的副产物，无新组件。派生表，非 fact，可丢可重建。**命名钉死：不是"边"/"共边"**（叫共边会误以为复活 P2）。手标种子是唯一不等闸的子集（见 §4.1）。 |
| **Summary 派生层（压缩树）** | Gate B + 前置 P1-2 | 双重 gating：scope 不成立则容器不存在；且脏 fact 上压不出干净 summary。解禁后顺序 P1-2 → summary 不可颠倒。详见 [docs/宪法.md](docs/宪法.md) Summary 层。 |
| **word2vec / GloVe / fastText 预训练词向量** | **准则层红线内核未拍板（Aiden 定）** + 召回审计数字 | 见 §7 决策闸速查。状态：**悬置——不否不做**。 |

---

## 6. 已焊死（否决 / 冻结 —— 防重提清单）

碰到下列想法先**停**。只有满足各自解冻条件、且有真实新证据时才重开。

- **P2 shared-entity 图边**：真实数据下 entity fan-out 低（380 active facts 上 0.811）、94% entity 只挂一条 fact、共享 fact pairs 少——建边没原料。**解冻条件**：出现"必须靠图才能答"的真实查询，**或 fan-out ≥ 1.5 / 共享对显著增加**。⚠️ **用数据触发，不用时间排期**（"大后期再做"是错的刻度）。注：lexicon 通了同义桥后，很多"看似需要图"的假性割裂会消失，fan-out 可能更难涨 → **先做 lexicon 反而推迟 P2，是好事**。
- **P2.5 LLM 有类型边**：默认永不做。主观边污染链式查询，且需 P2 先被真实需求解冻。
- **单值 scope 列**：判死。人的记忆不是规整 taxonomy。
- **多对多 scope + category/scope 解耦 + HRR bank 按 scope**：Gate B 首次审计 NO-GO（分类器尺子不可信 + 无真实域过滤需求）。多对多不是单值的"正确版"，仍 gated on 真实"非域过滤不可"的查询，不能与 provenance 混为一谈。
- **常驻 embedding 服务 / cross-encoder / 常驻 worker / 外部 cron**：违母红线（常驻、要启动序列）。注意刀刃是**常驻**，射程覆盖"常驻 embedding 用法"，**不自动覆盖"单次调用"的预训练词向量**（那条另议，见 §7）。
- **路 B 并发（一个 agent 持有库）**：会把持有者变成"必须先启动的记忆服务"，破"无启动序列"。只走路 A（多进程直开同一 .db，WAL 多读单写）。
- **reflect loop / consolidation worker**：不做常驻后台循环；周期任务只走任一活着实例的惰性 GC / on-session-end + SQLite 写锁抢占。

---

## 7. 决策闸状态速查

| 闸 | 状态 | 含义 |
|---|---|---|
| **Gate A**（P1-4 进场） | **GO（2026-06-24）** | 50 条人眼裁决 40 PASS / 10 FAIL，GO 率 80%。P1-4 可进场但仍按 §5 边界谨慎。 |
| **Gate B**（scope 可分性） | **NO-GO** | 分类器尺子不可信 + 无真实域过滤需求。scope 全家（单值/多对多/summary 容器）冻结。解冻 = 真实"非域过滤不可"的查询。 |
| **Control Group** | **锁定 27 条** | 量评估器测量噪声（~96.3% 一致）的物理固定基准。**禁止为追求 100% 一致而人工删样**（曾误删 ID 40 制造"成果幻觉"，已恢复）。 |
| **word2vec 红线内核** | **未拍板（Aiden 定）** | 否决它的两道墙（"要常驻服务""要重资源"）经讨论已倒——单次调用是关机即文件、无启动序列。**仅剩**："无语义召回"的真实内核是 (a) "不常驻" → 则单次调用合法可议；还是 (b) "语义判断不依赖外部训练沉淀、整条检索链可复现" → 则仍在门外。这条属准则层，没拍板前 word2vec 悬置。即便松开，仍 gated on 召回审计数字（黑话它补不了、词林已覆盖大半、引入不可复现召回）。 |

---

## 8. 已知限制（设计取舍，不是待修 bug）

- **无 embedding 语义召回**：母红线取舍。依赖 FTS5/Jaccard/grep-like 候选召回，把理解留给当下 LLM。缺不共词语义召回**不是技术债**；召回不足优先 query reformulation + 本地等价表 + 候选控制。
- **有效期 / validity 语义未建模**：`trust`/`recency` 衰减不等于"到期即死"。归后续 extractor profile / lifecycle，数据清洗闭环前不写 schema。带触发时间的东西（待办/日程）压根不进 Holo（见宪法 §6.1）。
- **entity 版本后缀混淆**：`GPT-4`/`GPT-4o` 这类后缀差异仍可能被数字签名弱化；真撞到再收紧守门。
- **跨 category 写入探重盲区**：`add_fact` 只同 category 内探重，跨 category 重复留给 P1 批 GC 全局收敛。
- **工具面提炼 pin 死 DeepSeek**：retain/consolidate 已能用 Hermes DeepSeek 路由或 `DEEPSEEK_API_KEY` 自动启用 LLM；故意不读 `OPENAI_API_KEY`（避免 silently 换 provider 致提取漂移）。只设 OpenAI key 不会启用提炼。
- **HRR 容量只报警不自动分拆**：超长 fact（>dim/4）只触发 warning，未自动分拆。
- **LLM client 按需构造（不缓存）**：低频写路径可接受；遇实测瓶颈前不缓存。

---

## 9. 推迟 / 砍了但记着

**推迟（到点再说）：**

- **提取器分型（extractor profile）**：技术/会议/聊天提取边界不同，但单一 prompt + 当前库干净度未稳，先分型是 runs ahead。
- **固定 eval 测试集**：20 真实查询 / 20 不该召回 / 20 脏 / 20 时间线 / 20 溯源是真需求，但必须等干净库作基准后再建。
- **恢复机制**：migration dry-run、rollback、WAL 损坏、半写入 retain 恢复——当前单用户低频未撞到，放到并发/独立包阶段一起做。
- **并发与独立包系统化**：等 provenance 使用面、干净度、检索边界稳定后再做。

**砍了但记着（过早优化，撞到再说）：**

- 上万到几十万 fact 全表扫优化——个人本地库远未到量级。
- category bank O(N²) 全量重建改增量——当前规模可接受。
- 自适应预算 / token 截断——未遇瓶颈，不提前复杂化。

---

*Last updated: 2026-06-29*
