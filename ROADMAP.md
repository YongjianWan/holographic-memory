# Roadmap

> 长期路线与已知限制。已完成项进 [CHANGELOG.md](CHANGELOG.md)；当前活跃债务进 [TECH_DEBT.md](TECH_DEBT.md)。

---

## 当前阶段

两条主线：

- **A. 检索质量（RQ）**：RRF 已落地，HRR 路正在真实库上评估是否保留。
- **B. 库卫生（P0/P1）**：P0 写入探重、P1-1 entity 归一化、documents 表已落地；P1 自动 GC 壳与 trust 衰减已落地。P2 图边已用真实数据否决。

## 优先级队列

按「体感收益 / 风险」排序：

1. **继续灌真实数据 + 翻库 go/no-go（结构升级前置硬门）**
   - 真实语料已扩大到 2078 条 active facts / 9 documents；立即转入只读审计，暂停继续灌库，禁止先设计或执行 `scope` migration。
   - 第 0 项来源账已核清：第二批 1809 次成功 `fact_id` 返回中新增 1698 行；111 次 P0 merge 全部发生在 `工作心理问题.txt` 内部，落在 92 个新 fact target 上，没有合并进旧 380 条 facts。
   - 第 0 项质量账未完全通过：主体粒度正常，但 doc 9 有 18 条超过 60 字、11 条超过 80 字的异常输出，最长 196 字，包含模型提炼过程而非事实。门 A/B 抽样前必须过滤或清理这类 extraction meta。
   - `source_doc_id` 是单值归属，不记录“后来的文档也命中过该 fact”的贡献关系；未来跨文档 merge 后，不能直接拿 per-source linked count 当完整来源分布。
   - 门 B 机器初判已完成（只读、按 fact 内容多标签）：2029 条 clean facts 中，单域 1295（63.8%）、双域 467（23.0%）、三域以上 56（2.8%）、无匹配 211（10.4%）。最大候选域覆盖 36.2%，未出现单域吞没绝大多数 facts。
   - 初判把 scope 形态进一步收窄到 `fact ↔ scope` 多对多候选：25.8% facts 需要至少两个领域；单值 fact scope 不适合。该结论仍需人工复核 taxonomy、50 条门 A 样本和多域代表样本，未授权 migration。
   - 门 A 已过：现有 50 条人工样本中，30 条在“去掉人物后仍成立”的判据下为 GO，证明库里存在结构硬货。
   - 门 B 未过：尚未验证 facts 能否稳定、低歧义地切成领域。必须统计单领域、多领域、无法判断三类占比，并人工复核代表样本。
   - 候选领域必须从真实数据归纳，不能预设“投促局 / 公文系统 / Holographic”就是最终 taxonomy。
   - **GO**：绝大多数结构 fact 可稳定归入单一领域，跨领域事实比例低且规则清楚，才允许进入 scope 结构设计。
   - **NO-GO**：大量 fact 天生横跨多个领域或只能归为“混合/其他”，则不新增 scope schema；改评估多对多标签、document provenance，或维持现状。

2. **Category / scope 拆分（仅在门 B 通过后）**
   - `category` 保留事实类型；单值 `facts.scope` 已不再是候选。当前机器初判支持多对多 `fact ↔ scope`，但只有人工门通过后才允许设计。
   - 目标是缩小探重、检索与 consolidation 候选范围；只有过滤信号足够可靠时才值得进入 schema。
   - schema migration 不可逆，因此在 go/no-go 报告和人工样本审查完成前，不写 migration、不回填真实库。

3. **P1-4：跨话题串联（手动 canary）**
   - 每次只取 2-3 个不同 scope；每条 observation 至少引用 2 条源 fact。
   - 先生成候选报告，不直接写库；人工审查 20 条后再决定是否允许软写入。
   - 产物不能只是摘要或共同关键词，且不挂入自动 GC。
   - 若 scope 门 NO-GO，必须改用经验证的其他边界信号，不能假装已有可靠 scope。

4. **RQ：决定 HRR 在默认 search 中的去留**
   - 已跑 3-way vs 2-way A/B 审计；多数查询下 HRR 注入噪音。
   - 暂不阻塞 scope/P1-4；后续单独决定是否将默认 search 降级为 FTS5 + Jaccard 两路 RRF，并保留 HRR 给 `probe` / `reason` 实验路径。

5. **❌ P2：shared-entity 边 + CTE 多跳 —— 已否决**
   - 否决依据：380 条真实 facts 实测，entity avg fan-out 仅 0.811；94% 的 entity 只挂在一条 fact 上；共享至少一个 entity 的 fact pairs 仅 29 对。`tanh(shared × 0.5)` 在此分布上空转，建图无意义。
   - 重启条件：未来真实数据下 avg fan-out 回升到 1.5 以上，或共享 entity 的 fact pairs 数量级显著增加，再重测。
   - 后续影响：taxonomy（file:/tech:/user: 等前缀体系）下游于图层决策，P2 否决则 taxonomy 一并搁置。

## 已知限制

- **entity 版本后缀混淆**：`_numeric_signature` 对 "GPT-4" / "GPT-4o" 都抽出 `{4}`，存在误合并风险。观察真实数据后再决定是否加后缀语义守门。
- **fanout 下降归因未验**：早期灌入 351 条真实文档后，entity avg fan-out 从 1.22 降至 0.811。当前语料已增至 2078 条 active facts，旧分布结论需要重跑；在新审计前不调整 entity 抽取规则。
- **scope 可分性未验**：现有 50 条审查只证明部分 fact 具有脱离人物的结构价值，没有证明它们适合单值领域划分。scope 仍是待验证假设，不是已批准 schema。
- **category bank 已结构性过载**：2078 条 active facts 中 2071 条位于 `project`，1024 维 bank 估算 SNR 约 0.70。scope 只有在领域划分可靠且分布不过度失衡时，才可能同时改善过滤价值和 bank 饱和；若最大 scope 仍承载绝大多数 facts，拆分不能解决该问题。
- **跨 category 写入探重盲区**：`add_fact` 只在同 category 内探重，跨 category 重复留给 P1 批 GC 全局收敛。
- **工具面 retain 默认无 LLM**：`fact_store(action='retain')` 只能走本地 fallback，需通过环境变量/配置注入 LLM client。
- **HRR 容量只报警不拆分**：超长 fact 仅触发 warning，未自动分拆。
- **LLM client 按需构造**：每次 retain/consolidate 重新实例化，目前低频可接受。
