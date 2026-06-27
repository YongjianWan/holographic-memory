# Current DB Ledger

## Safety

- Source database was copied with SQLite backup API.
- Counts below come from the copied snapshot, not from the live WAL database.
- Source DB: `C:\Users\sdses\AppData\Local\hermes\memory_store.db`
- Snapshot DB: `reports\snapshots\memory_store_snapshot_20260627_180530.db`

## Integrity

- generated_at: 2026-06-27T18:05:30
- schema_version: 10
- integrity_check: ok
- foreign_key_violations: 0

## Fact Counts

- facts_total: 4347
- facts_active: 2200
- facts_soft_deleted: 2147
- documents_total: 20
- merge_targets: 1
- merge_events: 2147
- cross-source merge candidates: 0

## Active Facts By Category

| category | active_facts |
|---|---:|
| project | 2083 |
| personal | 111 |
| user_pref | 5 |
| general | 1 |

## Documents

| doc_id | active | soft_deleted | source |
|---:|---:|---:|---|
| 1 | 227 | 0 | C:\Users\sdses\Desktop\现状（部分）.txt |
| 2 | 0 | 0 | C:\Users\sdses\Desktop\梁局汇报PPT-实际演示版.md |
| 3 | 47 | 0 | C:\Users\sdses\Desktop\今日.md |
| 4 | 77 | 0 | C:\Users\sdses\Desktop\AI智能检索与公文写作系统_需求文档.md |
| 5 | 46 | 57 | C:\Users\sdses\Desktop\ppt修改.txt |
| 6 | 264 | 772 | C:\Users\sdses\Desktop\招商会议.txt |
| 7 | 14 | 0 | C:\Users\sdses\Desktop\土地数据.txt |
| 8 | 218 | 620 | C:\Users\sdses\Desktop\招商2.txt |
| 9 | 113 | 696 | C:\Users\sdses\Desktop\工作心理问题.txt |
| 15 | 130 | 0 | AGENTS.md |
| 16 | 117 | 0 | CHANGELOG.md |
| 17 | 77 | 0 | ROADMAP.md |
| 18 | 98 | 0 | SESSION.md |
| 19 | 66 | 0 | TECH_DEBT.md |
| 20 | 70 | 0 | docs\achieve\CODE_SUMMARY.md |
| 21 | 247 | 0 | docs\achieve\holo-改造方案.md |
| 22 | 94 | 0 | docs\achieve\session_2026-06-24_legacy_status.md |
| 23 | 45 | 0 | docs\achieve\并发补丁_多agent共享库.md |
| 24 | 14 | 0 | docs\README.md |
| 25 | 208 | 0 | docs\宪法.md |

## Memory Banks

| bank_name | fact_count | snr |
|---|---:|---:|
| cat:general | 1 | 32.0 |
| cat:personal | 113 | 3.01 |
| cat:project | 2083 | 0.701 |
| cat:user_pref | 6 | 13.064 |

## Meta Candidates

- candidate_count_limited_to_100: 100

| fact_id | doc | length | content |
|---:|---:|---:|---|
| 19 | None | 406 | Commit review cron job: daily at 9 AM, skill=github-code-review, script=collect_commits.py, deliver=local. Background review prompt updated on 2026-06-02: _SKILL_REVIEW_PROMPT and _COMBINED_REVIEW_PROMPT added HARD RULE - must check skills_list() before creating new skill, patch instead of create when possible. "Be ACTIVE" retained. Frequency creation_nudge_interval=15. File: agent/background_review.py. |
| 2 | None | 339 | Policy evaluation platform (aizsgzt-admin) uses five-layer architecture: user entry, business process, Agent application, self-developed Agent Factory core, underlying capability & data resource. Agent application layer includes pre-evaluation Agent, review assistant Agent, report Q&A Agent (implemented), post-evaluation Agent (planned). |
| 23 | None | 338 | Hindsight memory export completed on 2026-06-15. 5189 total memory units in PostgreSQL (1312 world, 2422 experience, 1455 observation). 329 valuable world facts filtered and exported to ~/AppData/Local/hermes/hindsight_export.json. Key topics: aizsgzt platform architecture, skill curation decisions, user preferences, API configurations. |
| 16 | None | 295 | User device ecosystem: Xiaomi (non-Google ecosystem). Calendar does not assume Google Calendar, target is Mi Cloud / enterprise Exchange. Email: Gmail (wan19993300@gmail.com) with app password, IMAP connected via Hermes gateway. 163 (wan199933@163.com): IMAP blocked by server policy, SMTP-only. |
| 18 | None | 289 | User is Feishu super admin. "Don't mess things up, no need to ask for permission" positioning. For skill evaluation: assess from AI execution perspective (clear triggers, structured instructions, explicit constraints, failure fallback, fixed output format). Human readability is secondary. |
| 22 | None | 289 | Holographic memory provider activated on 2026-06-15. SQLite database at ~/AppData/Local/hermes/memory_store.db. HRR dimension 1024, auto_extract enabled, default trust 0.5. No external dependencies, no daemon, no model loading. Replaces hindsight which died from PyTorch meta tensor error. |
| 6 | None | 279 | Frontend application uses Vue.js with Pinia state management. Routes include static routes and investment workbench hidden routes. Has login/lock screen/dynamic route permission guards. API calls via Axios with baseURL, Token, error handling, and duplicate submission prevention. |
| 1001958 | 22 | 277 | The data filling approach must never use a full commit because facts cannot be deleted: start with a batch script, test 3-5 core granularities and token cost, then run full volume in time order only if granularity is acceptable, then immediately review 50 entries for go/no-go. |
| 9 | None | 274 | Skill curation decisions: hermes-self-audit merged into hermes-agent as references/. skill-evaluator merged into l4-skill-forge as evaluation framework. excalidraw-diagram-generator merged into excalidraw. dispatching-parallel-agents merged into subagent-driven-development. |
| 21 | None | 261 | API keys location (values not stored): KIMI_API_KEY→env, Kimi CLI→~/.kimi/config.toml, GitHub→~/.config/gh/hosts.yml, VolcEngine→ov.conf, SERPER/TUSHARE/ELEVENLABS→env pending configuration. HINDSIGHT_API_KEY in .env but hindsight service dead as of 2026-06-09. |
| 7 | None | 254 | Backend layered architecture: boot, web controller, service layer (AigzsgtAgentChatService for agent chat, CompanyAnalysisService), data access layer. Modules: security (Redis), biz, system, quartz, generator connect to database; agentProxy via HTTP/SSE. |
| 3 | None | 247 | Platform uses three vertical LLMs: general LLM, investment attraction vertical LLM, report generation LLM. Data sources include Haier enterprise database (30M+), Jinan policy/land/fund database, industry dynamics, government cloud computing power. |
| 26 | None | 247 | holographic memory 插件 consolidation 机制改为软删除：consolidate_facts 执行 UPDATE 设置 merged_into 指向合并后的 fact ID，而非物理 DELETE。所有 9 条读取路径（search/list/probe/related/reason/contradict/FTS5 JOIN 等）均过滤 merged_into IS NULL。支持 reactivation：相同内容再次插入时自动清除 merged_into。 |
| 1 | None | 246 | Hindsight memory system fixed and running on port 9100. DeepSeek v4 Flash + BAAI/bge-small-en-v1.5 + FlashRank. Migrated to holographic memory provider on 2026-06-15 due to PyTorch embedding model loading failure (Cannot copy out of meta tensor). |
| 20 | None | 244 | Quality standards integration belongs to l4-skill-forge layer (eval-cases, release-checklist, l4-standard, score-skill.js), not hermes-agent-skill-authoring. Architecture decision made to separate skill authoring from quality evaluation layers. |
| 17 | None | 233 | User is cost-sensitive to AI token costs. Considers compute expensive as a real constraint. Philosophy: "quality over quantity", delete redundancy quickly, don't create artificial needs. Decision standard: "am I actually using this?" |
| 8 | None | 227 | Data and external dependencies: HighGo/PostgreSQL compatible library (public schema, Flyway migration), Redis (Token/cache/verification), AI large model API, MCP tool registration, file storage, weather API, SMS API, email API. |
| 15 | None | 226 | User's current direction: Personal automation agent (Scout route), green-lit on 2026-06-04. Milestones: email webhook/IMAP IDLE → Calendar tools → reimbursement skill → event-driven framework → long-running background watcher. |
| 28 | None | 226 | holographic memory 新增文档保留流程：retain_document 存储原始文本，按 SHA256 去重，通过 FactExtractor 协议提取原子 facts。支持 pluggable extractor：_LocalFallbackExtractor（句子拆分，标记 fallback）和 _LLMExtractor（注入 model_call）。长文档按段落/句边界分块，默认 max_chunk_tokens=6000。 |
| 1001981 | 22 | 221 | Module P1-2 (production strategy release) is gated on threshold calibration: the four thresholds must be calibrated on the real 1051 library, especially the HRR semantic merging threshold (0.97 cannot be directly copied). |
| 29 | None | 220 | holographic memory Schema 迁移框架：schema_version 表 + 自动基线检测 + 迁移前 .db.bak.v{n} 备份（WAL checkpoint 后复制）。外键在迁移期间禁用，完成后重新启用并检查。当前版本 v4：新增 documents 表、text_hash UNIQUE 索引、facts.source_doc_id 外键（ON DELETE SET NULL）、merged_into 列。 |
| 1001244 | 16 | 220 | Read-only scope gate audit separates inserted rows, unique fact IDs, merge targets/events, extraction-meta candidates, Gate A sampling, and content-derived multi-label scope distribution without relying on source_doc_id. |
| 1001980 | 22 | 220 | Scope many-to-many plus category/scope decoupling plus HRR bank by scope is gated on Gate B: it proceeds only if facts can be stably partitioned into domains; otherwise, many-to-many is no better than single-value scope. |
| 11 | None | 218 | llm-wiki and obsidian skills: initially not merged because obsidian already contains Karpathy notes and llm-wiki may have uncovered content. User later considered them essentially the same thing and merge was executed. |
| 4 | None | 213 | Platform eight-dimension scoring: expansion capability, investment willingness, relevance, layout matching, supply chain completeness, investment attraction value, success rate, comprehensive recommendation score. |
| 13 | None | 208 | User prefers concise and direct responses over elaborate language. Values truth over politeness. "随便" / "？" / "开干" means "stop talking and do it". Zero tolerance for "said they did but didn't actually do it". |
| 1001979 | 22 | 207 | Module P1-4 (cross-topic linking) is gated on Gate A: it proceeds only if reviewing 50 facts yields structure independent of the human; if all facts are "Aiden did something," the entire module is abandoned. |
| 12 | None | 206 | GitHub repository awesome-copilot has 58+ skills. User requested checking and merging with existing skills. excalidraw-diagram-generator skill downloaded and installed via GitHub API (terminal was blocked). |
| 1001989 | 22 | 203 | The recovery mechanism task (migration dry-run, rollback, WAL corruption/partial write retain recovery tests) is postponed because the current single-user low-frequency workload has not hit these issues. |
| 1001937 | 22 | 195 | Module P1-2 (semantic merging + trust/recency) is 40-60% complete; consolidation, soft-delete, recency v8, and GC busy have implementations and tests, but the production strategy is not released. |
| 1001940 | 22 | 192 | The concurrency patch is 25-35% complete; BEGIN IMMEDIATE, GC busy skip, PASSIVE mode, and transactional atomicity exist, but a complete multi-agent solution is not systematically implemented. |
| 1001977 | 22 | 189 | Route B concurrency (one agent holds the database) is not adopted because it would turn the holder into a "memory service that must be started first," breaking the no-startup-sequence rule. |
| 1001969 | 22 | 181 | Module P2 (shared-entity edge building) is vetoed/frozen because real data has a fan-out of 0.811 and 94% of entities appear in only one fact, leaving no material for edge building. |
| 1001950 | 22 | 180 | The four thresholds to be calibrated are all document starting values, not final values: Jaccard 0.8, HRR semantic merging threshold, tanh confidence, and trust deletion threshold. |
| 1001987 | 22 | 179 | The fixed eval test set task (20 real queries, 20 not-to-be-recalled, 20 dirty data, 20 timeline, 20 provenance) is postponed because a clean corpus is needed as a baseline first. |
| 1001976 | 22 | 177 | Embedding-based semantic recall violates the red line and will not be implemented because it requires a persistent embedding service; the cost of no semantic recall is accepted. |
| 1001239 | 16 | 172 | The generated report records current fact counts, document distribution, soft-delete counts, memory bank pressure, and candidate dirty facts without mutating the source DB. |
| 1001322 | 16 | 172 | add_fact, update_fact, normalize_entities, and each consolidation cluster now own a single atomic transaction covering facts, entity links, HRR vectors, and category banks. |
| 1001963 | 22 | 170 | The original 33KB transformation plan document has been downgraded to an archive: it must not be deleted, but it is no longer in the active reading list for construction. |
| 1001965 | 22 | 170 | The concept of validity semantics has been identified as a pending design point: trust decay means "older is less trusted," not that the fact has a clear expiration time. |
| 1001982 | 22 | 169 | Solving HRR bank saturation does not necessarily require scope: options include further bucketing within categories or accepting weak HRR signals with low weight in RRF. |
| 1001971 | 22 | 166 | Module P2.5 (LLM-attributed typed edges) is permanently rejected because memory edges are subjective, error-prone, lack self-healing, and contaminate chained queries. |
| 5 | None | 164 | Local MCP server (ai_zsgzt_mcp) based on Node.js, reads merged-mcp-openapi.yaml, dynamically registers OpenAPI tools. Provides tool calling capability for AI panel. |
| 1001993 | 22 | 162 | The P1-1 version suffix mis-merge risk (K2/K2.7) is cut for now because a digit/version signature gate already catches it; tighten only if boundary cases are hit. |
| 1001411 | 17 | 160 | Recovery mechanisms including migration dry-run, rollback, WAL corruption, partial write retain recovery are deferred to concurrent/independent packaging phase. |
| 25 | None | 159 | holographic memory 插件 2026-06-21 更新：HRR 向量相似度从 RRF 融合中移除，基于 343-fact 语料 A/B 测试结论——HRR 对未匹配查询是噪音，对已匹配查询冗余。搜索降级为 2-way FTS5 + Jaccard RRF 融合。同时移除 hrr_weight 配置项。 |
| 1001924 | 22 | 159 | This document's sources include the progress summary, ChatGPT conversation conclusions, the original coverage cheat sheet, and the handover document Section 4. |
| 1001855 | 21 | 158 | P2 fact_edges仅构建shared-entity关联边，无有类型关系，表结构含source_fact_id、target_fact_id、edge_type默认为'related'、confidence用tanh(shared*0.5)、resolution_method为'shared-entity'。 |
| 10 | None | 157 | Django and Spring Boot skills not merged due to different tech stacks and both being actively used by user. Cross-tech-stack non-merge principle established. |
| 24 | None | 154 | holographic memory 是主动查询机制（非自动注入），与 hindsight 的 pre_llm_call 自动召回不同。使用分层策略：高频/关键偏好放 MEMORY（自动注入），档案/项目细节放 holographic（按需 fact_store search）。hindsight 已弃用。 |
| 1001991 | 22 | 154 | Performance optimization for full table scans of tens to hundreds of thousands of facts is cut because it is premature for a single-user personal library. |
| 1001975 | 22 | 152 | Cross-encoder rerank violates the red line and will not be implemented because it requires a persistent model; RRF is the officially accepted downgrade. |
| 1001962 | 22 | 151 | Handover document §4 (data filling is zero, retain has not been fed real files) is outdated and replaced by this document's progress table (1051/1690). |
| 1001917 | 22 | 150 | This block is an old status snapshot moved from `SESSION.md`, archived from checkpoint commit `4f9aef0 chore: checkpoint holographic workspace state`. |
| 1001387 | 17 | 147 | Systematic independent packaging and multi-agent shared library experience deferred until provenance, cleanliness, retrieval boundaries are stable. |
| 1001922 | 22 | 147 | Conflict rule: if this document conflicts with the constitution or the specification, the status/progress/sorting in this document take precedence. |
| 1001270 | 16 | 144 | Migration v6 rebuilds facts_fts to index all facts, including soft-deleted ones, fixing the v5 active-only coverage bug that broke reactivation. |
| 1001410 | 17 | 144 | Fixed eval test set (20 real queries, 20 should-not-recall, 20 dirty data, 20 timeline, 20 provenance) is deferred until clean library baseline. |
| 1001209 | 15 | 142 | New features must add unit tests for RRF formula, Jaccard calculation, entity normalization clustering, P0 dedup threshold and merge behavior. |
| 1001948 | 22 | 142 | The go/no-go decision for Gate A (corpus review) requires reviewing 50 facts manually to check if the fact still holds without the human name. |
| 1001955 | 22 | 141 | The next step is to complete the data ledger: extraction_runs -> fact_provenance (without confidence) -> quality_reason plus dirty_candidate. |
| 1002178 | 25 | 141 | P1-2 semantic merge and timeline convergence handles two cases: different wording for the same fact, and non-literal timeline contradictions. |
| 1001945 | 22 | 140 | All thresholds for ★3 (especially the HRR semantic merging threshold, where 0.97 cannot be directly copied) must be calibrated on real data. |
| 1001237 | 16 | 139 | Validity/expiration semantics are deferred to the future extractor-profile phase after the current corpus is cleaned and Gate A/B is rerun. |
| 1001272 | 16 | 138 | RRF-based FactRetriever.search combines FTS5, Jaccard token overlap, and HRR vector similarity using rank positions instead of raw scores. |
| 1001385 | 17 | 138 | Embedding service not introduced due to "no semantic recall"; insufficient recall addressed via query reformulation and candidate control. |
| 1001973 | 22 | 138 | The single-value scope column is declared dead because human memory is not a tidy taxonomy and a single fact often spans multiple domains. |
| 27 | None | 137 | holographic memory 实体归一化收紧：默认阈值 edit 0.85 / token 0.9。新增数字/日期/版本签名门控——"K2"（系列）与 "K2.7"（版本）即使字符串相似度高也不再合并。canonical 选择优先最具体的名称（含数字/标点/长度）。 |
| 1001968 | 22 | 136 | This design is not to be implemented now because the library is not yet clean; discussing validity semantics now would be running ahead. |
| 1001978 | 22 | 135 | Reflect loop / consolidation worker is not implemented because it requires a background loop; the need is already satisfied by lazy GC. |
| 1001992 | 22 | 135 | Category bank full rebuild to incremental update is cut because the current scale is insignificant; it can be addressed after auditing. |
| 1001382 | 17 | 134 | If cross-topic linking output quality is insufficient, the feature is cut; no embedding, self-trained models, or persistent processes. |
| 1001210 | 15 | 132 | New features must add integration tests running the full add_fact → search/probe/reason → feedback chain on a temporary SQLite file. |
| 1001911 | 22 | 132 | Version 10 does not write self-referencing provenance placeholders for old active facts; an empty field represents the honest state. |
| 1001401 | 17 | 131 | Induction only for P1-4, with source_fact_ids >= 2, cut if quality insufficient; no embedding, self-training, persistent processes. |
| 1001959 | 22 | 131 | Previous plan §5 (GC trigger as an in-process timer in Hermes) is outdated and replaced by the concurrency plan in specification ②. |
| 1001983 | 22 | 131 | The validity/validity semantics task is postponed because the library is not yet clean and designing it now would be running ahead. |
| 1001927 | 22 | 130 | The core framework is built, but the project is not near completion; the next phase is cleaning the real data and productizing it. |
| 1001985 | 22 | 130 | The extractor profiling task is postponed because the current single prompt has not been stabilized; profiling would be premature. |
| 1001964 | 22 | 128 | Sections 5, 6, and 8 of the original plan are overturned, but the context for why they were overturned remains in that document. |
| 1001421 | 17 | 125 | Cross-category write dedup blind spot; add_fact dedups only within same category; cross-category duplicates handled by P1 GC. |
| 1001422 | 17 | 125 | Tool-side retain has no LLM by default; requires environment variable or config injection for high-quality atomic extraction. |
| 1001912 | 22 | 125 | When the query side encounters a legacy fact without a provenance row, it should project it as `legacy_unknown` at read time. |
| 1001966 | 22 | 125 | A statement like "must deliver this week" should die after the week passes, not decay slowly; these are two different things. |
| 1001110 | 15 | 124 | fact_store 工具有 12 个动作：add, retain, search, probe, related, reason, contradict, update, remove, list, normalize, consolidate。 |
| 1001967 | 22 | 124 | This validity concept should be noted in the extractor profile layer, marked as "validity/expired semantics pending design." |
| 1001224 | 15 | 123 | When fact volume is large, consider bucketing or pre-filtering for `probe`/`related`/`reason` to avoid performance crashes. |
| 1002183 | 25 | 123 | P1-3 states that facts falling below the trust deletion threshold are not returned in list/search or are removed during GC. |
| 1001277 | 16 | 122 | Schema migration framework has schema_version table, automatic baseline detection, and pre-migration .db.bak.v{n} backups. |
| 1001939 | 22 | 122 | Module P2 (edge building) is vetoed/frozen because real data fan-out does not support it and is not counted as incomplete. |
| 1001956 | 22 | 122 | The next step is to decide on scope: many-to-many, document-provenance, or continue freezing, depending on Gate B results. |
| 1001943 | 22 | 121 | Based on full productization (independent package, concurrency, clean corpus, scope, P1-4), overall completion is 40-45%. |
| 1001541 | 19 | 56 | 偿还计划：后续若发现误合，需对_numeric_signature或相似度匹配增加后缀语义排除规则（宁漏不误）。 |
| 1001533 | 19 | 48 | 第二批真实数据中，工作心理问题.txt有少量模型自言自语、规则复述和分析过程被当作fact写入。 |
| 1001432 | 18 | 47 | 审计报告在 reports/current_db_ledger.md 和 .json 文件中。 |
| 1001511 | 18 | 27 | 规则已拉直：会议发言事件计为客观事件记录（PASS）。 |
| 349 | 4 | 25 | 6月11日（周四）完成文件上传模块和命名规则校验。 |
| 362 | 4 | 24 | 需用户确认文件命名规则主题_日期_版本是否可行。 |
| 368 | 4 | 22 | 开发侧6月11日完成文件上传和命名规则解析。 |
| 238 | 1 | 21 | 研判流程通过智能体驱动，而非人工配置规则。 |
