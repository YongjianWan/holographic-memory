# Patch Record

> 记录针对当前代码的补丁、修复与显式不做的替代方案。
> 每个条目写清楚：问题、处置、位置、理由、遗留尾巴。

---

## Patch 1 — HRR search 路 query/fact 编码对齐

**问题**
`search()` 第 86 行用裸 `encode_text(query)` 去比 fact 的 `encode_fact(content, entities)` 向量。
同文件 `probe()` 自己证明了正确写法是 `bind(encode_text(...), ROLE_CONTENT)`。
一个文件里两个方法，probe 对齐了、search 没对齐，是 bug。

**处置**
✅ **已应用**（应用到 RRF 新版 `_hrr_ranking`，不是旧 `search()`）。

**代码位置**
`retrieval.py`：`_hrr_ranking` 方法内

```python
role_content = hrr.encode_atom("__hrr_role_content__", self.hrr_dim)
query_vec = hrr.bind(hrr.encode_text(query, self.hrr_dim), role_content)
```

**理由**
`encode_fact` 把 content bind 到 `ROLE_CONTENT` 再 bundle entity 成分。query 也 bind 到 `ROLE_CONTENT` 后，才和 fact 向量里的 content 成分处于同一空间，similarity 才有意义。

**遗留尾巴**
fact 向量仍是 `content + entities` 的 bundle，query 只对齐 content 成分，其余 entity 成分对 query 是噪声。比裸编码强，但仍是弱信号。
更干净的解法是 unbind 出 content 再比，但实现更复杂（需显式维护 role 结构）。
当前 RRF 共识机制兜底，暂不升级。若实测 HRR 路贡献接近随机，再考虑 unbind 方案。

→ 已记入 `TECH_DEBT.md` L2 债务。

---

## Patch 2 — `fts_rank` 批内相对归一化

**问题**
旧 `_fts_candidates` 把 FTS5 rank 除以本批最大值（`raw_rank / max_rank`），得到批内相对分。
Jaccard 和 HRR 是绝对分，跟一个批内相对分加权，语义不一致。

**处置**
❌ **未应用**。

**理由**
当前实现已替换为 **RRF（Reciprocal Rank Fusion）**，三路直接拿原始名次融合，不再归一化 fts 原始分。
补丁 2 的 `raw / (raw + 1)` 绝对化方案是加权融合的止血补丁；既然 RRF 一步到位，这个补丁就失去意义。

**代码位置**
无。旧 `_fts_candidates` 已被删除， replaced by `_fts_ranking`（只返名次）。

---

## Patch 3 — trust 权重方式

**问题**
确认 trust 是否应该以乘法方式影响排序分。

**处置**
✅ **保持现状，未改动**。

**代码位置**
`retrieval.py`：`search()` 内

```python
trust_boost = 1.0 + 0.2 * (fact["trust_score"] - 0.5)
fact["score"] = rrf_score * trust_boost * recency_boost
```

**理由**
原代码 `score = relevance * trust_score` 已是乘法，与方案 §5 的"乘法 boost"原则一致。
RRF 版本进一步把 trust 改成中心 1.0、±10% 限幅的乘法 boost，避免低 trust 事实被完全压死，同时保证 trust 不压过 RRF 主排序。

---

*Last updated: 2026-06-20*
