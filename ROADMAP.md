# Roadmap

> 长期路线与已知限制。当前手头状态看 [SESSION.md](SESSION.md)；活跃债务看 [TECH_DEBT.md](TECH_DEBT.md)；已经落地的变更进 [CHANGELOG.md](CHANGELOG.md)。

---

## 当前阶段

Holographic Memory 的底盘已经能跑，当前阶段不是继续扩架构，而是把真实库的 provenance、干净度和检索边界做扎实。

两条主线仍然成立：

- **A. 检索质量（RQ）**：RRF 已落地；默认 search 是否保留 HRR 路仍需基于真实查询继续判断。
- **B. 库卫生（P0/P1）**：P0 写入探重、P1-1 entity 归一化、documents 表、soft-delete consolidation、GC/recency 壳已落地；P2 图边已被真实数据否决。

当前稳定快照以 [SESSION.md](SESSION.md) 为准：`3181 total / 1034 active / 2147 soft-deleted / schema v9`，active category 为 `project 917 / personal 111 / user_pref 5 / general 1`。旧的 `2078/2071/333/1051` 等数字只作为历史口径，不能再驱动 schema 决策。

---

## 优先级队列

按「当前收益 / 不可逆风险」排序：

1. **Source provenance 继承机制**
   - `source_doc_id` 是单值归属，不是完整 provenance；发生 merge 后不能还原所有贡献来源。
   - 下一步编码任务是引入事实与源文档的多对多 provenance 记录，例如 `fact_provenance`，并确保 merge 时继承来源。
   - 这不是 scope Gate B 的附属品，而是文档 retain 和合并路径的可审计性基础。

2. **整库干净度人工确认**
   - 基于当前稳定快照复核 meta/dirty candidates，确认哪些应通过 `merged_into` 软删除或标记。
   - 评估器只做辅助，边缘事实以人眼判定为准；Control Group 不再为了追求 100% 一致性而调整。

3. **HRR bank 饱和解耦**
   - `project` bank 仍过宽，当前 fact_count 933，1024 维估算 SNR 约 1.048。
   - 解法不默认绑定 scope；候选包括按 `source_doc_id`/文档组做物理切分、category 内轻量分桶，或承认 HRR 只保留在 probe/reason 实验路径。

4. **Scope 继续 veto / 待证**
   - Gate B 首次审计为 NO-GO：分类器尺子不可信，且没有真实“非域过滤不可”的检索需求。
   - 不新增 `facts.scope`、`fact_scopes` 或 scope-driven bank schema。
   - 解冻条件是出现真实使用中必须依靠域过滤才能回答的查询，而不是“数据更多”或“分类标签重构”。

5. **P1-4 跨话题串联（规格保留，Gate A 后仍需谨慎）**
   - 定位只做 induction：跨领域结构相似性识别；不做 deduction，也不做 abduction。
   - 必须有 `source_fact_ids >= 2` 的出口闸，禁止漂亮但无出处的 observation。
   - 产物若质量不够，砍功能，不引入 embedding、自训模型或常驻进程。

6. **RQ：决定 HRR 在默认 search 中的去留**
   - 已有 3-way vs 2-way A/B 迹象显示 HRR 对部分查询注入噪音。
   - 后续可考虑默认 search 降到 FTS5 + Jaccard 两路 RRF，HRR 保留给 `probe` / `related` / `reason` 的实验路径。
   - 不因“无语义召回”直接引入 embedding 服务；召回不足优先做 query reformulation 与候选控制。

7. **并发与独立包**
   - 已有 BEGIN IMMEDIATE、GC busy skip、PASSIVE checkpoint 等基础补丁。
   - 等 provenance、干净度和检索边界稳定后，再系统化独立包和多 agent 共享库体验。

---

## 已否决 / 冻结

- **P2 shared-entity 图边**：真实数据下 entity fan-out 低、共享 fact pairs 少，建边没有足够原料。除非未来真实快照证明 fan-out 明显回升，且出现必须靠图才能回答的真实查询，否则不重启。
- **P2.5 LLM 有类型边**：默认不做。主观边会污染链式查询，且需要 P2 先被真实需求解冻。
- **单值 scope 列**：判死。人的记忆不是规整 taxonomy；要做也只能是多对多，并且仍 gated on 真实需求。
- **cross-encoder / embedding 服务 / 常驻 worker / 外部 cron**：违背无常驻、关机即文件、开机即用的母红线。
- **路 B 并发（一个 agent 持有库）**：会把持有者变成必须先启动的记忆服务，不采用。

---

## 已知限制

- **有效期语义尚未显式建模**：`trust` / `recency` 不能表达“本周待办”“已过期”这类明确失效时点。归入后续 extractor profile / lifecycle 设计；当前不提前写 schema。
- **无 embedding 是设计取舍**：Holo 依赖 FTS5 / Jaccard / grep-like candidate recall，把理解留给当下 LLM。缺失不共词语义召回不是当前技术债。
- **entity 版本后缀混淆**：`GPT-4` / `GPT-4o` 这类后缀差异仍可能被数字签名弱化；真撞到再收紧守门。
- **跨 category 写入探重盲区**：`add_fact` 只在同 category 内探重，跨 category 重复留给 P1 批 GC 全局收敛。
- **工具面 retain 默认无 LLM**：`fact_store(action='retain')` 仍需要通过环境变量/配置注入 LLM client 才能获得高质量原子提炼。
- **HRR 容量只报警不自动分拆**：超长 fact 仍只触发 warning，未自动分拆。
- **LLM client 按需构造**：低频写路径可接受；遇到实测瓶颈前不缓存。

---

*Last updated: 2026-06-26*
