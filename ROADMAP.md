# Roadmap

> 长期路线与已知限制。已完成项进 [CHANGELOG.md](CHANGELOG.md)；当前活跃债务进 [TECH_DEBT.md](TECH_DEBT.md)。

---

## 当前阶段

两条主线：

- **A. 检索质量（RQ）**：RRF 已落地，HRR 路正在真实库上评估是否保留。
- **B. 库卫生（P0/P1）**：P0 写入探重、P1-1 entity 归一化、documents 表已落地；P1 自动 GC 壳与 trust 衰减已落地。P2 图边已用真实数据否决。

## 优先级队列

按「体感收益 / 风险」排序：

1. **当前库口径重建（ledger 已完成，scope gate 待重跑）**
   - 旧会话记录和当前报告口径不一致：曾记录 `2078 active facts / 2029 clean facts`，但当前 `reports/scope_gate_audit.md` 显示 `333 unique_fact_ids`。
   - 已通过 SQLite backup API 创建稳定快照并输出 `reports/current_db_ledger.md` / `.json`。
   - 当前快照口径：2741 total facts、1051 active facts、1690 soft-deleted facts、9 documents、schema v8；integrity check 为 ok，FK violations 为 0。
   - 当前 active category：project 933、personal 111、user_pref 6、general 1；`project` bank 1024 维估算 SNR 约 1.048。
   - 下一步必须基于该稳定快照重新跑 scope gate；任何旧的 Gate A/B 数字都只能作为历史线索，不能作为当前 schema 决策依据。
   - 仍保持已验证的设计边界：`source_doc_id` 是单值归属，不是完整 provenance；发生 merge 后不能用它推导完整来源。

2. **Category / scope 拆分（冻结到快照审计后）**
   - 不新增 `facts.scope`、`fact_scopes` 或 document-provenance migration，直到快照审计和人工复核完成。
   - 若新快照仍证明单值 scope 不成立，候选只能在多对多标签或 document-provenance 中继续评估。
   - 当前快照已经显示 active 库被大量软删除/重抽样改变：1690 条 soft-deleted facts 均指向 `999999 System audit soft-delete marker`，不能沿用旧的 2071 / SNR 0.70 结论。


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
