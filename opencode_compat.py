"""OpenCode-compatible project configuration primitives for Corvi.

This module intentionally uses only the Python standard library so Corvi keeps
working in a fresh terminal with no extra dependencies.
"""
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PermissionSet:
    """Resolve OpenCode-style allow/ask/deny rules for a tool name."""

    rules: dict[str, str] = field(default_factory=lambda: {"*": "ask"})

    def resolve(self, tool: str) -> str:
        ordered = sorted(self.rules.items(), key=lambda item: (item[0] == "*", item[0].count("*")))
        for pattern, action in ordered:
            aliases = {
                "read": ("read_file", "list_dir", "grep"),
                "edit": ("write_file", "edit_file"),
                "bash": ("run_bash",),
                "list": ("list_dir",),
            }
            matches = aliases.get(pattern, (pattern,))
            if any(fnmatch.fnmatch(tool, candidate) for candidate in matches):
                return action if action in {"allow", "ask", "deny"} else "ask"
        return "ask"

    @classmethod
    def from_config(cls, value: Any) -> "PermissionSet":
        if value == "allow":
            return cls({"*": "allow"})
        if value == "deny":
            return cls({"*": "deny"})
        if isinstance(value, dict):
            return cls({str(k): str(v) for k, v in value.items()})
        return cls()


@dataclass
class ProjectConfig:
    root: Path
    permissions: PermissionSet = field(default_factory=PermissionSet)
    commands: dict[str, str] = field(default_factory=dict)
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)
    model: str | None = None

    @classmethod
    def load(cls, root: Path) -> "ProjectConfig":
        path = root / "opencode.json"
        if not path.exists():
            path = root / ".opencode" / "config.json"
        if not path.exists():
            return cls(root)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(root)
        return cls(
            root=root,
            permissions=PermissionSet.from_config(data.get("permission", data.get("permissions"))),
            commands={str(k): str(v) for k, v in data.get("command", {}).items()},
            agents=data.get("agent", {}) if isinstance(data.get("agent", {}), dict) else {},
            model=data.get("model") if isinstance(data.get("model"), str) else None,
        )


def load_markdown_commands(root: Path) -> dict[str, str]:
    """Load simple custom slash commands from .opencode/commands/*.md."""
    result: dict[str, str] = {}
    command_dir = root / ".opencode" / "commands"
    if not command_dir.is_dir():
        return result
    for path in sorted(command_dir.glob("*.md")):
        try:
            result[path.stem] = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return result
