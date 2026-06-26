# Current DB Ledger

## Safety

- Source database was copied with SQLite backup API.
- Counts below come from the copied snapshot, not from the live WAL database.
- Source DB: `C:\Users\sdses\AppData\Local\hermes\memory_store.db`
- Snapshot DB: `reports\snapshots\memory_store_snapshot_20260624_205628.db`

## Integrity

- generated_at: 2026-06-24T20:56:28
- schema_version: 8
- integrity_check: ok
- foreign_key_violations: 0

## Fact Counts

- facts_total: 3181
- facts_active: 1034
- facts_soft_deleted: 2147
- documents_total: 9
- merge_targets: 1
- merge_events: 2147
- cross-source merge candidates: 0

## Active Facts By Category

| category | active_facts |
|---|---:|
| project | 917 |
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

## Memory Banks

| bank_name | fact_count | snr |
|---|---:|---:|
| cat:general | 1 | 32.0 |
| cat:personal | 113 | 3.01 |
| cat:project | 917 | 1.057 |
| cat:user_pref | 6 | 13.064 |

## Meta Candidates

- candidate_count_limited_to_100: 34

| fact_id | doc | length | content |
|---:|---:|---:|---|
| 19 | None | 406 | Commit review cron job: daily at 9 AM, skill=github-code-review, script=collect_commits.py, deliver=local. Background review prompt updated on 2026-06-02: _SKILL_REVIEW_PROMPT and _COMBINED_REVIEW_PROMPT added HARD RULE - must check skills_list() before creating new skill, patch instead of create when possible. "Be ACTIVE" retained. Frequency creation_nudge_interval=15. File: agent/background_review.py. |
| 2 | None | 339 | Policy evaluation platform (aizsgzt-admin) uses five-layer architecture: user entry, business process, Agent application, self-developed Agent Factory core, underlying capability & data resource. Agent application layer includes pre-evaluation Agent, review assistant Agent, report Q&A Agent (implemented), post-evaluation Agent (planned). |
| 23 | None | 338 | Hindsight memory export completed on 2026-06-15. 5189 total memory units in PostgreSQL (1312 world, 2422 experience, 1455 observation). 329 valuable world facts filtered and exported to ~/AppData/Local/hermes/hindsight_export.json. Key topics: aizsgzt platform architecture, skill curation decisions, user preferences, API configurations. |
| 16 | None | 295 | User device ecosystem: Xiaomi (non-Google ecosystem). Calendar does not assume Google Calendar, target is Mi Cloud / enterprise Exchange. Email: Gmail (wan19993300@gmail.com) with app password, IMAP connected via Hermes gateway. 163 (wan199933@163.com): IMAP blocked by server policy, SMTP-only. |
| 18 | None | 289 | User is Feishu super admin. "Don't mess things up, no need to ask for permission" positioning. For skill evaluation: assess from AI execution perspective (clear triggers, structured instructions, explicit constraints, failure fallback, fixed output format). Human readability is secondary. |
| 22 | None | 289 | Holographic memory provider activated on 2026-06-15. SQLite database at ~/AppData/Local/hermes/memory_store.db. HRR dimension 1024, auto_extract enabled, default trust 0.5. No external dependencies, no daemon, no model loading. Replaces hindsight which died from PyTorch meta tensor error. |
| 6 | None | 279 | Frontend application uses Vue.js with Pinia state management. Routes include static routes and investment workbench hidden routes. Has login/lock screen/dynamic route permission guards. API calls via Axios with baseURL, Token, error handling, and duplicate submission prevention. |
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
| 29 | None | 220 | holographic memory Schema 迁移框架：schema_version 表 + 自动基线检测 + 迁移前 .db.bak.v{n} 备份（WAL checkpoint 后复制）。外键在迁移期间禁用，完成后重新启用并检查。当前版本 v4：新增 documents 表、text_hash UNIQUE 索引、facts.source_doc_id 外键（ON DELETE SET NULL）、merged_into 列。 |
| 11 | None | 218 | llm-wiki and obsidian skills: initially not merged because obsidian already contains Karpathy notes and llm-wiki may have uncovered content. User later considered them essentially the same thing and merge was executed. |
| 4 | None | 213 | Platform eight-dimension scoring: expansion capability, investment willingness, relevance, layout matching, supply chain completeness, investment attraction value, success rate, comprehensive recommendation score. |
| 13 | None | 208 | User prefers concise and direct responses over elaborate language. Values truth over politeness. "随便" / "？" / "开干" means "stop talking and do it". Zero tolerance for "said they did but didn't actually do it". |
| 12 | None | 206 | GitHub repository awesome-copilot has 58+ skills. User requested checking and merging with existing skills. excalidraw-diagram-generator skill downloaded and installed via GitHub API (terminal was blocked). |
| 5 | None | 164 | Local MCP server (ai_zsgzt_mcp) based on Node.js, reads merged-mcp-openapi.yaml, dynamically registers OpenAPI tools. Provides tool calling capability for AI panel. |
| 25 | None | 159 | holographic memory 插件 2026-06-21 更新：HRR 向量相似度从 RRF 融合中移除，基于 343-fact 语料 A/B 测试结论——HRR 对未匹配查询是噪音，对已匹配查询冗余。搜索降级为 2-way FTS5 + Jaccard RRF 融合。同时移除 hrr_weight 配置项。 |
| 10 | None | 157 | Django and Spring Boot skills not merged due to different tech stacks and both being actively used by user. Cross-tech-stack non-merge principle established. |
| 24 | None | 154 | holographic memory 是主动查询机制（非自动注入），与 hindsight 的 pre_llm_call 自动召回不同。使用分层策略：高频/关键偏好放 MEMORY（自动注入），档案/项目细节放 holographic（按需 fact_store search）。hindsight 已弃用。 |
| 27 | None | 137 | holographic memory 实体归一化收紧：默认阈值 edit 0.85 / token 0.9。新增数字/日期/版本签名门控——"K2"（系列）与 "K2.7"（版本）即使字符串相似度高也不再合并。canonical 选择优先最具体的名称（含数字/标点/长度）。 |
| 349 | 4 | 25 | 6月11日（周四）完成文件上传模块和命名规则校验。 |
| 362 | 4 | 24 | 需用户确认文件命名规则主题_日期_版本是否可行。 |
| 368 | 4 | 22 | 开发侧6月11日完成文件上传和命名规则解析。 |
| 238 | 1 | 21 | 研判流程通过智能体驱动，而非人工配置规则。 |
| 376 | 4 | 20 | 需求确认文件命名规则为主题_日期_版本。 |
| 316 | 4 | 18 | 文件命名规则格式为主题_日期_版本。 |
