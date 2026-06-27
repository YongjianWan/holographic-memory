# Dirty Fact Candidates

## Safety

- Source database was copied with SQLite backup API.
- Report reads the copied snapshot only; it does not mutate facts, schema, or provenance.
- `likely_dirty` means the row matched current extractor guardrails or historical meta-leak patterns.
- `review` means the row is worth a human look, not that it should be removed.
- Source DB: `C:\Users\sdses\AppData\Local\hermes\memory_store.db`
- Snapshot DB: `reports\snapshots\memory_store_dirty_audit_20260627_184643.db`

## Summary

- generated_at: 2026-06-27T18:46:43
- active_facts_scanned: 2199
- candidate_count: 49
- review_length: 240
- review: 49

## Candidates

| fact_id | verdict | disposition | doc | length | reasons | content |
|---:|---|---|---:|---:|---|---|
| 19 |  | review | None | 406 | long_atomicity_check:>240 | Commit review cron job: daily at 9 AM, skill=github-code-review, script=collect_commits.py, deliver=local. Background review prompt updated on 2026-06-02: _SKILL_REVIEW_PROMPT and _COMBINED_REVIEW_PROMPT added HARD RULE - must check skills_list() before creating new skill, patch instead of create when possible. "Be ACTIVE" retained. Frequency creation_nudge_interval=15. File: agent/background_review.py. |
| 2 |  | review | None | 339 | long_atomicity_check:>240 | Policy evaluation platform (aizsgzt-admin) uses five-layer architecture: user entry, business process, Agent application, self-developed Agent Factory core, underlying capability & data resource. Agent application layer includes pre-evaluation Agent, review assistant Agent, report Q&A Agent (implemented), post-evaluation Agent (planned). |
| 23 |  | review | None | 338 | long_atomicity_check:>240 | Hindsight memory export completed on 2026-06-15. 5189 total memory units in PostgreSQL (1312 world, 2422 experience, 1455 observation). 329 valuable world facts filtered and exported to ~/AppData/Local/hermes/hindsight_export.json. Key topics: aizsgzt platform architecture, skill curation decisions, user preferences, API configurations. |
| 16 |  | review | None | 295 | long_atomicity_check:>240 | User device ecosystem: Xiaomi (non-Google ecosystem). Calendar does not assume Google Calendar, target is Mi Cloud / enterprise Exchange. Email: Gmail (wan19993300@gmail.com) with app password, IMAP connected via Hermes gateway. 163 (wan199933@163.com): IMAP blocked by server policy, SMTP-only. |
| 18 |  | review | None | 289 | long_atomicity_check:>240 | User is Feishu super admin. "Don't mess things up, no need to ask for permission" positioning. For skill evaluation: assess from AI execution perspective (clear triggers, structured instructions, explicit constraints, failure fallback, fixed output format). Human readability is secondary. |
| 22 |  | review | None | 289 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count), long_atomicity_check:>240 | Holographic memory provider activated on 2026-06-15. SQLite database at ~/AppData/Local/hermes/memory_store.db. HRR dimension 1024, auto_extract enabled, default trust 0.5. No external dependencies, no daemon, no model loading. Replaces hindsight which died from PyTorch meta tensor error. |
| 6 |  | review | None | 279 | long_atomicity_check:>240 | Frontend application uses Vue.js with Pinia state management. Routes include static routes and investment workbench hidden routes. Has login/lock screen/dynamic route permission guards. API calls via Axios with baseURL, Token, error handling, and duplicate submission prevention. |
| 9 |  | review | None | 274 | long_atomicity_check:>240 | Skill curation decisions: hermes-self-audit merged into hermes-agent as references/. skill-evaluator merged into l4-skill-forge as evaluation framework. excalidraw-diagram-generator merged into excalidraw. dispatching-parallel-agents merged into subagent-driven-development. |
| 21 |  | review | None | 261 | long_atomicity_check:>240 | API keys location (values not stored): KIMI_API_KEY→env, Kimi CLI→~/.kimi/config.toml, GitHub→~/.config/gh/hosts.yml, VolcEngine→ov.conf, SERPER/TUSHARE/ELEVENLABS→env pending configuration. HINDSIGHT_API_KEY in .env but hindsight service dead as of 2026-06-09. |
| 7 |  | review | None | 254 | long_atomicity_check:>240 | Backend layered architecture: boot, web controller, service layer (AigzsgtAgentChatService for agent chat, CompanyAnalysisService), data access layer. Modules: security (Redis), biz, system, quartz, generator connect to database; agentProxy via HTTP/SSE. |
| 3 |  | review | None | 247 | long_atomicity_check:>240 | Platform uses three vertical LLMs: general LLM, investment attraction vertical LLM, report generation LLM. Data sources include Haier enterprise database (30M+), Jinan policy/land/fund database, industry dynamics, government cloud computing power. |
| 26 |  | review | None | 247 | long_atomicity_check:>240 | holographic memory 插件 consolidation 机制改为软删除：consolidate_facts 执行 UPDATE 设置 merged_into 指向合并后的 fact ID，而非物理 DELETE。所有 9 条读取路径（search/list/probe/related/reason/contradict/FTS5 JOIN 等）均过滤 merged_into IS NULL。支持 reactivation：相同内容再次插入时自动清除 merged_into。 |
| 1 |  | review | None | 246 | long_atomicity_check:>240 | Hindsight memory system fixed and running on port 9100. DeepSeek v4 Flash + BAAI/bge-small-en-v1.5 + FlashRank. Migrated to holographic memory provider on 2026-06-15 due to PyTorch embedding model loading failure (Cannot copy out of meta tensor). |
| 20 |  | review | None | 244 | long_atomicity_check:>240 | Quality standards integration belongs to l4-skill-forge layer (eval-cases, release-checklist, l4-standard, score-skill.js), not hermes-agent-skill-authoring. Architecture decision made to separate skill authoring from quality evaluation layers. |
| 29 |  | review | None | 220 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | holographic memory Schema 迁移框架：schema_version 表 + 自动基线检测 + 迁移前 .db.bak.v{n} 备份（WAL checkpoint 后复制）。外键在迁移期间禁用，完成后重新启用并检查。当前版本 v4：新增 documents 表、text_hash UNIQUE 索引、facts.source_doc_id 外键（ON DELETE SET NULL）、merged_into 列。 |
| 1001221 |  | review | 15 | 74 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | `search_facts` has the side effect of incrementing `retrieval_count += 1`. |
| 1001214 |  | review | 15 | 55 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | Test scripts must not touch the real `memory_store.db`. |
| 1001183 |  | review | 15 | 45 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | P0 探重的 SQL 不能更新 retrieval_count，也不能过滤低 trust。 |
| 1001149 |  | review | 15 | 42 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | migration 框架 + schema_version 已实现（v1-v10）。 |
| 1001162 |  | review | 15 | 35 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | 启动时按 schema_version 顺序执行 migration。 |
| 1001277 |  | review | 16 | 122 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | Schema migration framework has schema_version table, automatic baseline detection, and pre-migration .db.bak.v{n} backups. |
| 1001253 |  | review | 16 | 116 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | Successful search, probe, related, and reason retrievals now increment retrieval_count and refresh last_accessed_at. |
| 1001261 |  | review | 16 | 54 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | On 380 active facts, entity average fan-out was 0.811. |
| 1001368 |  | review | 17 | 52 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | Old active facts are not backfilled with provenance. |
| 1001455 |  | review | 18 | 64 | transient_state:(当前\|目前).{0,12}(facts?\|条目\|token\|上下文\|slot\|槽位) | project bank 当前 fact_count 为 933，按 1024 维估算 SNR 约 1.048，仍低于 2.0。 |
| 1001497 |  | review | 18 | 57 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | Legacy provenance 不回填；旧 active facts 无 provenance 行是诚实状态。 |
| 1001509 |  | review | 18 | 56 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | 任何写入真实 memory_store.db 的动作都必须先备份，并将 backup 用作前后 diff 基准。 |
| 1001480 |  | review | 18 | 52 | transient_state:(当前\|目前).{0,12}(facts?\|条目\|token\|上下文\|slot\|槽位) | project category 仍然过宽，当前 fact_count 933，SNR 约 1.048。 |
| 1001531 |  | review | 19 | 59 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | 旧active facts可能没有provenance行，查询侧必须把空行状态读时投影为legacy_unknown。 |
| 1001536 |  | review | 19 | 44 | transient_state:(当前\|目前).{0,12}(facts?\|条目\|token\|上下文\|slot\|槽位) | 偿还计划：复核当前快照dirty fact候选，确认后通过merged_into软删除。 |
| 1001634 |  | review | 20 | 98 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | 核心 schema 表包括 facts、entities、fact_entities、documents、facts_fts、memory_banks、schema_version、gc_log。 |
| 1001635 |  | review | 20 | 79 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | facts 表含 content(UNIQUE)、category、trust、retrieval_count、merged_into、hrr_vector。 |
| 1001641 |  | review | 20 | 48 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | schema_version 和 gc_log 表分别记录 migration 版本和维护日志。 |
| 1001647 |  | review | 20 | 46 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | 配置项 db_path 默认值为 $HERMES_HOME/memory_store.db。 |
| 1001633 |  | review | 20 | 40 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | 最后更新 retrieval_count / last_accessed_at。 |
| 1001803 |  | review | 21 | 69 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | B. 探重的 FTS5 查询必须删 retrieval_count += 1 且去 trust 过滤，否则污染 GC 信号或漏掉低分重复。 |
| 1001784 |  | review | 21 | 56 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | _find_near_duplicate 用 FTS5 粗筛候选，删 retrieval_count += 1。 |
| 1001842 |  | review | 21 | 42 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | Trust衰减依赖P0-B：retrieval_count不被探重污染，信号才可信。 |
| 1001710 |  | review | 21 | 39 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | search_facts 有副作用 retrieval_count += 1。 |
| 1001704 |  | review | 21 | 38 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | 已有 retrieval_count 和 helpful_count 计数。 |
| 1001795 |  | review | 21 | 19 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | retrieval_count 累加。 |
| 1001958 |  | review | 22 | 277 | long_atomicity_check:>240 | The data filling approach must never use a full commit because facts cannot be deleted: start with a batch script, test 3-5 core granularities and token cost, then run full volume in time order only if granularity is acceptable, then immediately review 50 entries for go/no-go. |
| 1001911 |  | review | 22 | 132 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | Version 10 does not write self-referencing provenance placeholders for old active facts; an empty field represents the honest state. |
| 1001953 |  | review | 22 | 109 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | The next step is to rerun Gate A/B based on the 1051 active fact snapshot, first filling in the batch ledger. |
| 1001935 |  | review | 22 | 84 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | Gate A/B verification must be rerun after the database changed to 1051 active facts. |
| 1001925 |  | review | 22 | 72 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | This document was last updated based on a snapshot of 1051 active facts. |
| 1002014 |  | review | 23 | 49 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | Aiden已确认第三层会发生（开多个Claude Code写同一memory_store.db）。 |
| 1002005 |  | review | 23 | 29 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | N不固定，且都往同一个memory_store.db读写。 |
| 1002171 |  | review | 25 | 58 | transient_state:(active facts?\|schema_version\|memory_store\.db\|retrieval_count) | B.探重的FTS5查询必须删retrieval_count+=1且去trust过滤（否则污染GC信号/漏低分重复）。 |
