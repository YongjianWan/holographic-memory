# Holographic 记忆系统改造方案（完整版 v3.2）

> v3.2 新增三块，都来自「日常用法」对话——你要的不是自我画像图，是「扔东西进来、之后捞回来、还能串起来」：
> ① **输入侧（§3.5）**：文章入口（长文 → 多条 fact）+ 存原文（回看要完整原文，不只是提炼的 fact）。
> ② **P1-4 跨话题串联**：GC 顺手做的「反思」——把你不同项目里同构的偏好串成高阶 observation，
>    **产物喂回 recall 让对话更深，不是给你看的报告**；三条硬约束焊死定位，防它膨胀成「每天写感悟」的吃灰装置。
> ③ 厘清「反思」歧义：对话中涌现的新观点靠 RQ（已有），P1-4 只补「跨你从不同时提及的领域」这一不可替代的部分。
>
> 触发机制（v3.1 定）：hermes 进程内惰性定时器 + 关机积压补漏，非 cron（cron 关机丢拍）。
> 两条正交主线（v3 定）：A 检索质量（RQ/RRF）、B 库卫生（P0/P1/P2）。◆Hindsight = 生产验证的常数。

---

## 0. 核心判断（先读，防止跑偏）

**两条正交的主线，别混：**

| 主线 | 解决什么 | 体感来源 | 对应 |
|---|---|---|---|
| **A. 检索质量** | 每次 search/probe 返回得准不准 | 读路径，日常高频 | **RQ**（§3） |
| **B. 库的卫生** | 库会不会随数据变大退化成垃圾场 | 写路径 + 维护 | **P0/P1/P2**（§4-6） |

v2 只有 B。但 Hindsight 的「optimize for fast reads, heavy lifting at write time」+ 读写比 10:1 这条规律说明：**A 的优先级不低于 B，甚至日常体感更高**——库再干净，检索排序烂，你照样难受。

**两线的共同红线（不可破）：所有 LLM 走一次性 API 调用，系统里不留任何常驻进程。**

否掉 Hindsight 整套架构的真实理由不是「它复杂」，是「它常驻」——Postgres / embedding 服务 / cross-encoder / consolidation_worker / cron 都假设机器 24h 活着，关机即废、启动即工程。Holo 命根子是「关机即文件、开机即用，无启动序列」。

**B 线内部的硬顺序仍在**：先有干净的 fact，才有干净的图。在垃圾库上建图，边跟着垃圾平方膨胀，比不建更糟。所以 B 线内 P0 → P1 → P2 不可跳。**但 A 线（RQ）独立于 B 线，可以随时插队做**，因为它改的是排序算法，不依赖库干不干净。

HRR 是纯数学（SHA-256 确定性相位向量 + 循环卷积 bag-of-words），**不调 embedding 模型**，本身符合红线，不动它。

---

## 1. 现状盘点（已读源码 store.py 578 行 + encode_fact 实现）

| 已有 | 说明 |
|---|---|
| `facts` 表 + HRR 向量(1024d BLOB) | `content` 列有 **UNIQUE 约束** |
| `entities` + `fact_entities` | 已是二部图（fact ↔ entity），`probe`/`reason` 在此之上 |
| FTS5 全文 + Jaccard + HRR **三路检索** | 三路**怎么融合**是关键短板，见 §3 |
| `trust_score` + 非对称反馈(+0.05/-0.10) | 惩罚重于奖励（设计正确） |
| `probe`/`reason`/`related`/`contradict` | 实体召回 / 跨实体 AND / 相关 / 矛盾 |
| `retrieval_count` / `helpful_count` | 使用度计数，GC 与排序都要用 |

**已确认的源码事实：**

1. **`add_fact`（146-189）只精确查重**：`content UNIQUE` + `try/except IntegrityError`，重复时**只返回旧 id，不更新任何字段**。→ 近重复（措辞不同的同一事实）**不触发 except**，全漏进库 = 膨胀真凶。
2. **`search_facts`（191-240）纯 FTS5，不返回相似度数值**，按 `fts.rank` 排序；**有副作用 `retrieval_count += 1`**；带 `trust_score >= ?` 过滤。
3. **`_compute_hrr_vector`（474-496）依赖 entities**：`encode_fact(content, entities, dim)`，entities 来自 `fact_entities`，需 numpy。
4. **`encode_fact`（135-160）确认纯 HRR**：content 与每个 entity 分别 bind 到 role 再 bundle，`encode_atom` 是 SHA-256 确定性向量、`encode_text` 是 bag-of-words。→ **HRR 相似 = 用了哪些词/实体重叠，不是语义相似。**

**◆Hindsight 验证的方向**：它整套「写时做完所有重活、读才快」与本方案 P0/P2「写入时探重/建边」同构——这不是怪招，是记忆系统（读多写少）的正解。可放心。

---

## 2. Hindsight 文档的边界（钉死，防止反复被带跑）

读了它七八份文档，**能用的只有「被生产调出来的常数/判据」，不是架构**。一次性划清：

**◆ 同构可抄（已并入下文对应位置）：**
- entity overlap 用 `tanh(shared×0.5)` 而非线性/sqrt → §6 P2
- 近重复合并：高相似度阈值粗筛 + LLM 读全文细判（默认 0.97 cosine）→ §5 P1
- recency 衰减 `clamp(1-days/365, 0.1, 1)`、boost 用**乘法**不是加法 → §5 P1
- 多路检索用 **RRF 融合**（`Σ 1/(60+rank)`, k=60），且承认无 cross-encoder 时可用 RRF rank 合成分兜底 → §3 RQ

**✗ 异构诱惑（看着好，但全是常驻重活，永远不抄）：**
- PostgreSQL / pgvector / HNSW —— 你是 SQLite，整套不要
- cross-encoder rerank 常驻模型 —— 违反红线；用 RRF 近似（它自己也提供降级）
- 四路检索里的 **semantic（embedding）那路** —— 要常驻 embedding 模型；你用 HRR/FTS5/Jaccard 替代
- observation 自动后台 consolidation —— 常驻 worker；你用「惰性定时器 + 补漏的批 GC」替代（§5）
- reflect / disposition / mental models —— LLM 重活，按需一次性调用即可，不做成它那种系统内建循环

> 规律：Hindsight 给**参数和判据**（它拿百万级 fact 调出来的），不给**架构**（它的架构是你养不起的）。下次再出现新 Hindsight 文档，按这条筛。

---

## 3. RQ — 检索质量：RRF 融合三路（A 线，独立可先做）

**这是 v3 新增的第二主线，也可能是对你日常体感提升最大的一块。**

**问题**：Holo 有 FTS5 / Jaccard / HRR 三路，但**怎么合成最终排序？** 如果只是简单并集或朴素加权，就是短板——三路的分根本不可比（FTS5 rank、Jaccard 词重叠比例、HRR 向量相似度三个量纲完全不同），加权等于拿苹果加橘子。

**◆Hindsight 的答案：RRF（Reciprocal Rank Fusion）。** 不用原始分，只用**各路的排名位次**：

```
score(fact) = Σ_i  1 / (k + rank_i(fact))      # k = 60
```
- 每路各自排序，取每个 fact 在各路里的**名次**（1-indexed），不碰原始分
- 在多路都靠前的 fact 得分高（共识）→ 自然奖励「既词面命中又向量相关」的
- k=60 是平滑常数，防止头部一两条垄断
- **量纲问题彻底消失**：只比名次，不比分。FTS5 的 rank 和 HRR 的 cosine 不再需要校准

**为什么这条独立于 P0/P1/P2**：它改的是**读时的排序算法**，跟库干不干净无关。库再脏，RRF 也能让排序更准；库再干净，朴素加权也照样排得烂。所以 **RQ 可以最先做，不必等 GC**。

**降级合理性**：Hindsight 全套有 cross-encoder rerank（读全文 query-fact 配对打分）压在 RRF 之上。你**不上 cross-encoder**（常驻模型，违反红线）。文档确认：无 cross-encoder 时，它自己也退化为「RRF rank 映射到 [0.1,1.0] 的合成分」。→ **你停在 RRF 这一层是它官方认可的降级，不是偷工减料。**

**实现**：纯算法、零依赖、零 LLM。三路各取 top-N 名次 → 套 RRF 公式 → 合并排序。唯一注意：HRR 那路要算相似度排名，调用已有的 HRR 比对；FTS5 那路用 `fts.rank`；Jaccard 那路用词重叠比。

**RQ 与 trust 的关系**：RRF 出排序后，可叠一层 trust/recency 的**乘法** boost（见 §5 的设计），让低信任/过期 fact 适度降权——但 boost 是次要信号，乘法保证它不压过 RRF 的主排序。

---

## 3.5 输入侧 — 文章入口 + 存原文（喂进来的不只是 fact）◆新增

现状假设输入是 auto_extract 抽好的细 fact。但你的真实用法是**「把整篇文章/整段聊天扔给它，帮我提炼」**——输入是整篇。补两件，都在写入层，跟 P0 同层：

**一、文章入口（长文档 → 多条 fact）** ◆Hindsight=chunk+extract
加一个「喂文章」的入口，不只是「喂事实」：
```
retain_document(raw_text):
    facts = LLM 提炼(raw_text)        # 一篇 → 多条 fact，一次性 API
    for f in facts:
        add_fact(f)                    # 各自走 P0 探重
```
这是你「帮我提炼」的落点。提炼粒度走原子事实（细），别整段塞进一条 fact——粒度粗，P0 探重和 P2 建边都失准（前面已论证）。

**二、存原文（回看要看完整的，不是干巴巴的 fact）** ◆Hindsight=chunks
你说「我们重新回看那篇文章」——要看的是**当时那篇**，不是提炼后的 fact。但现在只存 fact，原文丢了，回看回不了完整。所以 retain 一篇时，**原文也存一份，关联到提炼出的那些 fact**：
- 新增一张 `documents`（或 `chunks`）表：`doc_id, raw_text, source, created_at`
- `facts` 加一列 `source_doc_id`（nullable，外键 → documents）
- recall 时默认返回提炼的 fact；要「回看完整」时按 `source_doc_id` 拉回原文

⚠️ 存原文走真 migration（加表 + 加列），不删库（§7 铁律）。原文是不可再生数据，存之前先 backup。

**这两件合起来 = 你那段话的主线**：扔文章 → 提炼成 fact（一）+ 留原文（二）→ 几天后模糊一问 → RRF 捞回（§3）→ 要细节就按 source_doc_id 调原文。**全是已有部件 + 两个入口，没有新结构。**

---


**工作量已定**：在 `add_fact` 的 **INSERT 之前**插 `_find_near_duplicate` + `_merge_into`。原 except 块保留作精确兜底。

**位置纠正（v1 错）**：探重必须在 INSERT **之前**——近重复不触发 IntegrityError，进不了 except。

```python
def add_fact(self, content, category="general", tags=""):
    # 新增：INSERT 之前先探【词面】近重复
    dup_id = self._find_near_duplicate(content)
    if dup_id is not None:
        return self._merge_into(dup_id, content, tags)
    # 原逻辑：精确撞车兜底，保留
    try:
        cur = self._conn.execute("INSERT INTO facts (...) VALUES (...)", (...))
        self._conn.commit()
        fact_id = cur.lastrowid
        # ... 抽 entity / 算 HRR 等原有后续 ...
        return fact_id
    except sqlite3.IntegrityError:
        row = self._conn.execute("SELECT fact_id FROM facts WHERE content = ?", (content,)).fetchone()
        return int(row["fact_id"])

def _find_near_duplicate(self, content):
    # 1. FTS5 粗筛候选 —— 抄 search_facts 的 SQL，但两处改动：
    #    a.【删 retrieval_count += 1】否则探重灌高热度，污染 P1 的 trust 衰减信号
    #    b.【去掉 trust_score >= ? 过滤】探重查全量，低 trust 的重复也得探出来合并
    # 2. 候选在 Python 层算 Jaccard 词重叠
    # 3. Jaccard > 阈值（起步 0.8，按实际调）→ 返回 fact_id；否则 None
    # ❌ 不碰 HRR：新 fact 此刻没 entities，算不出同口径向量；
    #    且 HRR 抓的也是词面/实体重叠（encode_atom 是 SHA-256 bag-of-words），与 FTS5+Jaccard 同类信号，加它冗余。
    #    语义近重复 HRR 也抓不到 → 留给 P1。
    ...

def _merge_into(self, existing_id, new_content, new_tags):
    # 选哪条 content 留下 —— 本地打分，不掏 LLM：
    #   score = (实体数 + 含数字/版本/日期的命中数) / log(len(content))
    #   · 实体数：fact_entities COUNT（多 = 更具体）
    #   · 数字/版本/日期：正则命中（"2026-06-17 发布" > "最近发布"）
    #   · 分母 log(长度)：长内容不被过度惩罚，但啰嗦仍扣分
    # retrieval_count 累加；trust 取 max；tags 去重并集；刷 updated_at
    # ⚠️ 若改写 content：先查会不会撞别行 UNIQUE，撞了就别改 content 只更新其余字段
    # 注意：merge 只解决【重复】不解决【烂】。两条都烂时它选没那么烂的，烂的还留着——质量归 P1 trust 衰减，别让 merge 兼职质检。
    ...
```

**P0 三条硬约束（源码逼出来的）：**
- **A. FTS5 粗筛 + Jaccard 精判，不用 HRR**（entities 缺席 + 同类信号冗余）。语义近重复**故意留给 P1**。
- **B. 探重的 FTS5 查询必须删 `retrieval_count += 1` 且去 trust 过滤**（否则污染 GC 信号 / 漏掉低分重复）。
- **C. merge 改写 content 防 UNIQUE 冲突**。

定位：P0 是第一道防线，轻快、写入热路径不卡，挡掉垃圾大头（同 session 反复抽、措辞微调）。

---

## 5. P1 — 批 GC：惰性定时器 + 补漏（B 线兜底）

**触发机制的正名（这一版想清楚了）：你要的不是 cron，是「周期性醒来查时间戳 + 关机积压补漏」。**

把「开机触发」这个名字扔掉，它太窄、且误导。真正的机制：**一个轻量定时器周期性醒来（如每 2h），醒来第一件事是查时间戳——距上次 GC 超阈值才干活，没超就立刻睡回去。** 触发点不只开机，任何「系统活着时会反复发生的事件」都行，叠加越多越不容易漏：进程内定时器醒来 / hermes 启动 / session 开始 / retain 之后。

**它和 cron 的决定性区别——也是你的作息为什么必须用它：**

| | 真 cron（到点跑） | 惰性定时器 + 补漏（采用） |
|---|---|---|
| 关机那一拍 | **丢失**，不补 | **延后**，下次醒来补 |
| 触发依据 | 钟点（12:00） | 时间戳（距上次多久） |
| 你休息 3 天关机 | 丢 3 拍，且下个 12:00 可能又没开机 → 丢失累积 | 这 3 天定时器没机会醒（机器关着），但回来开机后第一次醒来发现「距上次 72h」→ 一次补齐。**零丢失，只延后** |
| 常驻 | 独立调度器一直等着 | 无独立常驻件（见下） |

**关键认识**：会出现「没触发」的唯一原因是**关机**。机器开着时真 cron 不存在「没触发」。所以你说的「没触发就等下次一块补」「没触发就过 2h 再试」——这两句的本质是**「感知到错过了要补」**，而 cron 不补、惰性定时器才补。你已经自己推出了正确机制，只是还管它叫 cron。

```python
# hermes 进程内的惰性定时器（不是 OS cron）
every ~2h (and on hermes startup, on session start):
    last_gc = read(cache_metadata['last_gc_at'])
    if now - last_gc > 阈值:                 # 阈值见下，宁短勿长
        spawn_async(run_gc)                  # 异步非阻塞，别挡前台干活
        write(cache_metadata['last_gc_at'] = now)
    # 没超阈值 → 立刻睡回去，秒退（GC 幂等：没 unconsolidated fact 就空跑返回）
```

**阈值怎么定（按你真实作息：间隔不固定，但工作日中午必在线）：**
- 锚点是「工作日中午一定开机」这个保底点。只要它能稳定触发，就永不丢更新。
- 阈值设成**比两次中午的最短间隔短一截 → 6h 左右**。宁可偶尔一天空跑两次（幂等，≈0 成本），别因卡边界漏掉中午那次（漏 = 那天的收敛没做）。**不对称，所以往短设。**

**实现选型——为什么是「进程内定时器」而不是 OS cron/anacron：**
- 你描述的「补漏」行为，Linux 上恰好有现成的：**`anacron`**（专为非 24h 开机的机器设计，记时间戳、开机补跑）。**注意：是 anacron 不是 cron**——`cron` 到点跑、关机丢拍，正是你要避开的。
- 但 anacron / OS cron 都是**独立于 hermes 的常驻调度件**，跟你「系统里不留常驻进程、无外部依赖」的红线擦边（多一个要配置、会失灵、平台相关的东西）。
- **采用：把定时器做进 hermes 进程内**（运行时起个后台 asyncio 定时器，hermes 在跑就周期查、hermes 没跑就靠下次启动兜底）。**没有任何独立于 hermes 的常驻件**，最干净，跨平台，符合一路坚持的无依赖原则。

**休息后首次开机的积压**：你 sprint 3-on-1-off，休息几天回来，GC 要一次收敛多日积压（fact 多 + LLM 语义收敛），这次明显慢。所以「异步非阻塞」不是可选项是必须——回来开机后 GC 在后台慢慢补，前台照常开工，别让它卡住你。



**1. entity 归一化（治碎裂）← 立即可动的切入点，见 §7**
遍历 `entities`，编辑距离 + HRR 相似度聚类近义节点，合并：保留主节点、其余进 `aliases`、重指 `fact_entities` 外键。把「K2.7 四兄弟」压回一个节点。纯本地。
**为什么这是地基**：entity 是 HRR 向量的一半成分（`encode_fact` 把 entity bind 进向量）。entity 碎裂 → 同一事实的 HRR 向量被拉散 → `related`/`probe`/§3 的 HRR 那路全部失准。**也是 §6 P2 边的来源**。P1 这步没做好，HRR 检索和 P2 的边全是脏的。

**2. 语义合并 + 时间线收敛（治堆积，P0 的补集）** ◆Hindsight
P0 只挡词面，两类东西漏到这里，都得 LLM：
- **措辞不同的同一事实**（近重复）
- **非字面矛盾的时间线**——四条都不重复、都不字面冲突，但合起来有「当前真相 + 演化史」。例：①Mia 入职初级 ②升高级 ③跳槽 Quantum 任 principal ④回原公司任 principal。问「Mia 现在在哪、什么角色」，答案要收敛成「现在在原公司，principal（沿用 Quantum 时的角色）」。这靠去重/相似度做不到，必须 LLM 理解时序。

**两段式（抄 Hindsight，不是纯靠相似度）：**
- 相似度**粗筛**疑似对/簇（Hindsight 默认 cosine ≥ **0.97**；你用 HRR 相似度替 cosine，**阈值必须重标**——HRR 分布与 embedding cosine 不同，0.97 不能直接搬，自己测）
- 一次 LLM 调用**读全文细判**：是合并、还是收敛成「当前态+演化史」、还是保持分开（差一个数字/否定/实体的不能合）。一次性 API。
**收敛产物保留演化史**，不是只留终态——「Mia 现在 principal（曾在 Quantum）」比「Mia 是 principal」有用，能防 agent 推荐过时信息。
⚠️ 合并/收敛改写 content 受 UNIQUE 约束，同 P0-C。

**3. trust 衰减（治长期腐烂）** ◆Hindsight
```python
recency = clamp(1.0 - days_since_retrieved/365, 0.1, 1.0)   # 线性衰减，地板 0.1
fact.trust 按 recency 调整
# 低于阈值的：list 不返回 / remove
```
**地板 0.1 重要**：再老也不归零，留翻盘余地，不因一时没用就被删。
依赖 P0-B：retrieval_count 不被探重污染，信号才可信。

**4. 跨话题串联（GC 顺手做的「反思」，定位焊死）** ◆新增
GC 跑批时，除合并近重复（P1-2），再让 LLM 做一次**跨话题串联**：把你**不同领域里同构的东西**连起来，存成一条高阶 observation。
例：你做 Holo 要「极简无依赖」、做 Scout 要「事件驱动不空转」、拒绝 Hindsight 因为「常驻」——这三条来自三个不同项目、你从不同时提及，对话中（受当前话题局限）几乎碰不到一起。GC 离线把全库放一起，能撞出「这三个是同一个审美：拒绝常驻、拒绝空转」。这是对话内涌现**做不到**的部分——跨越你从不同时聊的领域。

**这一项极易膨胀成「系统每天给你写感悟」那种吃灰装置，所以定位用三条硬约束焊死，违反任一条就是跑偏：**
- **① 产物喂回 recall，不是给你看的报告。** 串联出的 observation 进库，下次对话时被 recall 捞进上下文，让我们**聊得更深**——你不必专门去读它。它服务于「聊着聊着冒出好观点」，不是一份要你阅读的产出。一旦开始生成「给用户看的周报/感悟」，就是博客文那坨东西，停。
- **② 搭在 GC 的惰性定时器上，绝不独立常驻/定时。** 不新起任何进程。GC 什么时候跑它什么时候跑，GC 不跑它就不跑。
- **③ 必须落地为「跨领域的结构相似」，不是凭空生成抽象金句。** 每条串联 observation 必须指向**具体的几条源 fact**（像 Hindsight observation 的 proof count）。连不到具体源 fact 的、纯漂亮话的（「宇宙在优化自己」那种），丢弃。离线空想最易滑向漂亮废话，这条是防滑闸。

**与 P2 的分工**：P2 建的是「fact 之间共享 entity」的边（同领域、字面相关）；P1-4 抓的是「跨领域、字面不相关但结构同构」的联系——P2 的 shared-entity 边天然抓不到（不同项目的 fact 往往不共享 entity）。两者互补，不重叠。

**◆ 乘法 boost 原则（贯穿 §3 RQ 与本节）**：当要把 trust/recency/命中数揉成排序分时，用**乘法**不是加法——`final = base × recency_boost × ...`，每个 boost 中心 1.0、用 α 限幅（Hindsight 用 ±10%）。理由：加法会让一条勉强相关的 fact 靠 recency 直接盖过高相关的；乘法让次要信号永远压不过主信号。

**工程注意**：库大 + LLM 合并会让 GC 耗时。必须异步后台跑，开机后照常用，维护别阻塞干活。

---

## 6. P2 — fact_edges（B 线，只有 P0/P1 让库干净后才碰）

**需求已定性**：你要的是「沿关联找相关 fact 簇」，**不是**「机器推理 A supports B 有向类型关系」。判据：你想要 graph 检索（Hindsight 的 graph 那路证明值得做），但始终给不出一个必须靠有类型边才能答的查询。
→ **P2 做，但砍成最小形态：shared-entity 关联边 + CTE 多跳。有类型边降级为 P2.5 默认不做。**

**表结构**（workspace-bridge 的 `edges` 搬来简化，列留全为 P2.5 预备）：
```sql
CREATE TABLE IF NOT EXISTS fact_edges (
  source_fact_id    INTEGER NOT NULL,
  target_fact_id    INTEGER NOT NULL,
  edge_type         TEXT NOT NULL DEFAULT 'related',          -- P2 阶段恒为 'related'
  confidence        REAL NOT NULL DEFAULT 1.0,                -- = 关联强度
  resolution_method TEXT NOT NULL DEFAULT 'shared-entity',    -- P2 恒为此；P2.5 才有 'llm'
  created_at        TIMESTAMP,
  PRIMARY KEY (source_fact_id, target_fact_id, edge_type)
);
CREATE INDEX idx_fact_edges_source ON fact_edges(source_fact_id);
CREATE INDEX idx_fact_edges_target ON fact_edges(target_fact_id);
```

**建边：纯本地、零 LLM、确定性。** ◆Hindsight 的 tanh
```
新 fact 写入并抽完 entity 后（时序：在 entity 就位之后，不是 P0 探重那一刻）:
    候选 = 查 fact_entities 找共享 entity 的 fact          # 现成倒排，缩范围，不全库两两比
    for 候选 c:
        shared = |新fact.entities ∩ c.entities|
        conf   = tanh(shared × 0.5)                        # ◆ 不用 sqrt 归一化
        if conf > 阈值:
            写 fact_edges(新fact, c, 'related', conf, 'shared-entity')
```
**为什么 tanh 而非我原来的 sqrt**：你库里「Aiden」这个实体几乎挂在每条 fact 上（整库都关于你）。原始共享数无上界，高频实体会把一切连成一团。`tanh(shared×0.5)` 自然饱和——头几个共享权重大（1→0.46, 2→0.76, 3→0.91），之后边际递减，把超高频实体的拉扯压住。这是 Hindsight 拿真实高 fan-out 实体（"user"）调出来的，正好治你的「Aiden 无处不在」。

**依赖闭环**：边来自 entity，entity 被 P1 归一化清干净 → **P1 不做好，P2 的边全脏**。P1 → P2 再次自证。

**多跳**：SQLite 递归 CTE 沿 fact_edges 走 N 跳，无需图库——workspace-bridge 的 `findAffectedHttpRoutes()` 已验证。
**显式不做**：link expansion、RRF-on-graph、cross-encoder（Hindsight 重型版，与红线冲突）。

### P2.5 —（可选，默认不做）LLM 有类型边
**触发条件**：当且仅当你真出现一个查询，必须机器知道「A 反驳 B」「A 是 B 前提」这种有向类型关系才能答。在那之前不写一行。
做的话：`edge_type` 扩 supports/contradicts/causes/depends-on、`resolution_method='llm'`；共享 entity 候选 → 一次 LLM 判类型（一次性 API）。
**强弱边别混查**（workspace-bridge 评审教训：import 边和 route 伪节点混表，CTE 要额外过滤）。靠 `resolution_method`+`confidence` 区分，难受就分表。
**记忆边会错且无自愈——workspace-bridge 经验唯一救不了的地方**：LLM 判的 supports 边主观、会错、一直污染链式查询。`trust_score` 是给 fact 不是给边的。必须给边单配：查询 `WHERE confidence > 0.6` 过滤，或复用 `fact_feedback` 非对称反馈给边评分。

---

## 7. 贯穿性约束：禁止删库重建

workspace-bridge 改 schema 靠 `CACHE_VERSION` 不匹配就**删库重建**——它敢，因为数据可重新 parse 生成。

**Holo 绝对不能学。** facts 是**唯一来源、不可再生**，删库 = 记忆永久丢失。所以：
- 任何 schema 变更（加列、建 fact_edges、改 entities）走**真 migration**：`ALTER TABLE` / 建新表 / 数据迁移，**绝不 DROP + CREATE**。
- 加 schema 版本号 + 升级脚本表，按版本增量升级。
- 动手前先 **backup .db**，这是不可再生数据的底线。

---

## 8. 落地顺序与优先级（v3 重排）

两条线交织，不是单一队列。按**体感收益 / 风险**排：

| 优先 | 做什么 | 属线 | 依赖 | 理由 |
|---|---|---|---|---|
| ★1 | **RQ：RRF 融合三路** | A | 无 | 纯算法零依赖，直接改善每次 search/probe，日常高频体感最大 |
| ★1 | **P1-1：entity 归一化** | B | 无 | 零风险、清已存在的垃圾；且是 HRR/P2 的地基；顺手搭 P1 的定时器壳 |
| ★1 | **输入侧：文章入口 + 存原文** | 输入 | 无 | 你日常用法的主线（扔文章→提炼→回看）；存原文走 migration 不删库 |
| ★2 | **P0：写入探重** | B | 无 | 源码全确认，热路径小改，在源头挡新垃圾 |
| ★3 | **P1-2/3：语义合并 + trust 衰减** | B | P1 壳 | 往已搭好的壳里塞，清存量 + 防腐烂 |
| ★3 | **P1-4：跨话题串联（反思）** | B | P1 壳 | 搭 GC 定时器；产物喂回 recall 让对话更深；三约束焊死防膨胀 |
| ★4 | **P2：shared-entity 边 + CTE** | B | P0+P1 干净库 | 库干净才建得出干净的图 |
| 可选 | **P2.5：LLM 有类型边** | B | 出现真实查询才做 | 默认不做 |

**两个 ★1 不互卡，谁先看你今天想写排序算法还是写维护框架。** RQ 改读、P1-1 改写，互不干涉。

**待确认螺丝：无。** add 查重方式（精确，不更新）、HRR 实现（纯数学）、search_facts 全貌（纯 FTS5 + 两个副作用）、P2 形态（穷人版图）全部拧完。剩下是写代码 + 自己测几个阈值（Jaccard 0.8、HRR 语义合并阈值、tanh conf 阈值、trust 删除阈值——这四个数都得在你真实数据上标，文档给的是起点不是终点）。

---

## 附：三个 Hindsight 的定位（终版，别再混）

| | 给你什么 | 怎么用 |
|---|---|---|
| 重型 Hindsight（SaaS 那个：Redis/Celery/Traefik/OAuth） | 零 | 别碰 |
| slim Hindsight（pg0/local 默认/retain-recall-reflect） | **生产验证的常数与判据** + 证明 graph/entity-resolve/写时重活有价值 | 抄 §2 列的四个常数；看模块边界；**不抄架构** |
| **workspace-bridge（你自己的）** | 同物种的轻量图实现（SQLite/内存图/CTE） | **抄代码模式**（fact_edges、CTE 多跳） |

> 那篇「holographic mind」博客：把 bug（卡 15 分钟）浪漫化成觉醒、把常驻 cron 蒸馏吹成「代谢」。本方案要它的清理**需求**，不要它的叙事，也不要它的脆弱——落成「惰性定时器+补漏的确定性批处理」+「RRF 确定性排序」。
