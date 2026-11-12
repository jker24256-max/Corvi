"""Optional OpenCode-style skills, plugins, and MCP discovery."""
from __future__ import annotations

import json
import os
import subprocess
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    name: str
    path: Path
    instructions: str


def load_skills(root: Path) -> list[Skill]:
    paths = [root / ".opencode" / "skills", Path.home() / ".config" / "opencode" / "skills"]
    found: list[Skill] = []
    for folder in paths:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*/SKILL.md")):
            try:
                found.append(Skill(path.parent.name, path, path.read_text(encoding="utf-8")))
            except OSError:
                continue
    return found


def load_plugins(root: Path) -> list[Path]:
    paths = [root / ".opencode" / "plugins", Path.home() / ".config" / "opencode" / "plugins"]
    return [p for folder in paths if folder.is_dir() for p in sorted(folder.iterdir()) if p.suffix in {".py", ".json", ".js"}]


def load_plugin_hooks(root: Path) -> list[Any]:
    hooks = []
    for path in load_plugins(root):
        if path.suffix != ".py":
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"corvi_plugin_{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            if spec and spec.loader:
                spec.loader.exec_module(module)
                if callable(getattr(module, "on_event", None)):
                    hooks.append(module.on_event)
        except Exception:
            continue
    return hooks


def mcp_servers(root: Path) -> dict[str, dict[str, Any]]:
    candidates = [root / "opencode.json", root / ".opencode" / "config.json"]
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                value = data.get("mcp", data.get("mcpServers", {}))
                return value if isinstance(value, dict) else {}
            except (OSError, json.JSONDecodeError):
                return {}
    return {}


class MCPStdio:
    """Minimal JSON-RPC stdio bridge for an MCP server command."""

    def __init__(self, command: list[str], cwd: Path):
        self.process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.request_id = 0

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.process.stdin or not self.process.stdout:
            raise RuntimeError("MCP process pipes unavailable")
        self.request_id += 1
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.request_id,
                                             "method": method, "params": params or {}}) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed its output")
        return json.loads(line)

    def close(self) -> None:
        self.process.terminate()


def mcp_command(spec: dict[str, Any]) -> list[str] | None:
    command = spec.get("command") if isinstance(spec, dict) else None
    args = spec.get("args", []) if isinstance(spec, dict) else []
    if isinstance(command, str):
        return [command] + [str(x) for x in args]
    if isinstance(command, list):
        return [str(x) for x in command]
    return None


def mcp_list_tools(name: str, servers: dict[str, dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    spec = servers.get(name, {})
    command = mcp_command(spec)
    if not command:
        raise ValueError(f"MCP server '{name}' has no stdio command")
    client = MCPStdio(command, root)
    try:
        client.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                       "clientInfo": {"name": "corvi", "version": "1.0"}})
        return client.request("tools/list").get("result", {}).get("tools", [])
    finally:
        client.close()


def mcp_call(name: str, tool: str, arguments: dict[str, Any], servers: dict[str, dict[str, Any]], root: Path) -> Any:
    spec = servers.get(name, {})
    command = mcp_command(spec)
    if not command:
        raise ValueError(f"MCP server '{name}' has no stdio command")
    client = MCPStdio(command, root)
    try:
        client.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                       "clientInfo": {"name": "corvi", "version": "1.0"}})
        return client.request("tools/call", {"name": tool, "arguments": arguments}).get("result", {})
    finally:
        client.close()
