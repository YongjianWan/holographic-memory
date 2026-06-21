# SESSION.md — 当前工作状态

> 这个文件回答："上次干到哪了、现在在搞什么、有什么临时坑"。
> 跟 TECH_DEBT 的区别：TECH_DEBT 记"欠的债"，SESSION 记"手头的活和临时记忆"。
> 每次开工读它，收工更新它。新项目开局：基本空白。

## 当前焦点

- `retain_document` 文档入口已落地（Patch 7）。
- 已把 `_LLMExtractor` prompt 重写（原子化约束写死、中文切分、好/坏示例），并在 `retain_document` 里加了段落/句子级 chunking（默认 6000 tokens，可配 `retain_max_chunk_tokens`）。
- DeepSeek key 已恢复，`batch_retain_eval._DeepSeekExtractor` 已固定 `temperature=0` 以消除多次运行的抖动。
- **云语料真实分类（366 facts / 4 文件）**：用加强后的分类器重跑，`unclear` 从 32.5% 降到 **0%**。最终分布：domain_fact 56.3%（206）、user_action 15.0%（55）、other_person_action 12.6%（46）、other_person_mentioned 11.5%（42）、meeting_meta 2.7%（10）、other 1.6%（6）、user_mentioned 0.3%（1）。任意 mention 万永健的 fact 共 56（15.3%）。说明之前的“大量 unclear”是启发式关键词太弱，不是事实不可分类。
- **entity 抽取修正**：在 `store.py` 的 `_extract_entities` 加了写时守卫：引号内候选 >20 字符或包含句中标点（，。！？；：等）视为 phrase/sentence，拒绝作为 entity。`pytest tests/` 全绿（54 passed）。在云语料上：总 entity 仅 5~6 个（中文事实几乎不带引号），修复前脏 entity 1 个（“请准备以下测试环境及资料，周二下午前完成演示”），修复后 0 个。
- **HRR / RRF 重大发现（云语料 366 facts）**：两两 HRR 相位余弦相似度 p50≈0、p95=0.036、p99≈0.052、**max=0.089**，≥0.80 的候选对为 0。这不只是「HRR 不能用于 P1-2 语义合并」——它顺带说明 §3 RRF 里的 HRR 那一路在真实语料上几乎在输出噪声。若 HRR 给出的排名是噪声，RRF 把它按 `1/(60+rank)` 加进共识分就是掺沙子。0.089 的天花板有多少来自 HRR 本质弱、有多少来自 entity 守卫后平均每 fact 只剩 ~1 个 entity，目前分不开；但无论哪种，**结论方向一致：别再调 HRR 阈值，P1-2 走 entity 共现 + LLM**。下一步必须在全量数据上实测三路 RRF vs 两路（FTS5+Jaccard）RRF，决定 HRR 那路是降权还是踢出。
- **domain_fact 比例修正为 56.3%**，不是之前凭直觉说的 80%+。加上 user_action 里“项目动作”那部分，往高了算也到不了 80。go/no-go 结论（去掉纯人型 mention 后库仍成立）不变，但余量比直觉薄，需要记着。
- **方法论红线**：key 失效时拿 fallback 语料（61 facts）标 HRR 阈值、entity 质量、分类分布是**假基准**——这已经是第三次证明 fallback 不能当基准。AGENTS.md 已加红线：fallback 只能验证脚本能跑通，不能出 any 数值结论；key 失效就等。
- **中文分词与 FTS5 trigram 迁移 (v5) (Patch 8)**: 确认 `.split()` 空格切分是导致中文 Jaccard/HRR 相似度大面积失效的元凶。引入了纯 Python 零依赖的 CJK 1-3 字符滑窗切词。重建了 `facts_fts` 虚拟表，使用 `tokenize="trigram"` 保证 FTS5 在中文下不瞎。A/B 测试表明 3-way RRF vs 2-way RRF 的中位数重合度恢复至 0.80，HRR 能够贡献有意义的独立信号。
- Q1 维持 12% 非原子率不动的结论仍有效（基于之前有效的 DeepSeek 运行）。
- Q2 category 分不分：用户 hub 不 dominant 的结论仍有效，但 bank 容量 warning（689 facts 落在单一 `project` bank）是真实问题，后续应靠真实 category 规则拆分，而不是继续把所有文档塞进 `project`。

## 进行中

> 开了头还没收尾的。每条标清楚卡在哪。

- <暂无>

## 待办（近期）

> 不是 roadmap，是这几天要碰的。长期规划进 ROADMAP.md。

- 输入侧：文档入口 + 存原文（§3.5）
- P1 GC 壳：惰性定时器 + 关机补漏
- P1-2/3：语义合并 + trust 衰减
- P1-4：跨话题串联（三条硬约束）
- P2：shared-entity 边 + CTE 多跳

## 已知陷阱（临时）

> 这次会话踩到的、还没沉淀进 TECH_DEBT 或 AGENTS 的坑。
> 验证清楚了就迁出去，别让这里变成债务垃圾场。

- `_resolve_entity` 曾用未转义的 SQLite `LIKE`，导致 `_`/`%` 被当通配符。已修复。若未来又出现 entity 匹配异常，先查这里。

## 决策记录（本项目关键拍板）

> 为什么这么设计、否决了什么方案。记"为什么"，不记"做了什么"。

- P1-1 entity 归一化未采用 HRR atom 相似度：HRR atom 对不同的字符串近似正交，对 "K2.7 四兄弟" 这类表面碎裂无区分能力；改用具确定性的编辑距离 + token 重叠。HRR 上下文向量聚类留作未来增强。
- entity canonical 选择用 specificity 主、链接数次：避免把 "K2.7" 碎裂全归并到更模糊的 "K2"。
- RRF 取代加权融合：三路原始分不可比，RRF 用排名位置融合更稳健。
- P0 写入探重只用 FTS5+Jaccard、不用 HRR：新 fact 尚无 entities，HRR 向量口径不同，且语义近重复不应占写热路径。
- P0 探重 SQL 禁 `retrieval_count` 与 trust 过滤：避免污染 GC 信号、漏掉低分重复。
- P0 merge 保留更 specific 的 wording：用 entity 数 + 数字/日期/版本命中数 / log(len) 本地打分，不掏 LLM。
- entity 归一化加 numeric signature 守门：纯字符串相似度分不清"碎裂"与"层级"；数字/版本/日期信号强且零成本，签名不同直接拒绝合并，宁可漏合不错合。

---

*Last updated: 2026-06-21*
