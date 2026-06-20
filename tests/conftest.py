"""Test fixtures and hermes module stubs for holographic tests."""

from __future__ import annotations

import sys
import types
from pathlib import Path


def _apply_wal_with_fallback(conn, db_label: str = "") -> None:
    """No-op stub for hermes_state.apply_wal_with_fallback."""
    pass


def _tool_error(message: str) -> str:
    return f"ERROR: {message}"


def _cfg_get(config: dict, *keys: str, default=None):
    """Nested dict getter stub for hermes_cli.config.cfg_get."""
    current = config
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current if current is not None else default


def _install_hermes_stubs() -> None:
    """Inject minimal stubs for hermes internals so the package can import."""
    if "hermes_state" not in sys.modules:
        hermes_state = types.ModuleType("hermes_state")
        hermes_state.apply_wal_with_fallback = _apply_wal_with_fallback
        sys.modules["hermes_state"] = hermes_state

    if "hermes_constants" not in sys.modules:
        hermes_constants = types.ModuleType("hermes_constants")
        hermes_constants.get_hermes_home = lambda: Path(".")
        hermes_constants.display_hermes_home = lambda: "."
        sys.modules["hermes_constants"] = hermes_constants

    if "agent.memory_provider" not in sys.modules:
        memory_provider = types.ModuleType("agent.memory_provider")

        class MemoryProvider:
            """Minimal ABC stub."""

            @property
            def name(self) -> str:
                return "stub"

        memory_provider.MemoryProvider = MemoryProvider
        sys.modules["agent.memory_provider"] = memory_provider
        sys.modules.setdefault("agent", types.ModuleType("agent"))

    if "tools.registry" not in sys.modules:
        tools_registry = types.ModuleType("tools.registry")
        tools_registry.tool_error = _tool_error
        sys.modules["tools.registry"] = tools_registry
        sys.modules.setdefault("tools", types.ModuleType("tools"))

    if "hermes_cli.config" not in sys.modules:
        hermes_cli_config = types.ModuleType("hermes_cli.config")
        hermes_cli_config.cfg_get = _cfg_get
        sys.modules["hermes_cli.config"] = hermes_cli_config
        sys.modules.setdefault("hermes_cli", types.ModuleType("hermes_cli"))


_install_hermes_stubs()
