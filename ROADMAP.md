# Roadmap

> 长期路线与已知限制。已完成项进 [CHANGELOG.md](CHANGELOG.md)；当前活跃债务进 [TECH_DEBT.md](TECH_DEBT.md)。

---

## 当前阶段

两条主线：

- **A. 检索质量（RQ）**：RRF 已落地，HRR 路正在真实库上评估是否保留。
- **B. 库卫生（P0/P1）**：P0 写入探重、P1-1 entity 归一化、documents 表已落地；P1 自动 GC 壳与 trust 衰减已落地。P2 图边已用真实数据否决。

## 优先级队列

按「体感收益 / 风险」排序：

1. **RQ：决定 HRR 在 RRF 中的去留**
   - 已跑 3-way vs 2-way A/B 审计；多数查询下 HRR 注入噪音。
   - 决策：若真实库上人眼判断噪音占多数，则降级为 2-way RRF。

2. **P1 壳：惰性定时器 + 关机补漏**
   - 位置：`__init__.py` 或新增 `gc.py`。
   - 机制：hermes 进程内定时器，按时间戳判断距上次 GC 是否超阈值；hermes 不在时丢拍，回来时一次性补齐。
   - 禁止 OS cron / 独立 worker。

3. **P1-2/3：语义合并 + trust 衰减**
   - 语义合并：基于 entity 共现聚类 → LLM 一次性细判 → `merged_into` 软删除。
   - trust 衰减：`recency = clamp(1 - days/365, 0.1, 1.0)`，乘法作用于 trust。

4. **P1-4：跨话题串联（反思）**
   - 三条硬约束：产物喂回 recall、不独立常驻、必须指向具体源 fact。

5. **❌ P2：shared-entity 边 + CTE 多跳 —— 已否决**
   - 否决依据：380 条真实 facts 实测，entity avg fan-out 仅 0.811；94% 的 entity 只挂在一条 fact 上；共享至少一个 entity 的 fact pairs 仅 29 对。`tanh(shared × 0.5)` 在此分布上空转，建图无意义。
   - 重启条件：未来真实数据下 avg fan-out 回升到 1.5 以上，或共享 entity 的 fact pairs 数量级显著增加，再重测。
   - 后续影响：taxonomy（file:/tech:/user: 等前缀体系）下游于图层决策，P2 否决则 taxonomy 一并搁置。

6. **按子项目细分 `category`**
   - 投促局系统、公文写作系统、日常工作/会议等本就不该共用一个 `project` category。
   - 目的不是修 SNR，是数据组织正确；顺带缓解 `project` category bank 当前 370+ facts 的 SNR 压力。

## 已知限制

- **entity 版本后缀混淆**：`_numeric_signature` 对 "GPT-4" / "GPT-4o" 都抽出 `{4}`，存在误合并风险。观察真实数据后再决定是否加后缀语义守门。
- **fanout 下降归因未验**：灌入 351 条真实文档后，entity avg fan-out 从 1.22 降至 0.811。可能原因一是 entity 抽取噪声（长句/SQL 关键字被误抽），二是文档本身主题分散、低 entity 重叠。当前未分证，暂不调整 entity 抽取规则，避免过拟合。
- **跨 category 写入探重盲区**：`add_fact` 只在同 category 内探重，跨 category 重复留给 P1 批 GC 全局收敛。
- **工具面 retain 默认无 LLM**：`fact_store(action='retain')` 只能走本地 fallback，需通过环境变量/配置注入 LLM client。
- **HRR 容量只报警不拆分**：超长 fact 仅触发 warning，未自动分拆。
- **LLM client 按需构造**：每次 retain/consolidate 重新实例化，目前低频可接受。
