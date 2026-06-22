# SESSION.md — 当前工作状态

> 这个文件回答："上次干到哪了、现在在搞什么、有什么临时坑"。
> 跟 TECH_DEBT 的区别：TECH_DEBT 记"欠的债"，SESSION 记"手头的活和临时记忆"。
> 每次开工读它，收工更新它。

## 当前焦点

- P1-2 语义合并安全验证：
  - **A（临时库）**：用 3 个桌面 .md 文件灌出 159-fact 临时库，发现 1 个候选簇；执行合并后 2 facts 被软删、1 个新 fact 生成；回滚（`merged_into=NULL`）后原 facts 重新可见。合并与回滚机制通过。
  - **B（真实库）**：29-fact 真实库无自然近重复，强制合并 `25,26,27` 被 LLM 守卫拒绝（`facts_merged=0`），说明当前策略不会随便软删记忆。

## 进行中

- 无。

## 本轮待办

- [x] 完成文档整理并 commit。
- [x] 同步到 hermes 实时目录。
- [x] 跑 P1-2 A+B 安全验证。
- [ ] 决定是否给 `run_consolidation_trial.py` 增加 `--db` 参数并 commit 该改进。

## 已知陷阱（临时）

- `run_consolidation_trial.py` 原先用 `from __init__ import _resolve_model_call`，作为脚本运行时会因相对导入失败。已本地修复为内联 `_resolve_model_call`，尚未 commit。

## 决策记录

- HRR 暂时不改动：审计结论是噪音占多数，但用户决定先保留，后续再决策。
- P1-2 当前策略不会误合并：真实库强制合并实验被 LLM 守卫拒绝；临时库自然近重复合并可正常回滚。

---

*Last updated: 2026-06-22*
