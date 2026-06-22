# SESSION.md — 当前工作状态

> 这个文件回答："上次干到哪了、现在在搞什么、有什么临时坑"。
> 跟 TECH_DEBT 的区别：TECH_DEBT 记"欠的债"，SESSION 记"手头的活和临时记忆"。
> 每次开工读它，收工更新它。

## 当前焦点

- **P1 惰性 GC 壳 + trust 衰减已落地**：新增 `memory_gc.py`（原 `gc.py`，因与标准库 `gc` 冲突而重命名）、migration v7 `gc_log` 表、配置项 `gc_interval_days` / `gc_decay_max_days` / `gc_decay_floor`；在 `initialize()` 和 `on_session_end()` 触发；`pytest` 103 passed。
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
  - 详细标注见 `C:/Users/sdses/AppData/Local/hermes/go_no_go_sample_50_labeled.json`。

## 进行中

- 无。

## 远程沙箱会话记录（无生产库/无 LLM key）

- 本会话运行环境是远程容器克隆，没有用户本机的生产库 `memory_store.db`、`SOUL.md`（符号链接指向 Windows 本机路径，断链）、也没有 `DEEPSEEK_API_KEY`。因此跳过需要真实数据判断的任务（§4 类灌库验证、按子项目细分 `project` category），改做纯代码层面、有测试覆盖的修复。
- **修复 fallback 提取器中文分句缺陷**：`_LocalFallbackExtractor.extract` 此前仅按 ASCII `.!?` 切句；中文文档很少用 ASCII 句号，无 LLM key 时整篇会被当成一条超长 fact 存入，直接撞上 HRR capacity warning。改为与 `store.py` 文档分块共用同一个中英文混合分句器（提到 `extractors.py`，命名为 `split_sentences`），消除重复实现。新增回归测试 `test_local_fallback_extractor_splits_chinese_sentences`。
- **清理过期 TECH_DEBT 条目**：L3"工具面 fact_store 缺乏默认 LLM 提炼支持"实际已在 `c1bb204` 通过 `_resolve_model_call` 解决（`retain`/`consolidate` 均已注入 DeepSeek/OpenAI client），文档未同步，已从活跃债务移除。
- `pytest`：104 passed（远程容器默认未装 `numpy`/`pytest`，需先 `pip install numpy pytest`；缺 numpy 时 1 个 HRR 相关测试因向量退化为 None 而误报失败，非代码 bug）。

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
- **P2 闸门**：50 条 go/no-go 中 GO 占 60%，不是"全是 Aiden 干了啥"，建议进入 P2 shared-entity 边 canary 验证。
- **生产库测试场纪律**：当前库小、数据可再生，同意拿生产库 `memory_store.db` 当测试场主动"造"bug。唯一红线：每次动生产库前必须先 `cp memory_store.db memory_store.db.bak.<标签>`；backup 不是为了防数据丢失，而是为了"动手前快照 vs 动手后状态"的 diff，定位环境耦合类 bug（如 HRR/entity 不一致、migration 顺序、路径配置等）。


---

*Last updated: 2026-06-22（远程沙箱会话补充）*
