"""Entity extraction, resolution, and name-matching helpers.

Entities are the structural nodes of the memory graph. Keeping the regex
rules, stop-word lists, and entity CRUD helpers in this module means
``store.py`` does not need to own every detail of how a raw string becomes
an ``entity_id``.

Why this split matters:
- Entity logic is self-contained: it only needs ``holographic.py`` for
  tokenisation and ``sqlite3`` for persistence.
- It is exercised independently by write-time extraction, normalisation,
  and retrieval pre-filtering.
- It is the easiest place to add new languages or domain-specific entity
  patterns without touching the storage layer.
"""

from __future__ import annotations

import difflib
import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

try:
    from . import holographic as hrr
except ImportError:  # pragma: no cover - supports standalone import during dev
    import holographic as hrr  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------

# Capitalised multi-word phrases: "John Doe", "Open AI".
_RE_CAPITALIZED = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')

# Quoted terms are strong entity signals: "Python", 'pytest'.
_RE_DOUBLE_QUOTE = re.compile(r'"([^"]+)"')
_RE_SINGLE_QUOTE = re.compile(r"'([^']+)'")

# Explicit aliases: "Guido aka BDFL" -> two entities.
_RE_AKA = re.compile(
    r'(\w+(?:\s+\w+)*)\s+(?:aka|also known as)\s+(\w+(?:\s+\w+)*)',
    re.IGNORECASE,
)

# Chinese quoted terms: 「全息记忆」 / 『Python』
_RE_CHINESE_QUOTE = re.compile(r'[「『]([^」』]+)[」』]')

# Common Chinese/technical suffixes that strongly signal a named entity.
_CHINESE_TECH_SUFFIXES = (
    "系统|平台|框架|库|工具|引擎|模型|算法|接口|服务|应用|程序|数据库|模块|组件|"
    "函数|类|方法|变量|参数|配置|文件|目录|路径|协议|格式|标准|语言|环境|"
    "测试|生产|开发|部署|发布|版本|分支|提交|合并|构建|编译|打包|镜像|容器|"
    "节点|集群|网络|服务器|客户端|网关|代理|缓存|会话|令牌|密钥|证书|签名|"
    "密码|认证|授权|审计|日志|监控|告警|通知|消息|邮件|队列|主题|路由|"
    "工作流|流水线|调度|执行|处理|计算|生成|渲染|转换|提取|加载|编码|解码|"
    "压缩|解压|加密|解密|分词|标注|分类|聚类|回归|预测|推荐|检索|排序|"
    "评估|度量|指标|统计|图表|报告|查询|搜索|索引|事务|锁|隔离|一致性|"
    "可用性|分区容错|扩展|伸缩|备份|恢复|迁移|同步|复制|分片|分区|"
    "记忆|内存|存储|事实|实体|向量|相似度|阈值|置信度"
)
_RE_CHINESE_TECH = re.compile(
    rf'(?<![A-Za-z0-9_\-])([\u4e00-\u9fffA-Za-z0-9_\-]{{1,15}})({_CHINESE_TECH_SUFFIXES})(?![A-Za-z0-9_\-])'
)

# Bare acronyms (HRR, FTS5) and dotted tech tokens (Vue.js, Node.js).
_RE_ACRONYM = re.compile(r'\b([A-Z]{2,}\d*)\b')
_RE_DOTTED_TECH = re.compile(r'\b([A-Za-z][A-Za-z0-9]*\.[A-Za-z0-9]+)\b')

# English stop-words for Jaccard filtering during candidate discovery.
# These are too generic to be useful entity signals on their own.
_ENGLISH_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "can", "this", "that", "these",
    "those", "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
    "us", "them", "my", "your", "his", "its", "our", "their", "am", "s", "t",
})

# Generic Chinese prefixes that should not stand alone as an entity.
_CHINESE_STOPWORDS = frozenset({
    "这", "那", "此", "该", "一", "一个", "一种", "一些", "某些", "某个", "这个",
    "那个", "这些", "那些", "所有", "全部", "部分", "任何", "每个", "各", "本",
    "上", "下", "前", "后", "左", "右", "中", "内", "外", "里", "间", "边", "面",
    "方", "头", "尾", "部", "侧", "端", "项", "条", "件", "个", "种", "类", "份",
    "张", "本", "套", "组", "批", "堆", "串", "行", "列", "排", "层", "级", "等",
    "整", "整个", "大", "小", "高", "低", "长", "短", "多", "少", "好", "坏", "新",
    "旧", "老", "初", "主", "次", "正", "副", "假", "真", "虚", "实", "公", "私",
    "同", "异", "单", "双", "复", "全", "半", "微", "巨", "重", "轻", "强", "弱",
    "快", "慢", "早", "晚", "近", "远", "先", "后", "未", "已", "将", "现", "原",
    "当", "每", "某", "他", "她", "它", "其", "之", "所", "与", "及", "或", "且",
    "而", "但", "因", "为", "于", "以", "从", "到", "向", "往", "在", "对", "把",
    "被", "让", "给", "跟", "比", "除了", "关于", "根据", "按照",
})

# Quoted strings often capture whole phrases/sentences (e.g. a task body) rather
# than named entities. Reject candidates that are too long or contain sentence-
# level punctuation. This is a write-time guard; existing dirty entities still
# need a normalisation pass.
_MAX_QUOTED_ENTITY_LEN = 20
_RE_SENTENCE_PUNCT = re.compile(r"[。！？；，、：,;:!?\n\r]")

# Dates, versions, and bare digit sequences all count toward content specificity.
# Version-like tokens treat '.', '_', '-' as equivalent separators so that
# "K2.7", "K2_7", and "K2-7" share the same numeric signature.
_RE_NUMERIC_DETAIL = re.compile(
    r'\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|(\d+(?:[._-]\d+)+)|(\d+)',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------

def _extract_numeric_signature(text: str) -> set[str]:
    """Extract normalised numeric/date/version markers from text.

    Version-like tokens with '.', '_', or '-' separators are normalised to
    use '.', so "K2_7" and "K2.7" produce the same signature.
    """
    sig: set[str] = set()
    for m in _RE_NUMERIC_DETAIL.finditer(text):
        if m.group(1):
            # Version-like: normalise separators.
            sig.add(m.group(1).replace("_", ".").replace("-", "."))
        elif m.group(2):
            sig.add(m.group(2))
        else:
            sig.add(m.group(0))
    return sig


def _numeric_hit_count(text: str) -> int:
    """Count distinct numeric/date/version tokens in text."""
    return len(_extract_numeric_signature(text))


def numeric_signature(text: str) -> frozenset[str]:
    """Return the set of numeric/date/version markers in text.

    Used as a gate in entity clustering: two names whose numeric signatures
    differ are likely a series-vs-version or version-vs-version relationship,
    not lexical variants of the same entity.
    """
    return frozenset(_extract_numeric_signature(text))


def content_specificity(content: str, entity_count: int) -> float:
    """Higher = more specific content. Used when merging near-duplicate facts.

    Prefers content with linked entities and numeric details, while lightly
    penalising overly long prose.
    """
    content = content.strip()
    if not content:
        return 0.0
    length = max(len(content), 10)
    return (entity_count + _numeric_hit_count(content)) / math.log(length)


def _split_aliases(aliases: str | None) -> list[str]:
    """Split a comma-separated alias string into a list."""
    if not aliases:
        return []
    return [a.strip() for a in aliases.split(",") if a.strip()]


def entity_specificity(name: str) -> int:
    """Score entity name specificity: higher = more specific.

    Prefers names with version/digit markers and longer forms, so that
    "K2.7" wins over "K2" even if the shorter name has more links.
    """
    stripped = name.strip()
    if not stripped:
        return 0
    digit_count = sum(1 for c in stripped if c.isdigit())
    punct_count = sum(1 for c in stripped if not c.isalnum() and not c.isspace())
    return digit_count * 2 + punct_count + len(stripped)


class _UnionFind:
    """Simple union-find for entity clustering."""

    def __init__(self, items: list[int]) -> None:
        self._parent: dict[int, int] = {item: item for item in items}

    def find(self, item: int) -> int:
        parent = self._parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]  # path compression
            item = parent[item]
        return item

    def union(self, a: int, b: int) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a != root_b:
            self._parent[root_b] = root_a


def entity_names_match(
    name_a: str,
    name_b: str,
    edit_threshold: float,
    token_threshold: float,
) -> bool:
    """Return True if two entity names are near-duplicates.

    A numeric/date/version gate runs before any merge decision: if the two
    names carry different numeric signatures, they are treated as distinct
    series/version entities even when their strings are similar.
    """
    if name_a.lower() == name_b.lower():
        return True

    # Numeric signature gate: "K2" vs "K2.7" or "Python" vs "Python 3.12"
    # are hierarchical relationships, not writing variants.
    sig_a = numeric_signature(name_a)
    sig_b = numeric_signature(name_b)
    if sig_a or sig_b:
        if sig_a != sig_b:
            return False

    a_lower = name_a.lower()
    b_lower = name_b.lower()

    # Edit distance similarity via difflib.
    edit_sim = difflib.SequenceMatcher(None, a_lower, b_lower).ratio()
    if edit_sim >= edit_threshold:
        return True

    # Token overlap.
    tokens_a = set(re.findall(r"[a-z0-9]+", a_lower))
    tokens_b = set(re.findall(r"[a-z0-9]+", b_lower))
    if not tokens_a or not tokens_b:
        return False
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    token_sim = intersection / union if union else 0.0
    return token_sim >= token_threshold


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_entities(text: str) -> list[str]:
    """Extract entity candidates from text using simple regex rules.

    Rules applied (in order):
    1. Capitalised multi-word phrases  e.g. "John Doe"
    2. Double-quoted terms             e.g. "Python"
    3. Single-quoted terms             e.g. 'pytest'
    4. AKA patterns                    e.g. "Guido aka BDFL" -> two entities
    5. Chinese quoted terms            e.g. 「全息记忆」
    6. Chinese/English + tech suffix   e.g. "公文写作系统", "Vue.js"
    7. Acronyms / dotted tech tokens   e.g. "HRR", "FTS5"

    Quoted candidates are rejected if they look like a phrase or sentence
    rather than a named entity (too long or containing sentence punctuation).
    Chinese suffix candidates are rejected if the prefix is only stop-words.

    Returns a deduplicated list preserving first-seen order.
    """
    seen: set[str] = set()
    candidates: list[str] = []

    def _add(name: str) -> None:
        stripped = name.strip()
        if stripped and stripped.lower() not in seen:
            seen.add(stripped.lower())
            candidates.append(stripped)

    def _looks_like_phrase_not_entity(s: str) -> bool:
        if len(s) > _MAX_QUOTED_ENTITY_LEN:
            return True
        if _RE_SENTENCE_PUNCT.search(s):
            return True
        return False

    def _prefix_is_stopwords_only(prefix: str) -> bool:
        """Return True if every character in prefix is a stop-word token.

        We treat each CJK character as its own token; latin tokens are split
        on whitespace. The goal is to reject candidates like "这个系统".
        """
        tokens: list[str] = []
        for token in re.split(r"\s+", prefix.strip()):
            if not token:
                continue
            # Split contiguous CJK characters so "这个" -> ["这", "个"].
            chars = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_\-]+", token)
            tokens.extend(chars)
        if not tokens:
            return True
        return all(t in _CHINESE_STOPWORDS for t in tokens)

    for m in _RE_CAPITALIZED.finditer(text):
        candidate = m.group(1)
        if len(candidate) <= _MAX_QUOTED_ENTITY_LEN:
            _add(candidate)

    for m in _RE_DOUBLE_QUOTE.finditer(text):
        candidate = m.group(1)
        if not _looks_like_phrase_not_entity(candidate):
            _add(candidate)

    for m in _RE_SINGLE_QUOTE.finditer(text):
        candidate = m.group(1)
        if not _looks_like_phrase_not_entity(candidate):
            _add(candidate)

    for m in _RE_AKA.finditer(text):
        _add(m.group(1))
        _add(m.group(2))

    # Chinese quoted terms.
    for m in _RE_CHINESE_QUOTE.finditer(text):
        candidate = m.group(1)
        if not _looks_like_phrase_not_entity(candidate):
            _add(candidate)

    # Chinese/English tokens followed by a tech suffix.
    for m in _RE_CHINESE_TECH.finditer(text):
        prefix = m.group(1)
        suffix = m.group(2)
        if not _prefix_is_stopwords_only(prefix):
            _add(prefix + suffix)

    # Acronyms and dotted tech tokens.
    # Acronyms that are substrings of already-captured entities (e.g. "AI"
    # inside "Open AI") are skipped to avoid duplicate fragments.
    seen_lower_str = "".join(seen)
    for m in _RE_ACRONYM.finditer(text):
        acronym = m.group(1)
        if f" {acronym.lower()} " not in f" {seen_lower_str} ":
            _add(acronym)
    for m in _RE_DOTTED_TECH.finditer(text):
        _add(m.group(1))

    return candidates


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def resolve_entity(
    conn: sqlite3.Connection, name: str, *, commit: bool = True
) -> int:
    """Find an existing entity by name or alias (case-insensitive) or create one.

    Returns the entity_id.
    """
    name_lower = name.strip().lower()

    # Exact name match (case-insensitive, no LIKE wildcards).
    row = conn.execute(
        "SELECT entity_id FROM entities WHERE LOWER(name) = ?", (name_lower,)
    ).fetchone()
    if row is not None:
        return int(row["entity_id"])

    # Search aliases — aliases stored as comma-separated.
    # Escape LIKE wildcards in the input to avoid '_' matching any character.
    safe_name = name_lower.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    alias_row = conn.execute(
        f"""
        SELECT entity_id FROM entities
        WHERE ',' || LOWER(aliases) || ',' LIKE '%,' || ? || ',%' ESCAPE '\\'
        """,
        (safe_name,),
    ).fetchone()
    if alias_row is not None:
        return int(alias_row["entity_id"])

    # Create new entity.
    cur = conn.execute("INSERT INTO entities (name) VALUES (?)", (name,))
    if commit:
        conn.commit()
    return int(cur.lastrowid)  # type: ignore[return-value]


def resolve_entity_id(conn: sqlite3.Connection, name: str) -> int | None:
    """Find an existing entity by name or alias (case-insensitive).

    Returns the entity_id, or None if no matching entity exists.
    Read-only variant of resolve_entity: it never creates a new row.
    """
    name_lower = name.strip().lower()

    row = conn.execute(
        "SELECT entity_id FROM entities WHERE LOWER(name) = ?", (name_lower,)
    ).fetchone()
    if row is not None:
        return int(row["entity_id"])

    safe_name = name_lower.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    alias_row = conn.execute(
        f"""
        SELECT entity_id FROM entities
        WHERE ',' || LOWER(aliases) || ',' LIKE '%,' || ? || ',%' ESCAPE '\\'
        """,
        (safe_name,),
    ).fetchone()
    if alias_row is not None:
        return int(alias_row["entity_id"])

    return None


def link_fact_entity(
    conn: sqlite3.Connection,
    fact_id: int,
    entity_id: int,
    *,
    commit: bool = True,
) -> None:
    """Insert into fact_entities, silently ignore if the link already exists."""
    conn.execute(
        """
        INSERT OR IGNORE INTO fact_entities (fact_id, entity_id)
        VALUES (?, ?)
        """,
        (fact_id, entity_id),
    )
    if commit:
        conn.commit()
