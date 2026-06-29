# Holographic Memory Provider

> 一个本地、轻量、无常驻进程的 hermes-agent 记忆插件。

Holographic Memory 用 SQLite 持久化事实，结合 FTS5 全文检索、HRR（Holographic Reduced Representations）相位向量与 trust 评分，为个人 Agent 提供可审计、可溯源、可组合的记忆查询。

---

## 核心设计取舍

- **本地 SQLite + WAL**：数据在文件里，关机即文件，开机即用。
- **无常驻进程 / 无外部依赖**：不加 Postgres、Redis、embedding 服务或 cron worker。
- **记忆数据不可再生**：schema 变更必须走 migration，禁止 DROP + CREATE。
- **理解留给当下的 LLM**：检索层负责召回候选、保留来源和降噪，不提前把“理解”烘焙进向量库。

---

## 快速开始

```bash
hermes memory setup    # select "holographic"
# or
hermes config set memory.provider holographic
```

核心工具：

- `fact_store` — `add`, `retain`, `search`, `probe`, `related`, `reason`, `contradict`, `update`, `remove`, `list`, `normalize`, `consolidate`
- `fact_feedback` — `helpful` / `unhelpful`，非对称调整 trust

跑测试：

```bash
pytest tests/
```

---

## 文档导航

| 文档 | 用途 |
|------|------|
| [`AGENTS.md`](./AGENTS.md) | **AI 协作者唯一工作入口**：项目契约、当前架构、开发红线、测试门禁 |
| [`docs/宪法.md`](./docs/宪法.md) | 判断准则层：母红线、Hindsight 筛选刀、进库裁决、协作规矩 |
| [`docs/README.md`](./docs/README.md) | `docs/` 目录导航与历史归档索引 |
| [`ROADMAP.md`](./ROADMAP.md) | 未来路线、已知限制、已否决/冻结/Gated 方向 |
| [`TECH_DEBT.md`](./TECH_DEBT.md) | 当前活跃技术债 |
| [`SESSION.md`](./SESSION.md) | 本轮工作状态与临时记忆 |
| [`CHANGELOG.md`](./CHANGELOG.md) | 按版本历史变更记录 |

---

## 工程红线（摘要）

完整版见 [`AGENTS.md`](./AGENTS.md)。

- Never break userspace。
- 禁止 `DROP TABLE` / 删库重建；schema 变更必须走 migration + 备份。
- 默认 `search()` 保持 FTS5 + Jaccard + HRR 三路 RRF。
- 不引入 embedding 服务、常驻 worker 或 OS cron。
- 不可逆操作之前必须验证，尽量 backup-first。

---

## 目录结构

```
holographic/
├── __init__.py          # 插件入口
├── store.py             # MemoryStore  orchestration
├── store_migrations.py  # SQLite schema + migrations
├── entities.py          # 实体抽取与归一化
├── extractors.py        # 文档 → fact 提取器
├── consolidation.py     # 语义合并
├── memory_gc.py         # 惰性垃圾回收
├── retrieval.py         # search / probe / related / reason / contradict
├── holographic.py       # HRR 向量代数
├── tests/               # pytest 测试与审计脚本
├── docs/                # 准则、导航、历史归档
└── reports/             # 审计脚本产物（非版本控制核心内容）
```
