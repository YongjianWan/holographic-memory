# 技术债与代码气味地图

> 只记录**当前活跃**的技术债。已修复的进 CHANGELOG，不留在这。
> 新项目开局：全部为 0。债务是干活过程中长出来的，不是抄来的。

---

## L1 Blocker（违反铁律，必须修）

> 当前无活跃的 L1 Blocker。

## L2 债务（阻塞演进或导致结果不可信）

### HRR search 路信号被 entity 成分稀释

`FactRetriever._hrr_ranking` 当前把 query 用 `bind(encode_text(query), ROLE_CONTENT)` 对齐到 fact 向量的 content 成分。但 fact 向量本身是 `content + entities` 的 bundle，query 只匹配 content 那份信号，其余 entity 成分对 query 来说是噪声。

- **当前影响**：HRR 那路名次质量偏弱。RRF 共识机制（FTS5 + Jaccard + HRR）仍在兜底，日常查询尚可用。
- **触发条件**：若实测 HRR 路在 RRF 中贡献接近随机（或 entity 碎裂严重到 HRR 路完全失效），需升级为更干净的解法——unbind 出 fact 的 content 成分再与 query 比。
- **为什么不现在改**：unbind 版需要每条 fact 显式维护自己的 role 结构，实现更复杂；而 RRF 的共识机制已让弱 HRR 信号不至于破坏整体排序。先观察实测数据。

### 实体归一化版本号后缀混淆风险

在 `store.py` 中，`_entity_names_match` 使用数字/版本签名守门。但对于带有不同字母后缀的版本（例如 "GPT-4" 与 "GPT-4o"），它们均提炼出数字签名 `4`。由于两者字符串相似度高，存在误合并为同一实体的风险。

- **当前影响**：有版本后缀细微差异的实体可能被误聚类。
- **偿还计划**：后续在真实数据测试中若发现该误合，需对 `_numeric_signature` 或相似度匹配增加后缀语义排除规则（"宁漏不误"）。

### Category 边界下的写入近重复检测盲区

在 `store.py` 的 `add_fact` 中，探重仅在同 category 内进行（避免 user_pref/project 互相污染）。若用户在不同 category 写入完全相同的 fact，写入探重无法拦截。

- **当前影响**：跨 category 的重复 fact 会漏进库中。
- **偿还计划**：该问题故意留给 P1 批 GC 进行全局收敛，暂不在写入热路径处理。

## 架构债务（不阻塞功能，但阻塞演进速度）

> 当前无活跃的架构债务。

## L3 品味问题（建议修，非债务）

### 工具面 fact_store 缺乏默认 LLM 提炼支持

在 `__init__.py` 中，工具调用的 `retain` 动作默认只能使用本地 `_LocalFallbackExtractor`（句子切分），因为核心包不打包 LLM SDK。这导致在 Agent 界面直接使用 `fact_store(action='retain')` 无法获得原子化的提炼。

- **当前影响**：只能通过 python API 显式注入 `model_call` 才能使用 `_LLMExtractor`。
- **优化计划**：应提供一种通过环境变量或插件配置注入 LLM API 客户端的方式，使 `fact_store` 工具默认可用 LLM。

### HRR 容量限制只报警不自动分拆

当单条 fact 长度超过 256（`dim / 4`）时，系统仅触发 `logging.warning` 警告，但事实仍会存入，导致其 HRR 向量信噪比低（变成噪声）。

- **优化计划**：在 P0 探重或 P1 批 GC 中，应加入自动对超长 fact 进行语义分拆的逻辑。

### HRR 编码分词口径不一致

`_warn_hrr_capacity` 在诊断时首选 `tiktoken` 统计 token 数，但 core 逻辑中的 `encode_text`（`holographic.py` 里）仍采用简单的 `whitespace split` 统计。

- **当前影响**：对 CJK（中文）文本，warning 的警告粒度较准，但实际 HRR 向量生成时仍面临字词混绑、信息容量被低估的情况。
- **优化计划**：在不引入重度依赖的前提下，使 HRR 生成的分词逻辑与 token 统计对齐。

---

> **当前活跃债务总览**：L1 **0** | L2 **3** | 架构 **0** | L3 **3** | 合计 **6**

---

## 文件级雷区地图

> 记"改动风险高、影响面大"的文件。空表起步，随项目长。

| 文件 | 行数 | 风险 | 状态 |
| ---- | ---- | ---- | ---- |
| — | — | — | 暂无 |

---

## 测试覆盖缺口

> 列没有专属测试覆盖的核心模块。理想状态：空。

> 暂无记录。

---

## 规格参考与边界行为（非债务，供 Agent 查阅）

> 已验证的边界安全行为、Exit Code 契约、路径处理矩阵等。
> 这部分是"已知正确行为"的存档，帮 agent 别重复踩已验证过的地方。
> 随项目积累，开局留空。

---

*Last updated: 2026-06-21（活跃债务：L1=0 / L2=3 / 架构=0 / L3=3）*
