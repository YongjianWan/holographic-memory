# Holographic Memory 代码摘要

> 本地 SQLite 事实记忆插件：FTS5 + Jaccard + HRR 检索，trust 评分，实体归一化。生成于 2026-06-24。

---

## 1. 项目定位

为 hermes-agent 提供的 MemoryProvider 插件。用 SQLite 存原子事实，无常驻进程、无外部向量服务，检索优先走本地可审计路线（全文/重叠度/HRR），理解交给当前 LLM。

核心约束见 `AGENTS.md`：禁止 DROP 重建、migration 必须备份、trust/recency 只能做乘性 boost。

---

## 2. 模块依赖图

```
hermes runtime
      │
      ▼
┌─────────────────┐
│   __init__.py   │  插件入口：工具 schema、配置、LLM 路由、生命周期 hook
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
store.py  retrieval.py
(读写核心)  (检索策略)
    │         │
    ├────┬────┤
    ▼    ▼    ▼
entities.py  consolidation.py  memory_gc.py
(实体/归一化)  (语义合并)      (惰性维护)
    │         │
    └────┬────┘
         ▼
  holographic.py
  (HRR 向量代数)
    │
    ▼
store_migrations.py
(schema + migration)
```

---

## 3. 核心模块一览

| 文件 | 关键类/函数 | 职责 |
|------|------------|------|
| `__init__.py` | `HolographicMemoryProvider` | 插件入口；注册 `fact_store` / `fact_feedback`；LLM 路由 |
| `store.py` | `MemoryStore` | 事实 CRUD、实体链接、HRR 生成、近重复检测、文档 retain |
| `store_migrations.py` | `_run_migrations` | SQLite schema、v1-v8 migration、基线检测、备份 |
| `entities.py` | `extract_entities` / `entity_names_match` | 实体抽取、解析、归一化守门 |
| `extractors.py` | `_LLMExtractor` / `_LLMConsolidator` | LLM 原子事实提取与语义合并 |
| `consolidation.py` | `find_consolidation_candidates` | 共享实体聚类 + LLM 软删除合并 |
| `memory_gc.py` | `GarbageCollector` | 非阻塞惰性维护；recency 因子 |
| `retrieval.py` | `FactRetriever` | search / probe / related / reason / contradict |
| `holographic.py` | `encode_fact` / `bind` / `bundle` | 确定性 HRR 相位向量代数 |

---

## 4. 关键算法速查

| 算法/常量 | 公式/值 | 说明 |
|-----------|---------|------|
| RRF 融合 | `score = Σ 1/(60 + rank_i)` | k=60；FTS5 / Jaccard / HRR 三路由排名位置融合 |
| trust boost | `1 + 0.2 × (trust − 0.5)` | 中心 1.0，范围 [0.9, 1.1] |
| recency boost | `0.9 + 0.1 × normalized_freshness` | 基础新鲜度 `freshness = clamp(1 - days/365, 0.1, 1.0)`。检索时归一化并映射至 `[0.9, 1.0]` 以防止干扰 RRF 主排序 |
| 近重复阈值 | Jaccard ≥ 0.8 | 写入时同 category 内检测 |
| 实体归一化阈值 | edit ≥ 0.85 / token ≥ 0.9 | numeric signature 不同则禁止合并 |
| HRR 容量警告 | `n_items > dim/4` | dim=1024 时 >256 items 报警 |
| HRR SNR | `sqrt(dim / n_items)` | bundled item 越多信噪比越低 |
| trust 反馈 | +0.05 helpful / −0.10 unhelpful | 非对称调整 |

---

## 5. 主数据流

### 5.1 写入事实

```
add_fact(content, category)
  → _find_near_duplicate(FTS5 粗排 → Jaccard)
      ├─ 命中 → _merge_into(existing_id)
      └─ 未命中 → INSERT → 抽实体 → 链实体 → 算 HRR → rebuild_bank
```

### 5.2 保留文档

```
retain_document(raw_text)
  → text_hash 去重落地 documents
  → _chunk_text 切块
  → extractor.extract 每块提炼事实
  → add_fact(..., source_doc_id=doc_id)
  → 统一 rebuild_bank
```

### 5.3 默认检索

```
search(query)
  → FTS5 排名 + Jaccard 排名 + HRR 排名
  → RRF 融合
  → × trust_boost × recency_boost × speaker_penalty
  → 更新 retrieval_count / last_accessed_at
```

---

## 6. 核心 Schema

| 表 | 作用 |
|---|------|
| `facts` | 原子事实；含 content(UNIQUE)、category、trust、retrieval_count、merged_into、hrr_vector |
| `entities` | 实体；name、aliases |
| `fact_entities` | 事实-实体二部图 |
| `documents` | 原始文档；raw_text、text_hash(UNIQUE) |
| `facts_fts` | FTS5 虚拟表，trigram 分词 |
| `memory_banks` | 按 category 聚合的 HRR bank |
| `schema_version` / `gc_log` | migration 版本 / 维护日志 |

---

## 7. 测试与运行

- **测试**：pytest，`tests/` 下 117 个用例；临时 SQLite，不碰真实库。
- **加载验证**：`python -c "import holographic"`
- **跑测试**：`pytest tests/`
- **真实 LLM eval**：`python batch_retain_eval.py --llm deepseek`、`python corpus_audit.py --llm deepseek`

---

## 8. 配置

`$HERMES_HOME/config.yaml` 节点 `plugins.hermes-memory-store`：

```yaml
db_path: $HERMES_HOME/memory_store.db
default_trust: 0.5
min_trust_threshold: 0.3
near_duplicate_threshold: 0.8
gc_interval_days: 7.0
gc_decay_max_days: 365.0
gc_decay_floor: 0.1
```

环境变量：`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`。

---

## 9. 当前状态与限制

- RRF 已落地；HRR 在真实数据上多数查询注入噪音，待评估是否从默认 search 降级。
- P2 shared-entity 图边已否决（fan-out 过低）。
- scope 可分性尚未通过真实数据门，不新增 schema。
- `source_doc_id` 单值归属，跨文档 merge 后无法还原完整来源。
- 写入探重仅同 category，跨 category 重复留给批 GC。

---

*更详细约束与设计决策见 `AGENTS.md`、`ROADMAP.md`、`TECH_DEBT.md`。*
