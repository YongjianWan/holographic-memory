# Roadmap

> 长期路线与已知限制。已完成项进 [CHANGELOG.md](CHANGELOG.md)；当前活跃债务进 [TECH_DEBT.md](TECH_DEBT.md)。

---

## 当前阶段

两条主线：

- **A. 检索质量（RQ）**：RRF 已落地，HRR 路正在真实库上评估是否保留。
- **B. 库卫生（P0/P1/P2）**：P0 写入探重、P1-1 entity 归一化、documents 表已落地；P1 自动 GC 壳与 P2 图边尚未启动。

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

5. **P2：shared-entity 边 + CTE 多跳**
   - 依赖 P0/P1 库干净；先做无类型 `related` 边，`tanh(shared × 0.5)` 压高频实体 fan-out。

6. **P2.5：LLM 有类型边**
   - 仅在出现真实查询必须靠 supports/contradicts 等类型关系才能答时才做。

## 已知限制

- **entity 版本后缀混淆**：`_numeric_signature` 对 "GPT-4" / "GPT-4o" 都抽出 `{4}`，存在误合并风险。观察真实数据后再决定是否加后缀语义守门。
- **跨 category 写入探重盲区**：`add_fact` 只在同 category 内探重，跨 category 重复留给 P1 批 GC 全局收敛。
- **工具面 retain 默认无 LLM**：`fact_store(action='retain')` 只能走本地 fallback，需通过环境变量/配置注入 LLM client。
- **HRR 容量只报警不拆分**：超长 fact 仅触发 warning，未自动分拆。
- **LLM client 按需构造**：每次 retain/consolidate 重新实例化，目前低频可接受。
