# SESSION.md — 当前工作状态

> 这个文件回答："上次干到哪了、现在在搞什么、有什么临时坑"。
> 跟 TECH_DEBT 的区别：TECH_DEBT 记"欠的债"，SESSION 记"手头的活和临时记忆"。
> 每次开工读它，收工更新它。新项目开局：基本空白。

## 当前焦点

已按用户要求回头加固 entity 归一化：加了 numeric/date/version signature 守门，防止"K2"和"K2.7"这类层级关系被误当碎裂合并。测试已补。下一步回到 `holo-改造方案.md` §8，进入 **输入侧：文档入口 + 存原文**（§3.5），或先搭 **P1 GC 惰性定时器壳**。

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

*Last updated: 2026-06-20*
