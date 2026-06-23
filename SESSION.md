# SESSION.md — 当前工作状态

> 这个文件回答："上次干到哪了、现在在搞什么、有什么临时坑"。
> 跟 TECH_DEBT 的区别：TECH_DEBT 记"欠的债"，SESSION 记"手头的活和临时记忆"。
> 每次开工读它，收工更新它。

## 当前焦点

- **migration v8 / recency 语义修复已落地**：
  - 新增 `facts.last_accessed_at`；recency 是查询时导出值，不落库。
  - `trust_score` 只承载反馈置信度；GC 不再永久侵蚀 trust，也不再用自身维护操作刷新 `updated_at`。
  - search / probe / related / reason 成功召回后统一登记访问；RRF 实时计算线性 recency boost，并限幅到 `0.9..1.0`。
- **关键写路径已原子化**：
  - `add_fact` 的探重 + INSERT 使用 `BEGIN IMMEDIATE`，两个连接并发写近重复只保留一条。
  - `add_fact` / `update_fact` / `normalize_entities` / consolidation cluster 覆盖 fact、entity link、HRR、category bank 的同一事务。
  - GC 抢不到 SQLite 写锁时立即返回 `busy`；close checkpoint 改为 `PASSIVE`。
- **验证**：`pytest tests/` 110 passed；`python -c "import holographic"` 与 compileall 通过。
- **下一步**：真实库已扩大到 2078 active facts / 9 documents；暂停继续灌库，立即做 scope 可分性翻库审计。在 go/no-go 门 B 通过前，禁止设计或执行 scope migration。
- **LLM retain 调用链已闭环**：
  - 插件复用 Hermes centralized provider router 解析凭证，但 retain 固定使用 DeepSeek；DeepSeek 不可用时明确失败，不允许退到主模型或其他 provider。
  - LLM 调用失败不再吞成“0 facts”；结果返回 chunk、异常类型和错误信息，orphan document 可原地重试。
- **第二批真实文档已灌入**：
  - ⚠️ 本批次执行时 retain router 错误配置为 `provider="auto"`，Hermes
    当前主 provider 为 `kimi-coding`，因此这批 facts 由 Kimi 提炼，不是
    预期的 DeepSeek。备份
    `memory_store.db.bak.before_orphan_retry_20260623_095125` 可用于回滚后
    以 DeepSeek 重提炼；在用户裁决前保留现状，不继续灌库。
  - `ppt修改.txt`：49 facts
  - `招商会议.txt`：530 facts
  - `土地数据.txt`：14 facts
  - `招商2.txt`：409 facts
  - `工作心理问题.txt`：696 条新 source-linked facts（extractor 返回 807 个 ID，其中 111 个被 P0 探重合并）
  - 净增 1698 active facts；SQLite integrity check 通过，FK violations 为 0。
  - `project` category bank 达 2071 facts，1024 维估算 SNR 约 0.70；批量写入逐条全量重建 bank 的性能债已记录。
- **翻库第 0 项核账**：
  - before/after 备份差分确认：新增行 1698；111 次 merge 全部发生在 doc 9 内部，落在 92 个新 target 上；旧 380 facts 的 retrieval_count 无增量。
  - `facts_added` 实际是成功返回 fact ID 的次数，包含重复返回旧 ID，不等于净新增。
  - 新批次长度分布 p50=20、p95=38、p99=62；主体粒度正常。异常集中在 doc 9：18 条 >60 字、11 条 >80 字、最长 196 字，包含模型提炼过程。
  - entity 数未普遍爆炸：整体 p50=0、p99 约 3、max=9。SNR 0.70 的主因是 2071 facts 共用一个 project bank。
  - `source_doc_id` 只记录单一归属，跨文档 merge 时会丢失后来 source 的贡献；门 B 报告不得把它当完整 provenance。
- **门 A/B 只读审计报告已生成**：
  - 报告：`reports/scope_gate_audit.md` / `reports/scope_gate_audit.json`。
  - 计数口径：inserted rows 1698、merge targets 92、merge events 111、successful fact ID returns 1809。
  - 保守标记 extraction-meta 候选 49 条；其中存在少量误报，必须人工确认后再软删。
  - 2029 条 clean facts 的多标签初判：0 域 211、单域 1295、双域 467、三域以上 56。
  - 最大候选域为“技术项目开发”734 条（36.2%）；“招商引资与企业分析”613 条（30.2%）。分布不再是单一招商域压倒性独大。
  - 25.8% facts 需要至少两个领域，机器初判不支持单值 `facts.scope`，支持 `fact ↔ scope` 多对多候选；人工门尚未完成，不授权 schema。
- **P1 惰性 GC 壳**：migration v7 引入 `gc_log` 与进程内触发；原 trust 衰减语义已由 migration v8 的独立 recency signal 替代。
- **真实库 HRR 一致性已修复**：
  - 发现上一轮 entity 重索引（29 facts → 65 entities / 79 links）后，`hrr_vector` **没有同步重算**。
  - 备份 → 运行 `tests/scripts/run_recompute_hrr_vectors.py` → 29 条 active facts 全部重抽 entity + 重算 HRR + 重建 category banks。
  - 对比 `memory_store.db.bak.before_entity_reindex_20260622_122721`：backup 中仅 9 条 facts 有 entity，current 中 26 条有 entity，确认 entity 集合确实变化，HRR 重算是必要的。
  - 3 条 facts（fact_id 4/9/11）无 entity 链接，与 backup 一致（content 本身无强 entity 信号），HRR 与空 entity 集合一致，非脏数据。
- **§4 canary 已执行**：
  - 4 个真实文档按时间正序 retain 进真实库：
    1. `现状（部分）.txt`（Apr 8）→ 227 facts
    2. `梁局汇报PPT-实际演示版.md`（Apr 15）→ 0 facts（已有相同 text_hash，去重）
    3. `今日.md`（Apr 20）→ 47 facts
    4. `AI智能检索与公文写作系统_需求文档.md`（Jun 10）→ 77 facts
  - 真实库从 29 facts 增至 380 facts（+351）。
  - Token 成本（实测，DeepSeek V4 Flash $0.14/M input, $0.28/M output）：
    - 4 文件共 ~19,880 input + ~7,856 output tokens
    - 约 $0.005 / 4 files → **~$0.12 / 100 files**
  - 粒度合格：平均 20–30 字符/ fact，最长 < 60 字符；样本显示为原子化改写，不是 fallback 句子切分。
  - **SNR 警告出现**：project category 事实数 370+，category bank SNR 降至 ~1.66（< 2.0 阈值）。需增加 `hrr_dim` 或细分 category。
- **50 条 go/no-go 审查完成**：
  - 按 source 比例随机抽样 50 条新增 facts。
  - 判据："去掉'人'这一条，fact 还成立吗？"
  - 结果：**GO 30 条 / NO-GO 20 条，GO 比例 60%**。
  - GO 事实以业务规则、系统架构、约束、数据口径为主；NO-GO 以临时进度、待确认事项、个人任务、过期 deadline 为主。
  - 该结果只通过了“是否存在结构硬货”的门 A；尚未验证单领域 / 多领域 / 无法判断分布，不能据此批准 scope schema。
  - 详细标注见 `C:/Users/sdses/AppData/Local/hermes/go_no_go_sample_50_labeled.json`。

## 进行中

- scope 前置门 B：扩大真实语料后，生成只读候选领域与多域歧义报告，再人工复核。

## 本轮待办

- [x] 完成文档整理并 commit。
- [x] 同步到 hermes 实时目录。
- [x] 跑 P1-2 A+B 安全验证。
- [x] 给 `run_consolidation_trial.py` 增加 `--db` 参数并修复相对导入问题。
- [x] 优化中文实体抽取并重新索引真实库。
- [x] 让 `generic_threshold` 自适应小库。
- [x] 实现 P1 惰性 GC 壳 + trust 衰减。
- [x] 修复 `gc.py` 与标准库 `gc` 的命名冲突，重命名为 `memory_gc.py`。
- [x] 修复真实库 HRR 向量与 entity 链接不一致的问题。
- [x] 执行 §4 canary：3-5 个真实文档 retain + 粒度和 token 实测。
- [x] 完成 50 条 go/no-go 审查。

## 已知陷阱（临时）

- `project` category 下 facts 已达 370+，HRR category bank SNR 跌破 2.0。继续往 `project` 灌文档会进一步恶化检索质量。需在下次全量灌入前决策：增加 `hrr_dim`（需 migration + 全量重算 HRR）或按子项目细分 category。

## 决策记录

- HRR 暂时不改动：审计结论是噪音占多数，但用户决定先保留，后续再决策。
- P1-2 当前策略不会误合并：真实库强制合并实验被 LLM 守卫拒绝；临时库自然近重复合并可正常回滚。
- 中文实体抽取不引入外部依赖（jieba 等），用正则规则 + 技术后缀 + 缩写/点号技术词实现。
- 真实库已备份：
  - `memory_store.db.bak.before_entity_reindex_20260622_122721`
  - `memory_store.db.bak.before_hrr_recompute_20260622_141637`
  - `memory_store.db.bak.before_canary_retain_20260622_145608`
- **store.py 重构**：拆出 `store_migrations.py`（schema + 迁移）和 `extractors.py`（LLM/fallback 提取器 + consolidator），`store.py` 从 ~2228 行降至 ~1700 行；测试 72 passed。
- **P1-2 调参方向被拦**：在 29 条 facts 的样本上继续放宽 generic/Jaccard 阈值以"让 consolidation 更频繁触发"是错的——当前库中近重复本就稀少，这是 P0 写入探重有效的证据。下一步应先批量灌入真实文档，等样本到几百条、出现真实近重复后再调参。
- **结构价值门 A**：50 条 go/no-go 中 GO 占 60%，只说明库里不是全是“Aiden 干了啥”；它不授权 P2，也不授权 scope。P2 已被后续真实 fan-out 数据否决。
- **scope 不可逆门**：scope 属于 prefix/namespace 一类结构升级。真实数据未证明领域可稳定划分前，不加列、不加表、不回填；多域事实占比高则直接 NO-GO。
- **生产库测试场纪律**：当前库小、数据可再生，同意拿生产库 `memory_store.db` 当测试场主动"造"bug。唯一红线：每次动生产库前必须先 `cp memory_store.db memory_store.db.bak.<标签>`；backup 不是为了防数据丢失，而是为了"动手前快照 vs 动手后状态"的 diff，定位环境耦合类 bug（如 HRR/entity 不一致、migration 顺序、路径配置等）。


---

*Last updated: 2026-06-23*
