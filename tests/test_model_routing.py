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
