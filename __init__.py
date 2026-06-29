"""hermes-memory-store — holographic memory plugin using MemoryProvider interface.

Registers as a MemoryProvider plugin, giving the agent structured fact storage
with entity resolution, trust scoring, and HRR-based compositional retrieval.

Original plugin by dusterbloom (PR #2351), adapted to the MemoryProvider ABC.

Config in $HERMES_HOME/config.yaml (profile-scoped):
  plugins:
    hermes-memory-store:
      db_path: $HERMES_HOME/memory_store.db   # omit to use the default
      auto_extract: false
      default_trust: 0.5
      min_trust_threshold: 0.3
      near_duplicate_threshold: 0.8          # Jaccard threshold for write-time dedup
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Dict, List

from agent.memory_provider import MemoryProvider
from tools.registry import tool_error
from .store import MemoryStore
from .retrieval import FactRetriever
from hermes_cli.config import cfg_get

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool schemas (unchanged from original PR)
# ---------------------------------------------------------------------------

FACT_STORE_SCHEMA = {
    "name": "fact_store",
    "description": (
        "Deep structured memory with algebraic reasoning. "
        "Use alongside the memory tool — memory for always-on context, "
        "fact_store for deep recall and compositional queries.\n\n"
        "ACTIONS (simple → powerful):\n"
        "• add — Store a fact the user would expect you to remember.\n"
        "• retain — Store a raw document/article and extract atomic facts from it.\n"
        "• search — Keyword lookup ('editor config', 'deploy process').\n"
        "• probe — Entity recall: ALL facts about a person/thing.\n"
        "• related — What connects to an entity? Structural adjacency.\n"
        "• reason — Compositional: facts connected to MULTIPLE entities simultaneously.\n"
        "• contradict — Memory hygiene: find facts making conflicting claims.\n"
        "• normalize — Merge fragmented entity variants (e.g. 'K2.7' / 'K2_7').\n"
        "• consolidate — Run semantic consolidation to merge duplicates and timeline updates using LLM.\n"
        "• update/remove/list — CRUD operations.\n\n"
        "IMPORTANT: Before answering questions about the user, ALWAYS probe or reason first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "retain", "search", "probe", "related", "reason", "contradict", "update", "remove", "list", "normalize", "consolidate"],
            },
            "content": {"type": "string", "description": "Fact content (required for 'add') or raw document text (required for 'retain')."},
            "query": {"type": "string", "description": "Search query (required for 'search')."},
            "entity": {"type": "string", "description": "Entity name for 'probe'/'related'."},
            "entities": {"type": "array", "items": {"type": "string"}, "description": "Entity names for 'reason'."},
            "fact_id": {"type": "integer", "description": "Fact ID for 'update'/'remove'."},
            "category": {"type": "string", "enum": ["user_pref", "project", "tool", "general"]},
            "source": {"type": "string", "description": "Optional source label for 'retain' (e.g. URL or filename)."},
            "tags": {"type": "string", "description": "Comma-separated tags."},
            "trust_delta": {"type": "number", "description": "Trust adjustment for 'update'."},
            "min_trust": {"type": "number", "description": "Minimum trust filter (default: 0.3)."},
            "limit": {"type": "integer", "description": "Max results (default: 10)."},
        },
        "required": ["action"],
    },
}

FACT_FEEDBACK_SCHEMA = {
    "name": "fact_feedback",
    "description": (
        "Rate a fact after using it. Mark 'helpful' if accurate, 'unhelpful' if outdated. "
        "This trains the memory — good facts rise, bad facts sink."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["helpful", "unhelpful"]},
            "fact_id": {"type": "integer", "description": "The fact ID to rate."},
        },
        "required": ["action", "fact_id"],
    },
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_plugin_config() -> dict:
    from hermes_constants import get_hermes_home
    config_path = get_hermes_home() / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
        with open(config_path, encoding="utf-8-sig") as f:
            all_config = yaml.safe_load(f) or {}
        return cfg_get(all_config, "plugins", "hermes-memory-store", default={}) or {}
    except Exception as e:
        logger.warning("Failed to load holographic plugin config: %s", e)
        return {}


def _resolve_model_call() -> Callable[[str], str] | None:
    import os

    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

    # Retain extraction is intentionally pinned to DeepSeek. Hermes owns
    # credential resolution, but it must not silently substitute the main
    # provider or another fallback model when DeepSeek is unavailable.
    try:
        from agent.auxiliary_client import call_llm

        def model_call(prompt: str) -> str:
            resp = call_llm(
                provider="deepseek",
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            return resp.choices[0].message.content or ""

        return model_call
    except ImportError:
        # Standalone scripts may run outside the Hermes package. Keep direct
        # environment-variable providers as a compatibility fallback.
        pass

    ds_key = os.environ.get("DEEPSEEK_API_KEY")
    if ds_key:
        try:
            from openai import OpenAI
            base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            client = OpenAI(api_key=ds_key, base_url=base_url)
            def model_call(prompt: str) -> str:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    stream=False,
                )
                return resp.choices[0].message.content or ""
            return model_call
        except Exception as e:
            logger.exception("Failed to initialize DeepSeek model call: %s", e)

    return None


# ---------------------------------------------------------------------------
# MemoryProvider implementation
# ---------------------------------------------------------------------------

class HolographicMemoryProvider(MemoryProvider):
    """Holographic memory with structured facts, entity resolution, and HRR retrieval."""

    def __init__(self, config: dict | None = None):
        self._config = config or _load_plugin_config()
        self._store = None
        self._retriever = None
        self._min_trust = float(self._config.get("min_trust_threshold", 0.3))

    @property
    def name(self) -> str:
        return "holographic"

    def is_available(self) -> bool:
        return True  # SQLite is always available, numpy is optional

    def save_config(self, values, hermes_home):
        """Write config to config.yaml under plugins.hermes-memory-store."""
        from pathlib import Path
        config_path = Path(hermes_home) / "config.yaml"
        try:
            import yaml
            existing = {}
            if config_path.exists():
                with open(config_path, encoding="utf-8-sig") as f:
                    existing = yaml.safe_load(f) or {}
            existing.setdefault("plugins", {})
            existing["plugins"]["hermes-memory-store"] = values
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(existing, f, default_flow_style=False)
        except Exception as e:
            logger.exception("Failed to save holographic plugin config to %s: %s", config_path, e)

    def get_config_schema(self):
        from hermes_constants import display_hermes_home
        _default_db = f"{display_hermes_home()}/memory_store.db"
        return [
            {"key": "db_path", "description": "SQLite database path", "default": _default_db},
            {"key": "default_trust", "description": "Default trust score for new facts", "default": "0.5"},
            {"key": "hrr_dim", "description": "HRR vector dimensions", "default": "1024"},
            {"key": "near_duplicate_threshold", "description": "Jaccard threshold for merging near-duplicate facts on write", "default": "0.8"},
            {"key": "retain_max_chunk_tokens", "description": "Max tokens per chunk for document retention (LLM context window guard)", "default": "6000"},
            {"key": "gc_interval_days", "description": "Days between lazy retrieval-recency refreshes (0 to disable)", "default": "7"},
            {"key": "gc_decay_max_days", "description": "Days for retrieval recency to reach gc_decay_floor", "default": "365"},
            {"key": "gc_decay_floor", "description": "Minimum retrieval recency multiplier", "default": "0.1"},
        ]

    def initialize(self, session_id: str, **kwargs) -> None:
        from hermes_constants import get_hermes_home
        _hermes_home = str(get_hermes_home())
        _default_db = _hermes_home + "/memory_store.db"
        db_path = self._config.get("db_path", _default_db)
        # Expand $HERMES_HOME in user-supplied paths so config values like
        # "$HERMES_HOME/memory_store.db" or "~/.hermes/memory_store.db" both
        # resolve to the active profile's directory.
        if isinstance(db_path, str):
            db_path = db_path.replace("$HERMES_HOME", _hermes_home)
            db_path = db_path.replace("${HERMES_HOME}", _hermes_home)
        default_trust = float(self._config.get("default_trust", 0.5))
        hrr_dim = int(self._config.get("hrr_dim", 1024))
        near_duplicate_threshold = float(self._config.get("near_duplicate_threshold", 0.8))
        retain_max_chunk_tokens = int(self._config.get("retain_max_chunk_tokens", 6000))
        gc_interval_days = float(self._config.get("gc_interval_days", 7.0))
        gc_decay_max_days = float(self._config.get("gc_decay_max_days", 365.0))
        gc_decay_floor = float(self._config.get("gc_decay_floor", 0.1))

        self._store = MemoryStore(
            db_path=db_path,
            default_trust=default_trust,
            hrr_dim=hrr_dim,
            near_duplicate_threshold=near_duplicate_threshold,
            gc_interval_days=gc_interval_days,
            gc_decay_max_days=gc_decay_max_days,
            gc_decay_floor=gc_decay_floor,
        )
        # Run lazy GC at startup to backfill any missed runs while hermes was
        # away. The GC timestamp prevents this from doing work too frequently.
        try:
            self._store.run_gc()
        except Exception as e:
            logger.warning("Lazy GC at initialize failed: %s", e)
        self._retain_max_chunk_tokens = max(256, retain_max_chunk_tokens)
        self._retriever = FactRetriever(
            store=self._store,
            hrr_dim=hrr_dim,
            recency_max_days=gc_decay_max_days,
            recency_floor=gc_decay_floor,
        )
        self._session_id = session_id

    def system_prompt_block(self) -> str:
        if not self._store:
            return ""
        try:
            total = self._store._conn.execute(
                "SELECT COUNT(*) FROM facts"
            ).fetchone()[0]
        except Exception:
            total = 0
        if total == 0:
            return (
                "# Holographic Memory\n"
                "Active. Empty fact store — proactively add facts the user would expect you to remember.\n"
                "Use fact_store(action='add') to store durable structured facts about people, projects, preferences, decisions.\n"
                "Use fact_feedback to rate facts after using them (trains trust scores)."
            )
        return (
            f"# Holographic Memory\n"
            f"Active. {total} facts stored with entity resolution and trust scoring.\n"
            f"Use fact_store to search, probe entities, reason across entities, or add facts.\n"
            f"Use fact_feedback to rate facts after using them (trains trust scores)."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not self._retriever or not query:
            return ""
        try:
            results = self._retriever.search(query, min_trust=self._min_trust, limit=5)
            if not results:
                return ""
            lines = []
            for r in results:
                trust = r.get("trust_score", r.get("trust", 0))
                lines.append(f"- [{trust:.1f}] {r.get('content', '')}")
            return "## Holographic Memory\n" + "\n".join(lines)
        except Exception as e:
            logger.debug("Holographic prefetch failed: %s", e)
            return ""

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        # Holographic memory stores explicit facts via tools, not auto-sync.
        # The on_session_end hook handles auto-extraction if configured.
        pass

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [FACT_STORE_SCHEMA, FACT_FEEDBACK_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if tool_name == "fact_store":
            return self._handle_fact_store(args)
        elif tool_name == "fact_feedback":
            return self._handle_fact_feedback(args)
        return tool_error(f"Unknown tool: {tool_name}")

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        # Auto-extraction via English regex was removed: it was useless for
        # Chinese, and even in English produced coarse non-atomic facts.
        # Structured extraction happens explicitly via retain_document + LLM.
        # Run lazy GC at session end; the timestamp check makes this cheap
        # when recently run.
        if self._store is not None:
            try:
                self._store.run_gc()
            except Exception as e:
                logger.warning("Lazy GC at session end failed: %s", e)

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        """Mirror built-in memory writes as facts."""
        if action == "add" and self._store and content:
            try:
                category = "user_pref" if target == "user" else "general"
                self._store.add_fact(content, category=category)
            except Exception as e:
                logger.debug("Holographic memory_write mirror failed: %s", e)

    def shutdown(self) -> None:
        if self._store is not None:
            try:
                self._store.close()
            except Exception as e:
                logger.warning("Error closing memory store on shutdown: %s", e)
        self._store = None
        self._retriever = None

    # -- Tool handlers -------------------------------------------------------

    def _handle_fact_store(self, args: dict) -> str:
        try:
            action = args["action"]
            store = self._store
            retriever = self._retriever

            if action == "add":
                fact_id = store.add_fact(
                    args["content"],
                    category=args.get("category", "general"),
                    tags=args.get("tags", ""),
                )
                return json.dumps({"fact_id": fact_id, "status": "added"})

            elif action == "retain":
                model_call = _resolve_model_call()
                extractor = None
                if model_call:
                    from .store import _LLMExtractor
                    extractor = _LLMExtractor(model_call=model_call)
                result = store.retain_document(
                    args["content"],
                    source=args.get("source", ""),
                    category=args.get("category", "general"),
                    extractor=extractor,
                    max_chunk_tokens=self._retain_max_chunk_tokens,
                )
                return json.dumps(result)

            elif action == "search":
                results = retriever.search(
                    args["query"],
                    category=args.get("category"),
                    min_trust=float(args.get("min_trust", self._min_trust)),
                    limit=int(args.get("limit", 10)),
                )
                return json.dumps({"results": results, "count": len(results)})

            elif action == "probe":
                results = retriever.probe(
                    args["entity"],
                    category=args.get("category"),
                    limit=int(args.get("limit", 10)),
                )
                return json.dumps({"results": results, "count": len(results)})

            elif action == "related":
                results = retriever.related(
                    args["entity"],
                    category=args.get("category"),
                    limit=int(args.get("limit", 10)),
                )
                return json.dumps({"results": results, "count": len(results)})

            elif action == "reason":
                entities = args.get("entities", [])
                if not entities:
                    return tool_error("reason requires 'entities' list")
                results = retriever.reason(
                    entities,
                    category=args.get("category"),
                    limit=int(args.get("limit", 10)),
                )
                return json.dumps({"results": results, "count": len(results)})

            elif action == "contradict":
                results = retriever.contradict(
                    category=args.get("category"),
                    limit=int(args.get("limit", 10)),
                )
                return json.dumps({"results": results, "count": len(results)})

            elif action == "update":
                updated = store.update_fact(
                    int(args["fact_id"]),
                    content=args.get("content"),
                    trust_delta=float(args["trust_delta"]) if "trust_delta" in args else None,
                    tags=args.get("tags"),
                    category=args.get("category"),
                )
                return json.dumps({"updated": updated})

            elif action == "remove":
                removed = store.remove_fact(int(args["fact_id"]))
                return json.dumps({"removed": removed})

            elif action == "list":
                facts = store.list_facts(
                    category=args.get("category"),
                    min_trust=float(args.get("min_trust", 0.0)),
                    limit=int(args.get("limit", 10)),
                )
                return json.dumps({"facts": facts, "count": len(facts)})

            elif action == "normalize":
                report = store.normalize_entities()
                return json.dumps({"normalized": True, "report": report})

            elif action == "consolidate":
                model_call = _resolve_model_call()
                if not model_call:
                    # Extraction/consolidation is intentionally pinned to DeepSeek
                    # (see _resolve_model_call). Don't advertise OPENAI_API_KEY here:
                    # it is never read, so promising it sends users down a dead end.
                    return tool_error("No DeepSeek LLM available. Set DEEPSEEK_API_KEY (or run inside Hermes with a configured DeepSeek provider). Consolidation requires an LLM.")
                report = store.consolidate_facts(
                    model_call=model_call,
                    category=args.get("category"),
                )
                return json.dumps({"consolidated": True, "report": report})

            else:
                return tool_error(f"Unknown action: {action}")

        except KeyError as exc:
            return tool_error(f"Missing required argument: {exc}")
        except Exception as exc:
            return tool_error(str(exc))

    def _handle_fact_feedback(self, args: dict) -> str:
        try:
            fact_id = int(args["fact_id"])
            helpful = args["action"] == "helpful"
            result = self._store.record_feedback(fact_id, helpful=helpful)
            return json.dumps(result)
        except KeyError as exc:
            return tool_error(f"Missing required argument: {exc}")
        except Exception as exc:
            return tool_error(str(exc))




# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Register the holographic memory provider with the plugin system."""
    config = _load_plugin_config()
    provider = HolographicMemoryProvider(config=config)
    ctx.register_memory_provider(provider)
