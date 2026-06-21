"""Sample ~50 facts from a DeepSeek-retained corpus for manual "library review".

The goal is to answer the §4 go/no-go question: if we remove the
person-centric facts (mostly 万永健 action items), does the remaining
knowledge base still stand on its own? This decides whether P2 graph edges
and node prefixes are worth building.

Usage:
    DEEPSEEK_API_KEY=... python sample_facts_for_review.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

if "hermes_state" not in sys.modules:
    hermes_state = types.ModuleType("hermes_state")
    hermes_state.apply_wal_with_fallback = lambda conn, db_label="": None
    sys.modules["hermes_state"] = hermes_state

if "hermes_constants" not in sys.modules:
    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: Path(tempfile.gettempdir())
    hermes_constants.display_hermes_home = lambda: tempfile.gettempdir()
    sys.modules["hermes_constants"] = hermes_constants

import store  # noqa: E402
from batch_retain_eval import _DeepSeekExtractor, PARSERS  # noqa: E402

WATCH_DIR = Path("C:/Users/sdses/Desktop")
PATTERNS = ["AI*.md", "今日.md", "梁局*.md", "现状*.txt"]
SAMPLE_SIZE = 50

# The user / narrator whose personal action items we might strip.
USER_NAMES = {"万永健"}
OTHER_PEOPLE = {
    "陈永存",
    "李善光",
    "赵传帅",
    "朱家腾",
    "仇道彬",
    "王云鹏",
    "赵明",
    "杨院老师",
    "陈楚俞",
    "秦高翔",
    "李鑫",
    "潘明轩",
    "李善光",
    "王三宁",
    "孔令瑞",
}
ACTION_VERBS = {
    "负责", "准备", "跟进", "汇报", "完成", "交付", "动作", "任务", "催",
    "确认", "协调", "演示", "出", "写", "发", "做", "跑", "设计", "开发",
    "落实", "进行", "简化", "安排", "讨论", "找", "保留", "扫描", "切换",
    "控制", "评估",
}

DOMAIN_KEYWORDS = {
    # system / architecture
    "系统", "平台", "模块", "功能", "接口", "数据库", "算法", "模型", "架构",
    "智能体", "agent", "workflow", "skill", "ai", "llm", "大模型",
    # project / process
    "项目", "方案", "策略", "逻辑", "流程", "目标", "范围", "约束", "需求",
    "阶段", "周期", "版本", "迭代", "mvp", "v2",
    # delivery / ops
    "部署", "上线", "测试", "演示", "交付", "接入", "打通", "迁移",
    # data / domain
    "数据", "信息", "企业", "产业链", "招商", "政策", "算力", "图谱",
    # decision / meeting metadata
    "决定", "确认", "明确", "要求", "包括", "涉及", "支持", "包含",
    "风险", "问题", "争议", "调整", "输出", "输入",
    # time / place / participants (meeting facts, not actions)
    "时间", "日期", "地点", "参与", "参会", "会议", "纪要",
    # residuals from real corpus
    "去重", "比对", "时效性", "格式", "规范", "训练", "风格", "效果", "方法",
    "优先级", "顺序", "原型", "讨论", "评估标准", "报价", "中介", "专班",
    "企查查", "业务方", "宝典", "对话式", "首页", "界面", "财政", "viewing",
    "后评估", "区县", "框架", "布局", "自动抓取", "技术框架", "技术债",
    "gpl", "扫描", "邮件", "准确率", "联系人", "角色", "客户", "竞争者",
    "服务器", "阻塞", "资源",
}


def classify_fact(content: str, entities: list[str]) -> tuple[str, str]:
    """Heuristic classification for the sample review.

    The classifier is intentionally simple and local. Its job is to place
    every fact into a meaningful bucket; a small residual of "other" is
    acceptable, but large "unclear" blocks signal a bad heuristic.
    """
    content = content.strip()
    lower = content.lower()

    # Explicit todo markers / personal task lists.
    if re.search(r"^\s*[-*]?\s*\[.?\]", content):
        if any(p in content for p in USER_NAMES):
            return "user_action", "todo marker + user name"
        return "other_person_or_task", "todo marker without user"

    # User is the explicit actor.
    if any(name in content for name in USER_NAMES):
        if any(v in content for v in ACTION_VERBS):
            return "user_action", "user name + action verb"
        return "user_mentioned", "user name but not clear actor"

    # Other named person is the explicit actor.
    if any(p in content for p in OTHER_PEOPLE):
        if any(v in content for v in ACTION_VERBS):
            return "other_person_action", "other person + action verb"
        return "other_person_mentioned", "other person mentioned"

    # Meeting logistics / metadata (time, place, participants, recording).
    meeting_kw = {"时间", "日期", "地点", "会议室", "参与", "参会", "参加", "会议", "纪要", "录屏", "录音"}
    if any(kw in content for kw in meeting_kw) and not any(v in content for v in ACTION_VERBS - {"确认"}):
        return "meeting_meta", "time/place/participant keyword without action"

    # Explicit task / next-step markers without a named actor -> narrator task.
    task_markers = {"待办", "遗漏", "立即要落实", "下一步"}
    if any(m in content for m in task_markers):
        return "user_action", "task/next-step marker"

    # Titled officials not in the named-people list -> other person mention.
    if re.search(r"[吕王张李陈赵杨]市长|[书记主任局长部长]", content):
        if not any(v in content for v in ACTION_VERBS):
            return "other_person_mentioned", "titled official mentioned"

    # Domain / system / project facts.
    domain_hits = [kw for kw in DOMAIN_KEYWORDS if kw in lower]
    if domain_hits:
        # Some domain facts are also user actions (e.g. "需要完成数据接入").
        # Only call it a user action if it reads like a directive aimed at
        # the narrator and there is no clear domain subject.
        directive_markers = {"请", "需要", "需", "应该", "应", "必须", "须", "要", "待"}
        has_directive = any(m in content for m in directive_markers)
        has_personal = {"我", "我的"} & set(re.findall(r"[\u4e00-\u9fa5]+", content))
        if (has_directive or has_personal) and any(v in content for v in ACTION_VERBS):
            return "user_action", "directive/personal + action verb on domain topic"
        return "domain_fact", f"domain keywords: {domain_hits[:3]}"

    # Action statement without explicit actor -> assumed narrator task.
    if any(v in content for v in ACTION_VERBS):
        return "user_action", "action verb, implicit narrator"

    # Residual: not domain, not action, not meeting logistics.
    return "other", "no strong signal"


def build_corpus(db_path: str) -> store.MemoryStore:
    memory_store = store.MemoryStore(db_path=db_path, hrr_dim=1024)
    extractor = _DeepSeekExtractor(
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    )
    files = []
    for pat in PATTERNS:
        files.extend(WATCH_DIR.glob(pat))
    files = sorted({p for p in files if p.suffix.lower() in PARSERS})
    for path in files:
        parser = PARSERS[path.suffix.lower()]
        raw_text = parser(path)
        if raw_text.strip():
            memory_store.retain_document(
                raw_text,
                source=str(path.name),
                category="project",
                extractor=extractor,
            )
    return memory_store


def sample_facts(memory_store: store.MemoryStore, n: int = SAMPLE_SIZE) -> list[dict]:
    rows = memory_store._conn.execute(
        """
        SELECT f.fact_id, f.content, d.source
        FROM facts f
        JOIN documents d ON f.source_doc_id = d.doc_id
        ORDER BY RANDOM()
        LIMIT ?
        """,
        (n,),
    ).fetchall()

    results: list[dict] = []
    for row in rows:
        fact_id = row["fact_id"]
        content = row["content"]
        source = row["source"]
        entity_rows = memory_store._conn.execute(
            """
            SELECT e.name FROM entities e
            JOIN fact_entities fe ON fe.entity_id = e.entity_id
            WHERE fe.fact_id = ?
            """,
            (fact_id,),
        ).fetchall()
        entities = [r["name"] for r in entity_rows]
        label, reason = classify_fact(content, entities)
        results.append(
            {
                "fact_id": fact_id,
                "source": source,
                "content": content,
                "entities": entities,
                "label": label,
                "reason": reason,
            }
        )
    return results


def entity_stats(memory_store: store.MemoryStore) -> list[dict]:
    rows = memory_store._conn.execute(
        """
        SELECT e.name, COUNT(*) AS cnt
        FROM entities e
        JOIN fact_entities fe ON fe.entity_id = e.entity_id
        GROUP BY e.entity_id
        ORDER BY cnt DESC
        LIMIT 20
        """
    ).fetchall()
    return [dict(r) for r in rows]


def aggregate_stats(memory_store: store.MemoryStore) -> dict:
    from collections import Counter

    total = memory_store._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    labels: Counter[str] = Counter()
    user_mention_count = 0

    rows = memory_store._conn.execute("SELECT fact_id, content FROM facts").fetchall()
    for row in rows:
        content = row["content"]
        label, _ = classify_fact(content, [])
        labels[label] += 1
        if "user" in label:
            user_mention_count += 1

    return {
        "total_facts": total,
        "any_user_mention_facts": user_mention_count,
        "label_distribution": dict(sorted(labels.items(), key=lambda x: -x[1])),
        "user_action_rate": round(labels.get("user_action", 0) / total, 3) if total else 0.0,
        "domain_rate": round(labels.get("domain_fact", 0) / total, 3) if total else 0.0,
    }


def print_report(sample: list[dict], stats: dict, top_entities: list[dict], facts: list[dict]) -> None:
    lines: list[str] = []
    lines.append("# 翻库 go/no-go：50 条 fact 抽样审查")
    lines.append("")
    lines.append("## 总体统计")
    lines.append("")
    lines.append(f"- 总 fact 数：{stats['total_facts']}")
    lines.append(f"- 含用户名的 fact（任意 mention）：{stats['any_user_mention_facts']}")
    lines.append("- 分类分布：")
    for label, count in stats["label_distribution"].items():
        rate = count / stats["total_facts"] * 100 if stats["total_facts"] else 0.0
        lines.append(f"  - {label}: {count} ({rate:.1f}%)")
    lines.append("")
    lines.append("## Top 20 实体（按链接 fact 数）")
    lines.append("")
    lines.append("| 实体 | 链接 fact 数 |")
    lines.append("|---|---|")
    for e in top_entities:
        lines.append(f"| {e['name']} | {e['cnt']} |")
    lines.append("")
    lines.append("## 50 条抽样")
    lines.append("")
    lines.append("| fact_id | 分类 | 来源 | 内容 | 理由 |")
    lines.append("|---|---|---|---|---|")
    for s in sample:
        content = s["content"].replace("|", "\\|").replace("\n", " ")
        source = Path(s["source"]).name
        lines.append(
            f"| {s['fact_id']} | {s['label']} | {source} | {content[:120]}{'...' if len(content)>120 else ''} | {s['reason']} |"
        )
    lines.append("")

    report_text = "\n".join(lines)
    print(report_text)

    out_path = PROJECT_ROOT / "sample_facts_review.md"
    json_path = PROJECT_ROOT / "sample_facts_review.json"
    unclear_path = PROJECT_ROOT / "sample_facts_unclear.json"
    out_path.write_text(report_text, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {"sample": sample, "stats": stats, "top_entities": top_entities, "facts": facts},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # Export residual / non-domain / non-action facts for manual review.
    residuals = [f for f in facts if f["label"] in ("other", "unclear")]
    unclear_path.write_text(
        json.dumps({"count": len(residuals), "facts": residuals}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n报告已写入：{out_path}")
    print(f"JSON：{json_path}")
    print(f"残余事实清单：{unclear_path}")


def all_facts(memory_store: store.MemoryStore) -> list[dict]:
    rows = memory_store._conn.execute(
        """
        SELECT f.fact_id, f.content, d.source
        FROM facts f
        JOIN documents d ON f.source_doc_id = d.doc_id
        ORDER BY f.fact_id
        """
    ).fetchall()
    results: list[dict] = []
    for row in rows:
        label, reason = classify_fact(row["content"], [])
        results.append(
            {
                "fact_id": row["fact_id"],
                "source": row["source"],
                "content": row["content"],
                "label": label,
                "reason": reason,
            }
        )
    return results


def main() -> None:
    if "DEEPSEEK_API_KEY" not in os.environ:
        print("请先设置 DEEPSEEK_API_KEY")
        sys.exit(1)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        memory_store = build_corpus(db_path)
        sample = sample_facts(memory_store)
        stats = aggregate_stats(memory_store)
        top_entities = entity_stats(memory_store)
        facts = all_facts(memory_store)
        print_report(sample, stats, top_entities, facts)
        memory_store.close()
    finally:
        Path(db_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
