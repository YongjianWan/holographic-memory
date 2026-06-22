# AGENTS.md — Holographic Memory Provider

> 本文件供 AI 编码助手使用。如果你要修改代码，请先读这里。
> 工程纪律见 [SOUL.md](SOUL.md)；未来路线见 [ROADMAP.md](ROADMAP.md)；历史变更见 [CHANGELOG.md](CHANGELOG.md)。

## 快速开始

```bash
hermes memory setup    # select "holographic"
# or
hermes config set memory.provider holographic
```

工具：

- `fact_store` — 10 actions: add, retain, search, probe, related, reason, contradict, update, remove, list, normalize, consolidate.
- `fact_feedback` — helpful/unhelpful，非对称调整 trust。

跑测试：

```bash
pytest tests/
```

eval 脚本（需 `DEEPSEEK_API_KEY`，结果输出到 `reports/`）：

```bash
source .env
python batch_retain_eval.py --llm deepseek
python corpus_audit.py --llm deepseek
```

## 1. 项目定位

Holographic Memory 是 hermes-agent 的一个 **MemoryProvider 插件**：用本地 SQLite 做事实存储，结合 FTS5 全文检索、HRR（Holographic Reduced Representations，纯数学向量）和 trust 评分，实现可组合查询（probe / reason / related / contradict）。

核心红线：

- **无常驻进程、无外部依赖**：不加 Postgres / Redis / embedding 服务 / cron worker。
- **关机即文件、开机即用**：数据在 SQLite 文件里，启动无初始化序列。
- **记忆数据不可再生**：任何 schema 变更必须走 migration，**禁止 DROP + CREATE**。

## 2. 仓库布局

源码已复制到当前工作目录，与 hermes 安装的实时副本并存：

```
C:/Users/sdses/Desktop/随机小项目/holographic/          # 本仓库（工作目录）
├── __init__.py          # 插件入口：MemoryProvider 实现、工具分发、配置、on_session_end
├── store.py             # MemoryStore  orchestration：事实 CRUD、实体链接、HRR 向量生成、配置
├── store_migrations.py  # SQLite schema、_SCHEMA、migration v1-v6 及基线检测
├── entities.py          # 实体抽取、解析、名称/别名匹配、归一化守门
├── extractors.py        # 文档→fact 提取器协议、fallback/LLM 提取器、LLM consolidator
├── consolidation.py     # 语义合并候选发现、LLM 守卫、merged_into 软删除
├── memory_gc.py         # 惰性垃圾回收：trust 衰减、GC 日志
├── retrieval.py         # 检索策略：search / probe / related / reason / contradict
├── holographic.py       # HRR 相位向量代数（bind/unbind/bundle/similarity/encode_*）
├── plugin.yaml          # 插件声明
├── AGENTS.md            # 本文件（项目契约与现状）
├── ROADMAP.md           # 未来路线与已知限制
├── CHANGELOG.md         # 历史变更
├── TECH_DEBT.md         # 活跃技术债
├── SESSION.md           # 本轮工作状态
├── SOUL.md              # 人格与工程纪律
├── holo-改造方案.md      # 历史设计稿
└── docs/README.md       # 文档导航

C:/Users/sdses/AppData/Local/hermes/hermes-agent/plugins/memory/holographic/   # hermes 加载的实时副本
└── （同名的源码文件，通过快捷方式「holographic - 快捷方式.lnk」指向）
```

**开发流程**：

1. 在当前工作目录改代码、跑测试、做版本控制。
2. 改动稳定后，再复制/同步到 AppData 下的实时目录，供 hermes 实际加载。
3. 不要把实时目录里的 `.db` 文件或 `__pycache__` 拖进本仓库。
4. **任何 API key / 令牌只能走环境变量**

---

## 人格与工程纪律

完整内容见 [SOUL.md](SOUL.md)。此处只锚定与本项目直接相关的 L1 工程底线：

- Never break userspace。
- shutdown/close/cleanup 逐步 try-catch；cache load 防御旧/损坏格式。
- 数据一致性：cache 引用不塞可变结构；删除实体时清理关联缓存槽位。
- 不碰 `.env` / `.key` / `.pem` / `.p12` / `.pfx` / `.crt` / `id_rsa`，只改 `.env.example`。
- TDD 红线：没有失败测试不写生产代码；改测试前先跑 RED。
- 验证门禁 5 步：命令 → 运行 → 读输出/退出码 → 验证支持结论 → 宣称完成。
- 每轮结束前 `git status --short`；Commit 说清改了啥，一次别改太多不相关东西。
- 可逆/影响局限当前任务 → 干就完了；不可逆/影响外溢 → 先说清楚等确认。
- 代码不仅要写注释而且写是什么，也写为什么。保证代码可读性。

## 3. 当前架构现状（读源码后确认）

| 能力                                                  | 状态              | 位置                            |
| ----------------------------------------------------- | ----------------- | ------------------------------- |
| SQLite + WAL fallback                                 | ✅ 已有           | `store.py` / `store_migrations.py` |
| `facts` / `entities` / `fact_entities` 二部图   | ✅ 已有           | `store_migrations.py` / `store.py` |
| FTS5 全文索引 + 触发器同步                            | ✅ 已有           | `store_migrations.py`          |
| HRR 向量（1024d，确定性 SHA-256 atoms）               | ✅ 已有           | `holographic.py`               |
| trust 非对称反馈（+0.05 / -0.10）                     | ✅ 已有           | `store.py`                     |
| `probe` / `related` / `reason` / `contradict` | ✅ 已有           | `retrieval.py`                 |
| RRF 三路融合（RQ）                                    | ✅ 已实现         | `retrieval.py`                 |
| entity 归一化（P1-1）                                 | ✅ 已实现         | `entities.py` / `store.py`     |
| 近重复检测（P0）                                      | ✅ 已实现         | `store.py`                     |
| migration 框架 +`schema_version`                    | ✅ 已实现 (v1-v6) | `store_migrations.py`          |
| `documents` 表 + `facts.source_doc_id`            | ✅ 已实现         | `store_migrations.py` / `store.py` |
| `documents.text_hash` 去重                          | ✅ 已实现         | `store_migrations.py` / `store.py` |
| 文档入口 `retain_document`（§3.5）                 | ✅ 已实现         | `store.py` / `extractors.py` / `__init__.py` |
| `facts.merged_into` 软删除 & 语义合并（P1-2）       | ✅ 已实现         | `consolidation.py` / `store.py` / `retrieval.py` |
| 惰性 GC / trust 衰减（P1）                            | ✅ 已实现         | `memory_gc.py` / `store.py` / `__init__.py` |
| `fact_edges` 图边 + CTE 多跳（P2）                  | ❌ 未实现         | 待新增                          |

## 4. 开发约定

### 4.1 改动前必读

1. 先读 `holo-改造方案.md`（当前目录），尤其是 §0 核心判断、§8 落地顺序、§7 禁止删库重建。
2. 改动涉及数据库 schema 时，先确认现有用户数据库路径（默认 `$HERMES_HOME/memory_store.db`），并提供真 migration + 备份提示。
3. 不要修改 `holographic.py` 中的 HRR 数学语义，除非你有充分理由并同步更新所有调用点。

### 4.2 数据安全 / migration 铁律

- **禁止 DROP TABLE / DROP DATABASE / 删库重建**。
- 加列/加表用 `ALTER TABLE ... ADD COLUMN` 或 `CREATE TABLE ... INSERT INTO ... SELECT` 迁移。
- 启动时按 `schema_version` 顺序执行 migration；老库没有 `schema_version` 表时，必须根据实际 schema 反推基线版本（从最新结构往回匹配：先查 `documents`/`source_doc_id`，再查 `hrr_vector`）。
- `_SCHEMA` 必须始终保持为**最新完整结构**；空库初始化后即为最新版本，不需要跑 migration。
- 每次升级前在代码里硬做备份：`PRAGMA wal_checkpoint(FULL)` 后再复制 `.db.bak.v{current}`，不覆盖已有备份。
- migration 期间 `PRAGMA foreign_keys = OFF`，结束后开启并执行 `PRAGMA foreign_key_check`；有 violations 必须抛异常，不能留下脏状态。
- **FK pragma 管理禁止在 `try` 块内 `return` 早退**：所有退出路径（已最新、升级完成、异常）都必须经过同一个 `finally`；`finally` 里无条件 `PRAGMA foreign_keys = ON`，不要“保存-恢复”原状态（SQLite 默认 OFF，恢复等于没开）。
- 切换 FK pragma 前必须 `conn.commit()` 确保无活动事务（SQLite 在事务里改 FK pragma 是 no-op）。
- 每个 migration 函数必须内部幂等（`IF NOT EXISTS` / `PRAGMA table_info` 自检）。
- 任何会改表结构的操作，文档/日志里都要提醒用户先备份 `.db`。

### 4.3 检索质量（RQ）红线

- 三路检索（FTS5 / Jaccard / HRR）**禁止直接拿原始分线性相加**。
- 必须改用 **RRF（Reciprocal Rank Fusion）**：`score = Σ 1/(60 + rank_i)`，k=60。
- **HRR 那路是假设，不是事实**：全量数据上来后必须实测三路 RRF 与两路（FTS5+Jaccard）RRF 的排序差异。若在真实语料上 HRR 两两相似度塌在噪声区间（如 366 条云提取事实 max≈0.089、p99≈0.052），则 HRR 给出的“排名”就是噪声，会往共识分里掺沙子。届时应将 HRR 在 RRF 中降权或踢出，而不是继续调 HRR 阈值。
- trust / recency 只能做**乘法 boost**，不能做加法；boost 中心 1.0、限幅 ±10% 左右。

### 4.4 库卫生（P0/P1/P2）红线

- **P0 写入探重**必须放在 `add_fact` 的 INSERT 之前，不能依赖 `IntegrityError`。
- `retain_document` 是输入侧闭环：先按 `text_hash` 去重落地原文，再提炼 fact；提炼失败保留孤儿 document，可重跑。
- Fallback 提取器只保证“不崩”，不替代 LLM 粒度；fallback fact 必须降 trust 并标记。
- **fallback 语料禁止用于标定任何阈值/分布/质量指标**（包括 HRR 阈值、entity 质量、分类分布）。key 失效时宁可等，也不要拿 fallback 跑出来的数当“临时基准”——它的粒度是系统性偏烂的，会被误当真基准用。fallback 只能用来验证脚本是否能跑通。
- P0 探重只能用 **FTS5 + Jaccard**，不要用 HRR（新 fact 还没 entities，向量口径不同）。
- P0 探重的 SQL **不能** 更新 `retrieval_count`，也**不能**过滤低 trust。
- **P1 必须先做 entity 归一化，再做 P2 建边**——边来自 entity，entity 碎裂则边全脏。
- entity 归一化必须加 **numeric/date/version signature 守门**："K2" 与 "K2.7" 是层级不是碎裂，不能靠字符串相似度硬合。
- entity 归一化阈值要保守：默认 edit ≥ 0.85 或 token ≥ 0.9 才合并，宁可漏合、不错合。
- **P2 边默认只做 `shared-entity` 无类型边**；有类型边（supports/contradicts/...）是 P2.5，必须有真实查询需求才做。

### 4.5 常驻进程红线

- 不能用 OS cron / anacron / 独立 worker。
- 周期性任务必须挂在 hermes 进程内（如 `on_session_end`、asyncio 惰性定时器、启动时补漏）， hermes 不在就跑不了，回来时按时间戳一次性补齐。

### 4.6 LLM 使用原则

- 所有 LLM 调用必须是一次性 API，**不能**在系统内维持长期循环或后台推理。
- LLM 只用于：文档提炼、语义合并/收敛、跨话题串联。排序/探重/建边尽量本地完成。

## 5. 未来路线

新需求优先级与已知限制见 [ROADMAP.md](ROADMAP.md)。

## 6. 测试要求

新增功能时必须补齐测试：

- 单元测试：RRF 公式、Jaccard 计算、entity 归一化聚类、P0 探重阈值与 merge 行为。
- 集成测试：在临时 SQLite 文件上跑完整 `add_fact → search/probe/reason → feedback` 链路，测试结束后删除临时库。
- 测试文件放在 `tests/`；`conftest.py` 已提供 hermes 内部模块 stub，并把 `db_path` 指向临时文件，**不要碰真实 `memory_store.db`**。
- **所有测试脚本、试验脚本、可执行验证脚本必须放在 `tests/` 目录内**，不要散落在项目根目录：
  - pytest 自动收集的测试文件统一命名为 `test_*.py`，放在 `tests/` 根下。
  - 非 pytest 的临时/私有试验脚本（如操作真实 DB 的 trial、桌面文件灌库脚本）放在 `tests/scripts/` 子目录，并用 `run_*` 前缀避免被 pytest 自动收集。

## 7. 常见坑

- **HRR 不是语义相似**：HRR 相似度反映的是「用了哪些词/实体重叠」，不是 embedding 意义上的语义近义。别把 HRR 阈值直接套用到语义合并（P1-2）上，需要重新标定。
- **FTS5 rank 是负数**：越小越好；对外暴露前要做归一化或转排名。
- **`search_facts` 会副作用 `retrieval_count += 1`**：P0 探重、GC 内部查询等场景不要调用它，应写独立 SQL。
- **`probe`/`related`/`reason` 当前是全表扫 HRR 向量**：事实量大时要考虑分桶/预过滤，否则性能会崩。
- **`_rebuild_bank` 每次 add/update/remove 都会全量重建 category bank**：高频写入时考虑异步/批量重建。

## 8. 修改后必做

1. 跑通插件加载：`python -c "import holographic"` 不报错。
2. 如果用 pytest：`pytest tests/` 全绿。
3. 检查是否引入了新的常驻进程或外部依赖。
4. 涉及 schema 变更时，更新本文件 §3 状态表。
5. 文档变更同步到 [CHANGELOG.md](CHANGELOG.md)。
