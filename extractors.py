"""Document-to-fact extractors and LLM consolidation helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol


class FactExtractor(Protocol):
    """Pluggable extractor: turns a raw document into atomic fact strings."""

    kind: str

    def extract(self, raw_text: str, category: str) -> list[str]:
        ...


class _LocalFallbackExtractor:
    """Crash-only extractor when no LLM is available.

    Produces text fragments, not true atomic facts. Facts emitted by this
    extractor are tagged as fallback and receive a lower initial trust score.
    """

    kind: str = "fallback"

    def __init__(self, min_length: int = 20) -> None:
        self.min_length = min_length

    def extract(self, raw_text: str, category: str) -> list[str]:
        import re

        raw_text = raw_text.strip()
        if not raw_text:
            return []
        # Split on sentence boundaries; this is intentionally coarse.
        sentences = re.split(r"(?<=[.!?])\s+", raw_text)
        seen: set[str] = set()
        facts: list[str] = []
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < self.min_length:
                continue
            if sentence in seen:
                continue
            seen.add(sentence)
            facts.append(sentence)
        return facts


class _LLMExtractor:
    """LLM-based atomic-fact extractor.

    The actual API call is injected via ``model_call`` so the core package
    does not depend on any SDK. Provider failures are allowed to propagate so
    the storage layer can preserve an orphan document *and* report why the
    extraction needs retrying.
    """

    kind: str = "llm"

    def __init__(self, model_call: Callable[[str], str]) -> None:
        self.model_call = model_call

    def extract(self, raw_text: str, category: str) -> list[str]:
        prompt = self._build_prompt(raw_text, category)
        response = self.model_call(prompt)
        return self._parse_response(response)

    def _build_prompt(self, raw_text: str, category: str) -> str:
        return (
            "You are an atomic-fact extractor. Extract one atomic fact per line from the text below.\n\n"
            "Hard rules:\n"
            "- ONE fact per line. No compound sentences.\n"
            "- Each fact must be self-contained: understandable without the surrounding text.\n"
            "- Preserve exact names, dates, numbers, versions, and scores.\n"
            "- Do NOT use bullets, numbers, markdown, or introductory phrases like 'The fact is'.\n"
            "- If the text contains multiple related claims, split them into separate facts.\n"
            "- Aim for 5-25 words per fact. Never exceed 60 words / 80 tokens per fact.\n"
            "- For Chinese text, split at Chinese sentence/clause boundaries （。；：） and keep each fact short.\n\n"
            "Good examples:\n"
            "- 投促局项目由李善光负责，当前状态为开发中。\n"
            "- 凌云志企业综合评分为85分，投资意愿88分。\n"
            "- 发改委项目要求所有功能入口整合为Chat形式。\n\n"
            "Bad example (too coarse, do NOT output like this):\n"
            "- 投促局项目由李善光负责且已四次汇报，毕局确认，凌云志85分，发改委要Chat入口。\n\n"
            f"Category: {category}\n\n"
            "---\n"
            f"{raw_text}\n"
            "---\n\n"
            "Atomic facts:"
        )

    def _parse_response(self, response: str) -> list[str]:
        facts: list[str] = []
        seen: set[str] = set()
        for line in response.splitlines():
            line = line.strip().strip("-\u2022*•").strip()
            if len(line) < 12:
                continue
            if line in seen:
                continue
            seen.add(line)
            facts.append(line)
        return facts


class _LLMConsolidator:
    """LLM-based fact consolidator.

    The actual API call is injected via ``model_call`` so the core package
    does not depend on any SDK.
    """

    def __init__(self, model_call: Callable[[str], str]) -> None:
        self.model_call = model_call

    def consolidate(self, facts: list[dict]) -> list[dict]:
        if not facts:
            return []
        prompt = self._build_prompt(facts)
        try:
            response = self.model_call(prompt)
        except Exception:
            return []
        return self._parse_response(response)

    def _build_prompt(self, facts: list[dict]) -> str:
        facts_str = json.dumps(
            [{"fact_id": f["fact_id"], "content": f["content"]} for f in facts],
            ensure_ascii=False,
            indent=2,
        )
        return (
            "You are a semantic memory consolidator. Analyze the related facts below and determine if any of them are duplicate claims or part of a timeline sequence that should be merged/converged.\n\n"
            "Here is the list of facts:\n"
            f"{facts_str}\n\n"
            "Instructions:\n"
            "1. Group facts that discuss the same specific event, relationship, preference, or state.\n"
            "2. If facts represent duplicate or slightly different wording of the same claim (e.g. 'A works on project B' and 'A is developing project B'), merge them.\n"
            "3. If facts represent timeline updates of the same state (e.g. 'A is senior dev' and 'A promoted to principal dev'), converge them into a single consolidated fact representing the latest state with history (e.g. 'A is principal dev (previously senior dev)').\n"
            "4. Keep unrelated facts completely separate. Do not force-merge facts that happen to share an entity but claim different things.\n"
            "5. For merged/converged facts, write a self-contained content sentence. Aim for 5-25 words. Never exceed 60 words.\n"
            "6. Output your decision as a single valid JSON object. No conversational markdown, no explanation.\n\n"
            "Response Schema:\n"
            "{\n"
            '  "consolidations": [\n'
            "    {\n"
            '      "input_ids": [12, 15],\n'
            '      "consolidated_content": "Consolidated fact content..."\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Example JSON output:\n"
            "{\n"
            '  "consolidations": [\n'
            '    {"input_ids": [12, 15], "consolidated_content": "Mia is a Principal Dev (previously Senior Dev)"}\n'
            "  ]\n"
            "}"
        )

    def _parse_response(self, response: str) -> list[dict]:
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()

        try:
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                json_str = response[start : end + 1]
                data = json.loads(json_str)
                return data.get("consolidations", [])
        except Exception:
            pass
        return []
