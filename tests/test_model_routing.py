"""Tests for routing retain extraction through Hermes' configured provider."""

from __future__ import annotations

import sys
import types

import holographic


def test_resolve_model_call_routes_only_to_deepseek(monkeypatch) -> None:
    calls: list[dict] = []
    auxiliary_client = types.ModuleType("agent.auxiliary_client")

    def call_llm(**kwargs):
        calls.append(kwargs)
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content="routed response")
                )
            ]
        )

    auxiliary_client.call_llm = call_llm
    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", auxiliary_client)

    model_call = holographic._resolve_model_call()

    assert model_call is not None
    assert model_call("extract this") == "routed response"
    assert calls == [
        {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "extract this"}],
            "temperature": 0,
        }
    ]


def test_consolidate_without_llm_reports_deepseek_only(monkeypatch, tmp_path) -> None:
    """The consolidate error must reflect the DeepSeek-pinned design.

    `_resolve_model_call` deliberately only honors the Hermes DeepSeek route or
    a `DEEPSEEK_API_KEY` fallback (see the pinning comment in __init__). The old
    error string promised `OPENAI_API_KEY`, which is never read, so a user who
    set only that key would configure it and still get nothing. The message must
    name what is actually honored and must not advertise an unsupported key.
    """
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delitem(sys.modules, "agent.auxiliary_client", raising=False)

    provider = holographic.HolographicMemoryProvider(
        config={"db_path": str(tmp_path / "routing.db"), "hrr_dim": 256}
    )
    provider.initialize("routing-session")
    try:
        out = provider.handle_tool_call("fact_store", {"action": "consolidate"})
    finally:
        provider._store.close()

    assert "DEEPSEEK_API_KEY" in out
    assert "OPENAI_API_KEY" not in out
