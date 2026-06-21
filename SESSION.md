# SESSION.md — 当前工作状态

> 这个文件回答："上次干到哪了、现在在搞什么、有什么临时坑"。
> 跟 TECH_DEBT 的区别：TECH_DEBT 记"欠的债"，SESSION 记"手头的活和临时记忆"。
> 每次开工读它，收工更新它。

## 当前焦点

- v6 migration 落地：FTS5 rebuild 覆盖全部 facts（包括 soft-delete），修复 v5 active-only  bug。
- HRR 质量审计：在真实库（29 facts）上跑 3-way vs 2-way RRF，15/15 查询发散，中位重合度 0.40；多数 "HRR 注入项" 为噪音。
- 文档整理：新建 ROADMAP.md / docs/README.md，精简 AGENTS.md（移除嵌入式 SOUL 与未来路线），重置 SESSION.md。

## 进行中

- 无。

## 本轮待办

- 完成文档整理并 commit。
- 同步到 hermes 实时目录。

## 已知陷阱（临时）

- 无。

## 决策记录

- HRR 暂时不改动：审计结论是噪音占多数，但用户决定先保留，后续再决策。

---

*Last updated: 2026-06-21*
