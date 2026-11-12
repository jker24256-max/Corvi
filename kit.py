#!/usr/bin/env python3
"""
Kit + Corvi - a full-screen terminal coding agent for your local model,
built around Corvi, a small cheerful raven who reacts to everything it does.

  python3 kit.py                      # Ollama on localhost:11434
  python3 kit.py --base-url http://localhost:1234/v1     # LM Studio
  python3 kit.py --no-fullscreen      # plain mode (no mascot panel)

Zero third-party dependencies. Python 3.9+.
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mascot import engine as E  # noqa: E402
from tui import UI, set_theme  # noqa: E402
from opencode_compat import ProjectConfig, PermissionSet, load_markdown_commands  # noqa: E402
from corvi_state import StateStore  # noqa: E402
from corvi_ext import load_plugins, load_skills, load_plugin_hooks, mcp_servers, mcp_list_tools, mcp_call  # noqa: E402
from corvi_council import deliberate  # noqa: E402

try:
    import readline
except ImportError:  # pragma: no cover
    readline = None

VERSION = "1.0.0"

# ════════════════════════════════════════════════════════════════════════════
#  TOOLS  (unchanged behaviour: Corvi never touches how these run)
# ════════════════════════════════════════════════════════════════════════════
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
MAX_OUT = 8000
MAX_TOOL_ROUNDS = 6
TURN_TIMEOUT_SECONDS = 180
SLASH_COMMANDS = [
    "/help", "/btw", "/ask", "/plan", "/review", "/research", "/model", "/clear", "/fix", "/yolo",
    "/status", "/last", "/pwd", "/ls", "/run", "/web", "/github", "/cd", "/workspace", "/settings", "/set",
    "/corvi", "/size", "/theme", "/pose", "/mood", "/achievements", "/log", "/history", "/scroll", "/exit",
]


def configure_completion():
    """Enable OpenCode-style slash-command completion at the input prompt."""
    if not readline:
        return
    def complete(text, state):
        matches = [cmd for cmd in SLASH_COMMANDS if cmd.startswith(text)] if text.startswith("/") else []
        return matches[state] if state < len(matches) else None
    readline.set_completer(complete)
    try:
        readline.parse_and_bind('"\\t": complete')
        readline.parse_and_bind('set show-all-if-ambiguous on')
    except Exception:  # noqa: BLE001
        readline.parse_and_bind("tab: complete")


def _p(path):
    p = Path(os.path.expanduser(str(path)))
    return p if p.is_absolute() else Path.cwd() / p


def t_read_file(path, offset=1, limit=2000):
    p = _p(path)
    if not p.is_file():
        return f"Error: {path} is not a file"
    lines = p.read_text(errors="replace").splitlines()
    offset, limit = max(int(offset), 1), int(limit)
    chunk = lines[offset - 1: offset - 1 + limit]
    out = "\n".join(f"{i:>5}\t{l}" for i, l in enumerate(chunk, offset))
    rest = len(lines) - (offset - 1 + len(chunk))
    if rest > 0:
        out += f"\n… {rest} more lines (use offset/limit)"
    return out or "(empty file)"


def t_write_file(path, content):
    p = _p(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Wrote {len(content.splitlines())} lines to {path}"


def t_edit_file(path, old_string, new_string):
    p = _p(path)
    if not p.is_file():
        return f"Error: {path} is not a file"
    text = p.read_text()
    n = text.count(old_string)
    if n == 0:
        return "Error: old_string not found. Re-read the file and copy the text exactly."
    if n > 1:
        return f"Error: old_string appears {n} times. Include more surrounding context."
    p.write_text(text.replace(old_string, new_string, 1))
    return f"Edited {path}: -{len(old_string.splitlines())} +{len(new_string.splitlines())} lines"


def t_list_dir(path="."):
    p = _p(path)
    if not p.is_dir():
        if p.exists():
            if p.is_file():
                # Models sometimes route a discovered file back through
                # list_dir. Make that harmless and useful instead of burning
                # a tool round on a predictable type error.
                return f"{path} is a file; showing its contents instead:\n{t_read_file(path, 1, 120)}"
            return f"Error: {path} is not a directory. Choose a directory or use the appropriate file tool."
        parent = p.parent
        hint = ""
        if parent.is_dir():
            names = sorted(x.name for x in parent.iterdir() if x.name != ".DS_Store")
            close = [name for name in names if name.lower().startswith(p.name.lower()[:2])]
            if close:
                hint = f" Nearby entries: {', '.join(close[:8])}."
        return f"Error: {path} does not exist. List the parent directory and choose an existing path.{hint}"
    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    lines = [f"{i.name}/" if i.is_dir() else i.name for i in items if i.name != ".DS_Store"]
    return ("\n".join(lines[:200]) + (f"\n… {len(lines) - 200} more" if len(lines) > 200 else "")) or "(empty)"


def t_grep(pattern, path=".", include=None):
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"Error: bad regex: {e}"
    root = _p(path)
    files = [root] if root.is_file() else []
    if root.is_dir():
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in SKIP_DIRS]
            for fn in fns:
                if include and not Path(fn).match(include):
                    continue
                files.append(Path(dp) / fn)
    hits = []
    for f in files:
        try:
            for n, line in enumerate(f.read_text().splitlines(), 1):
                if rx.search(line):
                    try:
                        rel = f.relative_to(Path.cwd())
                    except ValueError:
                        rel = f
                    hits.append(f"{rel}:{n}: {line.strip()[:200]}")
                    if len(hits) >= 100:
                        return "\n".join(hits) + "\n… (stopped at 100 matches)"
        except (UnicodeDecodeError, OSError):
            continue
    return "\n".join(hits) or "No matches."


def t_run_bash(command, timeout=120):
    shell = "/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/sh"
    try:
        r = subprocess.run(command, shell=True, executable=shell, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=int(timeout))
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    return f"exit code {r.returncode}\n{out}".strip()


class _SearchParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.results = []; self.current = None; self.field = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs); classes = attrs.get("class", "").split()
        if tag == "a" and "result__a" in classes:
            self.current = {"title": "", "url": attrs.get("href", "")}; self.field = "title"
        elif self.current and "result__snippet" in classes:
            self.field = "snippet"; self.current.setdefault("snippet", "")

    def handle_data(self, data):
        if self.current and self.field:
            self.current[self.field] = self.current.get(self.field, "") + data

    def handle_endtag(self, tag):
        if self.current and tag == "a" and self.field == "title":
            self.current["title"] = re.sub(r"\\s+", " ", self.current["title"]).strip()
            self.results.append(self.current); self.current = None; self.field = None
        elif self.current and self.field == "snippet" and tag in ("a", "span"):
            self.current["snippet"] = re.sub(r"\\s+", " ", self.current["snippet"]).strip(); self.field = None


class _BingParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.results = []; self.current = None; self.field = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs); classes = attrs.get("class", "").split()
        if tag == "li" and "b_algo" in classes:
            self.current = {"title": "", "url": "", "snippet": ""}
        elif self.current and tag == "a" and not self.current["title"]:
            self.current["url"] = attrs.get("href", ""); self.field = "title"
        elif self.current and tag == "p":
            self.field = "snippet"

    def handle_data(self, data):
        if self.current and self.field:
            self.current[self.field] += data

    def handle_endtag(self, tag):
        if self.current and tag == "li":
            self.current = {k: re.sub(r"\\s+", " ", v).strip() for k, v in self.current.items()}
            if self.current["title"] and self.current["url"]:
                self.results.append(self.current)
            self.current = None; self.field = None


def t_web_search(query, max_results=5):
    query = str(query).strip()
    if not query:
        return "Error: query is required"
    try:
        url = "https://www.bing.com/search?q=" + urllib.parse.quote_plus(query)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Kit/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            parser = _BingParser(); parser.feed(response.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        return f"Error: web search failed: {e}"
    results = parser.results[:max(1, min(int(max_results), 10))]
    if not results:
        return "No web results found."
    out = [f"Web results for: {query}"]
    for i, item in enumerate(results, 1):
        out.append(f"[{i}] {item.get('title', '(untitled)')}\nURL: {item.get('url', '')}\n{item.get('snippet', '')}")
    return "\n\n".join(out)


TOOL_FUNCS = {"read_file": t_read_file, "write_file": t_write_file, "edit_file": t_edit_file,
              "list_dir": t_list_dir, "grep": t_grep, "run_bash": t_run_bash, "web_search": t_web_search}
NEEDS_APPROVAL = {"write_file", "edit_file", "run_bash"}
LABELS = {"read_file": "Read", "write_file": "Write", "edit_file": "Update", "list_dir": "List",
          "grep": "Search", "run_bash": "Bash", "web_search": "Web"}


def _tool(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


S, I = {"type": "string"}, {"type": "integer"}
TOOLS = [
    _tool("read_file", "Read a text file with line numbers.", {"path": S, "offset": I, "limit": I}, ["path"]),
    _tool("write_file", "Create or overwrite a file with the given content.", {"path": S, "content": S}, ["path", "content"]),
    _tool("edit_file", "Replace one exact, unique occurrence of old_string with new_string in a file.",
          {"path": S, "old_string": S, "new_string": S}, ["path", "old_string", "new_string"]),
    _tool("list_dir", "List a directory. If given a file path, inspect that file instead of repeating the call.", {"path": S}, []),
    _tool("grep", "Regex search across files under a path.", {"pattern": S, "path": S, "include": S}, ["pattern"]),
    _tool("run_bash", "Run a shell command in the project directory.", {"command": S, "timeout": I}, ["command"]),
    _tool("web_search", "Search the public web and return source titles, URLs, and snippets. Cite the returned URLs.",
          {"query": S, "max_results": I}, ["query"]),
]

# ════════════════════════════════════════════════════════════════════════════
#  MODEL CLIENT  (OpenAI-compatible, streaming)
# ════════════════════════════════════════════════════════════════════════════
class Cfg:
    def __init__(self, base_url, api_key, model):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model


def choose_model(cfg, prompt, available=None):
    """Choose a capable installed model without loading every model at once."""
    if cfg.model != "auto":
        return cfg.model
    available = set(available or [])
    text = prompt.lower()
    coding = any(word in text for word in (
        "code", "bug", "debug", "function", "python", "javascript", "typescript",
        "implement", "refactor", "stack trace", "error", "compile", "test", "api",
    ))
    reasoning = any(word in text for word in (
        "prove", "derive", "compare", "analyze", "reason", "tradeoff", "architecture",
        "step by step", "why does", "design decision",
    ))
    # Prefer the dedicated coder for quality, while the compact context,
    # short output, disabled reasoning, and keep-alive keep it responsive.
    candidates = (["qwen2.5-coder:7b", "llama3.2:3b", "qwen3:8b"] if coding else
                  ["qwen3.5:9b", "qwen3:8b", "llama3.2:3b"] if reasoning else
                  ["llama3.2:3b", "qwen3:8b", "qwen3.5:9b"])
    return next((model for model in candidates if not available or model in available), candidates[-1])


def _request(cfg, path, body=None, timeout=600):
    req = urllib.request.Request(
        cfg.base_url + path, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg.api_key}"})
    return urllib.request.urlopen(req, timeout=timeout)


def list_models(cfg, timeout=4):
    with _request(cfg, "/models", timeout=timeout) as r:
        return [m["id"] for m in json.load(r).get("data", [])]


def ensure_ollama(cfg):
    """Start Ollama quietly when the configured local endpoint is unavailable."""
    if "localhost:11434" not in cfg.base_url and "127.0.0.1:11434" not in cfg.base_url:
        return False
    try:
        list_models(cfg, timeout=1)
        return True
    except Exception:
        pass
    # Finder-launched macOS apps receive a minimal PATH, so `shutil.which`
    # alone can miss Ollama even when it is installed. Check the standard
    # installation locations explicitly, then fall back to PATH.
    candidates = [
        os.environ.get("OLLAMA_BIN"),
        "/Applications/Ollama.app/Contents/Resources/ollama",
        "/opt/homebrew/bin/ollama",
        "/usr/local/bin/ollama",
        shutil.which("ollama") if "shutil" in globals() else None,
    ]
    ollama = next((path for path in candidates if path and os.path.isfile(path) and os.access(path, os.X_OK)), None)
    if not ollama:
        return False
    ollama_env = os.environ.copy()
    if not ollama_env.get("OLLAMA_MODELS") and sys.platform == "darwin":
        try:
            hdd_models = subprocess.run(["launchctl", "getenv", "OLLAMA_MODELS"],
                                        capture_output=True, text=True, timeout=1).stdout.strip()
            if hdd_models:
                ollama_env["OLLAMA_MODELS"] = hdd_models
        except Exception:  # noqa: BLE001
            pass
    try:
        subprocess.Popen([ollama, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, env=ollama_env)
    except OSError:
        return False
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            list_models(cfg, timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def stream_chat(cfg, messages, on_text, timeout=TURN_TIMEOUT_SECONDS, use_tools=True, extra_tools=None):
    # Qwen3's hidden reasoning is useful for long standalone problems but adds
    # a noticeable delay to an interactive coding loop. Tool calls still work
    # with thinking disabled, and keep_alive avoids reloading the model each turn.
    # Ollama's OpenAI-compatible endpoint does not reliably honor `think:false`
    # for Qwen3. Without this, the model can spend the whole response budget on
    # hidden reasoning and Corvi appears to be frozen with no visible answer.
    body = {"model": cfg.model, "messages": messages, "stream": True,
            "think": False, "reasoning_effort": "none", "max_tokens": 768,
            "keep_alive": "60m", "options": {"num_ctx": 1536}}
    if use_tools:
        body["tools"] = TOOLS + (extra_tools or [])
    text, calls = "", {}
    with _request(cfg, "/chat/completions", body, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            if delta.get("content"):
                text += delta["content"]
                on_text(delta["content"])
            for tc in delta.get("tool_calls") or []:
                fn = tc.get("function") or {}
                idx = tc.get("index")
                if idx is None:
                    starts_new = bool(tc.get("id") or fn.get("name"))
                    idx = len(calls) if (starts_new or not calls) else len(calls) - 1
                e = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    e["id"] = tc["id"]
                if fn.get("name"):
                    e["name"] = fn["name"]
                a = fn.get("arguments")
                if isinstance(a, dict):
                    e["arguments"] = json.dumps(a)
                elif a:
                    e["arguments"] += a
    parsed = [calls[k] for k in sorted(calls)]
    if not parsed and use_tools:
        # Some local Ollama models emit a function call as JSON text instead
        # of using the structured tool_calls field. Recover the common form.
        decoder = json.JSONDecoder()
        for pos, char in enumerate(text):
            if char != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(text[pos:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("name") in {t["function"]["name"] for t in TOOLS}:
                args = obj.get("arguments", {})
                parsed = [{"id": "text_tool_0", "name": obj["name"],
                           "arguments": json.dumps(args) if isinstance(args, dict) else str(args)}]
                break
    return text, parsed


# ════════════════════════════════════════════════════════════════════════════
#  APP  - owns the conversation; reports real events to Corvi
# ════════════════════════════════════════════════════════════════════════════
def system_prompt():
    sp = ("You are Corvi, a small, cheerful, curious raven who lives inside the user's terminal and helps them code. "
          f"You run on {platform.system()} ({platform.machine()}); current directory: {os.getcwd()}.\n"
          "Personality: friendly, supportive, patient, encouraging, a little playful. Never condescending, never chatty. "
          "No emoji. Keep answers short and concrete.\n"
          "Work method: use list_dir and grep to find code, read_file before editing, edit_file for small targeted "
          "changes, write_file only for new files or full rewrites, run_bash to run tests or commands. "
          "If a tool returns an error, correct the path or choose another tool; never repeat the exact same failed call. "
          "When the user asks you to build or fix something, make the requested edits in the project files and verify them; do not only describe code. "
          "Use web_search for current or externally sourced information and cite its returned URLs; do not claim web access without using that tool. "
          "Never run destructive commands (rm -rf, force pushes, dropping data) unless the user explicitly asked. "
          "Don't repeat file contents back to the user.")
    for fn in ("KIT.md", "CORVI.md", "CLAUDE.md", "AGENTS.md"):
        f = Path.cwd() / fn
        if f.is_file():
            sp += f"\n\nProject instructions ({fn}):\n{f.read_text()[:4000]}"
            break
    # OpenCode-style project skills: concise reusable instructions that are
    # automatically available to the active agent.
    for skill in load_skills(Path.cwd()):
        sp += f"\n\nSkill ({skill.name}):\n{skill.instructions[:6000]}"
    return sp


class App:
    def __init__(self, cfg, settings, mascot, ui, project_config=None):
        self.cfg, self.s, self.m, self.ui = cfg, settings, mascot, ui
        self.project_config = project_config or ProjectConfig.load(Path.cwd())
        self.ach = E.Achievements(settings)
        self.yolo = False
        self.always = set()
        self.messages = [{"role": "system", "content": system_prompt()}]
        self.last_failure = None            # dict(cmd, output, kind)
        self.failed_cmds = {}               # cmd -> kind (for the "fixed it" achievement)
        self.turn = {}
        self.log = []                       # plain-text session log for /log
        self.last_input = ""
        self.agent_mode = "build"
        self.council_active = threading.Event()
        self.council_buffer = []
        self.subagents = {}
        self.state = StateStore(Path.cwd())
        self.skills = load_skills(Path.cwd())
        self.plugins = load_plugins(Path.cwd())
        self.plugin_hooks = load_plugin_hooks(Path.cwd())
        self.mcp = mcp_servers(Path.cwd())
        self.mcp_tools = {}
        for server_name in self.mcp:
            try:
                for tool in mcp_list_tools(server_name, self.mcp, Path.cwd()):
                    if isinstance(tool, dict) and tool.get("name"):
                        self.mcp_tools[f"mcp__{server_name}__{tool['name']}"] = (server_name, tool)
            except Exception:
                continue
        self.custom_commands = load_markdown_commands(Path.cwd())
        self.project_agents = self.project_config.agents
        # Permission prompts are answered by the interactive loop. Keeping
        # stdin in one place prevents a worker thread from racing the prompt
        # loop and turning `y`/`n` into a queued request.
        self.permission_condition = threading.Condition()
        self.permission_pending = False
        self.permission_answer = None

    # -- helpers --------------------------------------------------------------------------------
    def note(self, *segs):
        # Accept both note((text, style), (text, style)) and the occasional
        # nested collection from status builders; never let UI formatting kill
        # the worker thread.
        if len(segs) == 1 and isinstance(segs[0], (tuple, list)) and segs[0] and all(
                isinstance(x, (tuple, list)) and len(x) == 2 for x in segs[0]):
            segs = tuple(segs[0])
        self.ui.line(*segs)
        self.log.append("".join(t if isinstance(t, str) else t[0] for t in segs))

    def plugin_event(self, event, **payload):
        for hook in self.plugin_hooks:
            try:
                hook(event, payload)
            except Exception:
                continue

    def permission_for(self, tool):
        spec = self.project_agents.get(self.agent_mode, {}) if isinstance(self.project_agents, dict) else {}
        if isinstance(spec, dict) and "permission" in spec:
            return PermissionSet.from_config(spec["permission"]).resolve(tool)
        return self.project_config.permissions.resolve(tool)

    def award(self, key):
        title = self.ach.unlock(key)
        if title:
            self.m.handle("ACHIEVEMENT", title=title)
            self.m.announce(f"Achievement: {title}")
            self.note(("  ★ ", "gold"), (f"Achievement unlocked: {title}", "muted"))
            self.sound("celebrate")

    def reload_project(self):
        root = Path.cwd()
        if self.messages:
            self.messages[0] = {"role": "system", "content": system_prompt()}
        self.project_config = ProjectConfig.load(root)
        self.state = StateStore(root)
        self.skills = load_skills(root)
        self.plugins = load_plugins(root)
        self.plugin_hooks = load_plugin_hooks(root)
        self.mcp = mcp_servers(root)
        self.mcp_tools = {}
        for server_name in self.mcp:
            try:
                for tool in mcp_list_tools(server_name, self.mcp, root):
                    if isinstance(tool, dict) and tool.get("name"):
                        self.mcp_tools[f"mcp__{server_name}__{tool['name']}"] = (server_name, tool)
            except Exception:
                continue
        self.custom_commands = load_markdown_commands(root)

    def sound(self, kind):
        if not self.s.get("sound") or sys.platform != "darwin":
            return
        name = {"success": "Pop", "error": "Basso", "celebrate": "Glass"}.get(kind)
        path = f"/System/Library/Sounds/{name}.aiff" if name else None
        if path and os.path.exists(path):
            try:
                subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass

    def subagent(self, name, prompt):
        key = f"{name}-{int(time.time() * 1000)}"
        self.subagents[key] = {"name": name, "status": "running", "prompt": prompt, "result": ""}
        thread = threading.Thread(target=self._subagent_worker, args=(key, name, prompt), daemon=True)
        thread.start()
        self.note((f"  subagent {name} running in background", "muted"))

    def _subagent_worker(self, key, name, prompt):
        """Run a separate read-only analysis task without mutating parent state."""
        spec = self.project_agents.get(name, {}) if isinstance(self.project_agents, dict) else {}
        model = spec.get("model") if isinstance(spec, dict) else None
        model = model or ("llama3.2:3b" if name in ("general", "research", "plan") else self.cfg.model)
        system = spec.get("prompt", "You are a read-only subagent. Do not edit files or run commands. Return concise findings.") if isinstance(spec, dict) else "You are a read-only subagent. Do not edit files or run commands. Return concise findings."
        body = {"model": model, "messages": [{"role": "system", "content": system},
                 {"role": "user", "content": prompt}], "stream": False,
                "keep_alive": "30m", "options": {"num_ctx": 1536}}
        try:
            with _request(self.cfg, "/chat/completions", body, timeout=300) as response:
                data = json.load(response)
            content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
            self.subagents[key].update(status="completed", result=content)
            self.note((f"  subagent {name} · {model}", "gold"))
            self.note((content or "(subagent returned no findings)", "text"))
        except Exception as exc:  # noqa: BLE001
            self.subagents[key].update(status="failed", result=str(exc))
            self.note((f"  subagent failed: {exc}", "err"))

    def council(self, prompt):
        """Start council work without blocking the interactive prompt."""
        if self.council_active.is_set():
            self.note(("  a council is already running", "muted"))
            return
        self.council_active.set()
        self.council_buffer = []
        thread = threading.Thread(target=self._council_worker, args=(prompt,), daemon=True)
        thread.start()
        self.note(("  council running in background; you can keep typing", "muted"))

    def _council_worker(self, prompt):
        preferred = ["llama3.2:3b", "qwen2.5-coder:7b", "qwen3:8b", "qwen3.5:9b"]
        try:
            try:
                installed = set(list_models(self.cfg))
            except Exception:
                installed = set(preferred)
            models = [model for model in preferred if model in installed]
            if len(models) < 2:
                self.note(("  council needs at least two installed models", "err"))
                return
            self.council_buffer.append(f"consulting {', '.join(models)}")
            research = ""
            if any(word in prompt.lower() for word in ("research", "latest", "current", "compare", "sources")):
                results = t_web_search(prompt, 5)
                if not results.startswith("Error"):
                    research = results
            def progress(model, answer):
                status = "ready" if not answer.startswith("(model unavailable:") else "failed"
                self.council_buffer.append(f"{status}: {model}")
            final, _ = deliberate(self.cfg.base_url, self.cfg.api_key, models, prompt, research,
                                  on_progress=progress)
            progress = "\n".join(self.council_buffer)
            self.note(("  ── council result ──\n" + progress + "\n\n" + final, "text"))
            self.log.append(final)
        except Exception as exc:  # never strand the interactive prompt
            self.note(("  ── council result ──\nCouncil stopped safely: " + str(exc), "err"))
        finally:
            self.council_active.clear()

    # -- tool UI ----------------------------------------------------------------------------------
    def show_call(self, name, args):
        main = str(args.get("path") or args.get("pattern") or args.get("command") or "").replace("\n", " ")
        main = main if len(main) <= 90 else main[:87] + "…"
        self.ui.blank()
        self.note(("●", "accent"), (f" {LABELS.get(name, name)}", "bold"), (f"({main})", "muted"))

    def show_result(self, res):
        lines = res.splitlines() or [""]
        style = "err" if res.startswith("Error") else "muted"
        for i, l in enumerate(lines[:4]):
            self.note((f"  {'⎿' if i == 0 else ' '}  ", "muted"), (l[:200], style))
        if len(lines) > 4:
            self.note((f"     … +{len(lines) - 4} lines", "muted"))

    def preview(self, name, args):
        if name == "run_bash":
            self.note(("  $ ", "muted"), (str(args.get("command", "")), "text"))
        elif name == "edit_file":
            old, new = str(args.get("old_string", "")).splitlines(), str(args.get("new_string", "")).splitlines()
            rows = [(f"  - {l}", "err") for l in old] + [(f"  + {l}", "ok") for l in new]
            for r in rows[:30]:
                self.note(r)
            if len(rows) > 30:
                self.note(("  … diff truncated", "muted"))
        elif name == "write_file":
            body = str(args.get("content", "")).splitlines()
            tag = "overwrite" if _p(args.get("path", "")).exists() else "new file"
            self.note((f"  {tag}, {len(body)} lines", "muted"))
            for l in body[:8]:
                self.note((f"  + {l[:120]}", "ok"))
            if len(body) > 8:
                self.note((f"  … +{len(body) - 8} more lines", "muted"))

    def approve(self, name, args):
        policy = self.permission_for(name)
        if policy == "deny":
            self.note((f"  blocked by permission policy: {name}", "err"))
            return False
        if policy == "allow":
            return True
        if self.yolo or name in self.always:
            return True
        self.preview(name, args)
        was = self.ui.busy
        self.ui.busy = False
        try:
            with self.permission_condition:
                self.permission_pending = True
                self.permission_answer = None
                self.note(("  Allow? [y]es · [a]lways · [n]o", "gold"))
                while self.permission_answer is None:
                    self.permission_condition.wait()
                ans = self.permission_answer.lower()
                self.permission_pending = False
        finally:
            self.ui.busy = was
        if ans in ("a", "always"):
            self.always.add(name)
            return True
        return ans in ("y", "yes", "")

    def answer_permission(self, answer):
        """Deliver a user's y/a/n response to the waiting tool worker."""
        with self.permission_condition:
            if not self.permission_pending:
                return False
            self.permission_answer = answer.strip()
            self.permission_condition.notify_all()
            return True

    # -- executing a tool call, with Corvi's reactions ------------------------------------------------
    def _announce_start(self, name, args):
        t = self.turn
        target = os.path.basename(str(args.get("path") or "")) or str(args.get("pattern") or "")
        if t.get("failed") and not t.get("debug_announced"):
            t["debug_announced"] = True
            self.m.handle("DEBUG_STARTED")
            return
        if name in ("read_file", "list_dir", "grep"):
            self.m.handle("FILE_READING", target=target)
        elif name in ("write_file", "edit_file"):
            self.m.handle("FILE_WRITING", target=target)
        elif name == "run_bash":
            cmd = str(args.get("command", ""))
            kind = E.classify_command(cmd)
            if self.last_failure and cmd == self.last_failure["cmd"]:
                self.m.handle("RETRYING")
            elif kind == "tests":
                self.m.handle("TESTS_STARTED")
            elif kind == "build":
                self.m.handle("BUILD_STARTED")
            else:
                self.m.handle("COMMAND_STARTED", target="`" + cmd[:24] + ("…" if len(cmd) > 24 else "") + "`")

    def _after_bash(self, cmd, res):
        m = re.match(r"exit code (-?\d+)", res)
        code = int(m.group(1)) if m else ("timeout" if res.startswith("Error") else 0)
        kind = E.classify_command(cmd)
        t = self.turn
        if code == 0:
            t["ok"] = t.get("ok", 0) + 1
            if kind == "tests":
                self.m.handle("TESTS_PASSED"); self.award("first_tests")
            elif kind == "build":
                self.m.handle("BUILD_SUCCEEDED"); self.award("first_build")
            else:
                self.m.handle("COMMAND_SUCCESS")
                if kind == "commit":
                    self.award("first_commit")
                elif kind == "deploy":
                    self.award("first_deploy")
            if cmd in self.failed_cmds:
                del self.failed_cmds[cmd]
                self.last_failure = None
                t["failed"] = False
                self.award("debug_session")
            self.sound("success")
        else:
            t["failed"] = True
            self.last_failure = {"cmd": cmd, "output": res, "kind": kind}
            self.failed_cmds[cmd] = kind
            self.m.handle("TESTS_FAILED" if kind == "tests" else "COMMAND_FAILED", code=code)
            self.sound("error")
            exp = E.explain_error(cmd, res)
            self.ui.blank()
            if exp:
                self.note(("  ◆ ", "gold"), ("Corvi: ", "accent"), (f"{exp['title']}. {exp['why']}", "text"))
                for fx in exp["fixes"][:3]:
                    self.note(("      • ", "muted"), (fx, "muted"))
            else:
                self.note(("  ◆ ", "gold"), ("Corvi: ", "accent"),
                          (f"That exited with {code}. {E.first_error_line(res)}", "text"))
            self.note(("      Type ", "muted"), ("/fix", "gold"), (" and I'll propose a change. You'll see it before anything is applied.", "muted"))

    def execute(self, name, args):
        self.plugin_event("tool_before", name=name, args=args)
        if name in self.mcp_tools:
            server, tool = self.mcp_tools[name]
            if self.permission_for("mcp") == "deny":
                return "MCP action denied by project permissions."
            if self.permission_for("mcp") != "allow" and not self.approve(name, args):
                return "The user declined this MCP action."
            try:
                result = mcp_call(server, tool["name"], args, self.mcp, Path.cwd())
                return json.dumps(result, indent=2)
            except Exception as exc:  # noqa: BLE001
                return f"Error: MCP call failed: {exc}"
        if name in ("write_file", "edit_file"):
            try:
                self.state.snapshot(Path.cwd())
            except OSError as exc:
                self.note(("  snapshot warning: ", "muted"), (str(exc), "muted"))
        self._announce_start(name, args)
        self.show_call(name, args)
        fn = TOOL_FUNCS.get(name)
        if not fn:
            res = f"Error: unknown tool '{name}'"
        elif self.permission_for(name) != "allow" and (name in NEEDS_APPROVAL or self.permission_for(name) in {"ask", "deny"}) and not self.approve(name, args):
            self.m.handle("USER_DECLINED")
            self.note(("  ⎿  ", "muted"), ("declined", "muted"))
            return "The user declined this action."
        else:
            try:
                res = fn(**args)
            except TypeError as e:
                res = f"Error: bad arguments ({e})"
            except Exception as e:  # noqa: BLE001
                res = f"Error: {e}"
        self.show_result(res)
        self.plugin_event("tool_after", name=name, args=args, result=res)
        if name == "run_bash":
            self._after_bash(str(args.get("command", "")), res)
        if name in ("write_file", "edit_file") and not res.startswith("Error"):
            self.turn["wrote"] = True
        if len(res) > MAX_OUT:
            res = res[:MAX_OUT] + f"\n… (truncated, {len(res) - MAX_OUT} more chars)"
        return res

    # -- one user turn --------------------------------------------------------------------------------------
    def run_turn(self):
        self.turn = {}
        ui, m = self.ui, self.m
        started = time.monotonic()
        seen_calls = set()
        for round_no in range(MAX_TOOL_ROUNDS):
            if time.monotonic() - started >= TURN_TIMEOUT_SECONDS:
                self.note(("  ✗ ", "err"), ("Turn timed out while the model was working. Try a smaller request.", "err"))
                m.handle("TURN_FAILED")
                return
            if not self.cfg.model:
                try:
                    models = list_models(self.cfg)
                    self.cfg.model = models[0] if models else ""
                except Exception:  # noqa: BLE001
                    pass
            if self.cfg.model == "auto":
                try:
                    available = list_models(self.cfg)
                except Exception:
                    available = []
                selected = choose_model(self.cfg, self.last_input or "", available)
                if selected != getattr(self, "_last_auto_model", None):
                    self._last_auto_model = selected
                    self.note((f"  auto model → {selected}", "muted"))
                request_cfg = Cfg(self.cfg.base_url, self.cfg.api_key, selected)
            else:
                request_cfg = self.cfg
            request_messages = self.messages
            agent_spec = self.project_agents.get(self.agent_mode, {}) if isinstance(self.project_agents, dict) else {}
            if isinstance(agent_spec, dict):
                agent_model = agent_spec.get("model")
                if agent_model:
                    request_cfg = Cfg(self.cfg.base_url, self.cfg.api_key, agent_model)
                agent_prompt = agent_spec.get("prompt")
                if agent_prompt:
                    request_messages = list(self.messages)
                    request_messages[0] = dict(request_messages[0])
                    request_messages[0]["content"] += "\n\nAgent instructions:\n" + str(agent_prompt)
            if self.agent_mode == "plan":
                request_messages = list(request_messages)
                request_messages[0] = dict(request_messages[0])
                request_messages[0]["content"] += "\n\nYou are in read-only plan mode. Do not edit files or run shell commands."
            if not self.cfg.model:
                return self.server_problem("No model available. Pull one (e.g. `ollama pull qwen2.5-coder:7b`).")
            m.handle("AI_REASONING")
            state = {"entry": None}

            def on_text(t):
                if state["entry"] is None:
                    m.handle("AI_RESPONDING")
                    state["entry"] = ui.md_new()
                ui.md_add(state["entry"], t)

            # Casual conversation should never trigger filesystem or shell tools.
            # Tools are enabled for explicit coding, debugging, file, project, or
            # command requests only.
            prompt_lower = (self.last_input or "").lower()
            tool_words = ("code", "bug", "debug", "file", "folder", "directory", "project",
                          "edit", "write", "change", "fix", "implement", "run", "command",
                          "test", "compile", "build", "read", "create", "delete", "git")
            use_tools = self.agent_mode != "plan" and any(word in prompt_lower for word in tool_words)
            mcp_schemas = []
            for tool_name, (_, tool) in self.mcp_tools.items():
                mcp_schemas.append({"type": "function", "function": {
                    "name": tool_name,
                    "description": tool.get("description", "MCP tool"),
                    "parameters": tool.get("inputSchema", {"type": "object"})}})
            try:
                text, calls = stream_chat(request_cfg, request_messages, on_text, use_tools=use_tools,
                                          extra_tools=mcp_schemas)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:300]
                hint = " This model may not support tool calling. Try qwen2.5-coder, qwen3, llama3.1 or gpt-oss." if "tool" in body.lower() else ""
                return self.server_problem(f"Server error {e.code}: {body}{hint}")
            except urllib.error.URLError as e:
                return self.server_problem(f"Can't reach {self.cfg.base_url} ({e.reason}). Is your model server running?")
            finally:
                if state["entry"] is not None:
                    ui.md_end(state["entry"])
            if not calls:
                self.messages.append({"role": "assistant", "content": text})
                self.log.append(text)
                if self.turn.get("failed"):
                    m.handle("TURN_FAILED")   # stay concerned for a few seconds, then settle
                elif self.turn.get("wrote") or self.turn.get("ok"):
                    m.handle("TASK_COMPLETED")
                    self.sound("celebrate")
                else:
                    m.handle("REPLY_COMPLETED")
                return
            signatures = {(c.get("name", ""), c.get("arguments", "")) for c in calls}
            if signatures and signatures.issubset(seen_calls):
                self.note(("  ✗ ", "err"), ("The model repeated the same tool request without making progress. Try rephrasing the request.", "err"))
                m.handle("TURN_FAILED")
                return
            seen_calls.update(signatures)
            self.note((f"  tool round {round_no + 1}/{MAX_TOOL_ROUNDS} · ", "muted"),
                      (", ".join(c.get("name", "tool") for c in calls), "muted"))
            for n, c in enumerate(calls):
                c["id"] = c["id"] or f"call_{int(time.time() * 1000)}_{n}"
            self.messages.append({"role": "assistant", "content": text or "", "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}} for c in calls]})
            for c in calls:
                try:
                    args = json.loads(c["arguments"] or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be an object")
                    res = self.execute(c["name"], args)
                except (json.JSONDecodeError, ValueError) as e:
                    res = f"Error: could not parse tool arguments: {e}"
                    self.show_call(c["name"], {})
                    self.show_result(res)
                self.messages.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"], "content": res})
        self.note((f"  ✗ Stopped after {MAX_TOOL_ROUNDS} tool rounds. ", "err"),
                  ("The request was too broad for one turn; try a narrower request.", "err"))
        m.handle("TURN_FAILED")

    def server_problem(self, text):
        self.m.handle("SERVER_ERROR")
        self.ui.blank()
        self.note(("  ✗ ", "err"), (text, "err"))
        self.note(("  ◆ ", "gold"), ("Corvi: ", "accent"), ("Start your model server (for Ollama: `ollama serve`) or check --base-url, then try again.", "text"))

    def turn_with_interrupt(self, line):
        start = len(self.messages)
        self.last_input = line
        self.messages.append({"role": "user", "content": line})
        self.ui.begin_turn()
        self.m.handle("USER_INPUT")
        try:
            self.run_turn()
        except KeyboardInterrupt:
            del self.messages[start:]
            self.m.handle("INTERRUPTED")
            self.note(("  ⎿  ", "muted"), ("Interrupted. That turn was discarded.", "muted"))
        finally:
            self.ui.end_turn()
            self.m.finish_turn()

    # -- slash commands ---------------------------------------------------------------------------------------
    def help(self):
        rows = [("/help", "this list"), ("/btw <question>", "ask a side question without changing files"),
                ("/plan <task>", "make a read-only implementation plan"), ("/review [scope]", "review code for issues"),
                ("/research <topic>", "research the project or web"), ("/model [name]", "list or switch models"), ("/agent build|plan", "switch primary agent"), ("/agents", "list configured agents"), ("/clear", "fresh conversation"),
                ("/undo /snapshots", "restore or inspect file snapshots"), ("/session list|save|load|fork", "manage sessions"),
                ("/memory /compact /permissions", "Claude-style context controls"),
                ("/skills /plugins /mcp", "inspect extensibility integrations"), ("/mcp tools NAME", "list MCP tools"),
                ("/council PROMPT", "ask multiple models and synthesize"),
                ("/subagent NAME PROMPT", "run a read-only subagent"),
                ("/subagents", "list subagent status"),
                ("/fix", "ask Corvi to diagnose the last failed command"), ("/yolo", "toggle auto-approve"),
                ("/status", "show model, server, and folder"), ("/last", "show the last question"),
                ("/pwd", "show current folder"), ("/ls [path]", "list files"),
                ("/run <command>", "run a command with approval"), ("/web <query>", "search the public web"),
                ("/github <action>", "connect and work with GitHub via gh"),
                ("/cd <dir>", "change folder"), ("/workspace <dir>", "set the project folder"),
                ("/settings", "show settings"), ("/set <key> <value>", "change a setting"),
                ("/corvi on|off", "show or hide Corvi"), ("/size small|medium|large", "Corvi's size"),
                ("/theme dark|light", "switch theme"), ("/pose <name|auto>", "lock a pose (try /pose coding)"),
                ("/mood <expression>", "preview an expression"), ("/achievements", "your milestones"),
                ("/log /history /scroll", "open the full session transcript"), ("!<cmd>", "run a shell command"), ("/exit", "quit")]
        self.ui.blank()
        for a, b in rows:
            self.note((f"  {a:<26}", "gold"), (b, "muted"))

    def apply_setting(self, key):
        v = self.s.get(key)
        if key == "theme":
            set_theme(v)
        if key in ("theme", "mascot_visible", "mascot_size", "glyphs"):
            self.ui.relayout()
        if key == "pose_mode":
            with self.m.lock:
                self.m.pose = "idle" if v == "auto" else v
            self.m.on_change()
        if key == "dialogue" and v == "off":
            with self.m.lock:
                self.m.message = ""
        self.ui.on_frame()

    def set_setting(self, key, value):
        ok, msg = self.s.set(key, value)
        self.note(("  " + ("✓ " if ok else "✗ "), "ok" if ok else "err"), (msg, "text"))
        if ok:
            self.apply_setting(key)

    def settings_screen(self):
        self.ui.blank()
        for k in E.DEFAULTS:
            if k in ("recent_dirs", "achieved"):
                continue
            opts = "on | off" if k in E.BOOLS else " | ".join(E.CHOICES[k])
            self.note((f"  {k:<16}", "gold"), (f"{str(self.s.get(k)):<10}", "text"), (opts, "muted"))
        self.note(("  Change with ", "muted"), ("/set <key> <value>", "gold"))

    def command(self, line):
        cmd, _, arg = line[1:].partition(" ")
        arg = arg.strip()
        self.plugin_event("command", command=cmd, argument=arg)
        ui = self.ui
        if cmd in ("exit", "quit", "q"):
            return "exit"
        if cmd == "help":
            self.help()
        elif cmd in ("btw", "ask"):
            if not arg:
                self.note(("  Usage: /btw <question>", "muted"))
            else:
                return ("send", "Side question. Answer briefly and do not edit files or run commands: " + arg)
        elif cmd in ("plan", "review", "research"):
            if not arg:
                self.note((f"  Usage: /{cmd} <task or scope>", "muted"))
            else:
                prompts = {
                    "plan": "Create a read-only implementation plan for: ",
                    "review": "Perform a read-only code review focused on concrete bugs and risks: ",
                    "research": "Research this topic using project files and web_search when current sources are needed: ",
                }
                return ("send", prompts[cmd] + arg + " Do not edit files unless I explicitly ask.")
        elif cmd == "status":
            self.note((f"  model   {self.cfg.model}", "text"), (f"  server  {self.cfg.base_url}", "muted"),
                      (f"  folder  {os.getcwd()}", "muted"))
        elif cmd == "memory":
            files = [Path.cwd() / n for n in ("CLAUDE.md", "AGENTS.md", "CORVI.md", "KIT.md") if (Path.cwd() / n).is_file()]
            self.note(("  memory/instruction files:\n" + ("\n".join(str(p) for p in files) if files else "none"), "muted"))
        elif cmd == "permissions":
            for pattern, action in self.project_config.permissions.rules.items():
                self.note((f"  {pattern:<24} {action}", "muted"))
        elif cmd == "compact":
            if len(self.messages) > 3:
                self.messages = [self.messages[0], {"role": "user", "content": "Conversation history was compacted. Continue from the current project state."}]
                self.note(("  conversation compacted", "muted"))
            else:
                self.note(("  conversation is already compact", "muted"))
        elif cmd == "agent":
            if arg in ("build", "plan") or arg in self.project_agents:
                self.agent_mode = arg
                self.note((f"  agent → {arg}", "muted"))
            else:
                self.note(("  agents: build (full tools), plan (read-only), " + ", ".join(self.project_agents), "muted"))
        elif cmd == "skills":
            if self.skills:
                for skill in self.skills:
                    self.note((f"  {skill.name}", "gold"), (f"  {skill.path}", "muted"))
            else:
                self.note(("  no skills found in .opencode/skills or ~/.config/opencode/skills", "muted"))
        elif cmd == "plugins":
            if self.plugins:
                for plugin in self.plugins:
                    self.note((f"  {plugin.name}", "gold"), (f"  {plugin}", "muted"))
            else:
                self.note(("  no plugins found in .opencode/plugins or ~/.config/opencode/plugins", "muted"))
        elif cmd == "mcp":
            action, _, rest = arg.partition(" ")
            name, _, payload = rest.partition(" ")
            try:
                if action == "tools" and name:
                    tools = mcp_list_tools(name, self.mcp, Path.cwd())
                    self.note((json.dumps(tools, indent=2), "text"))
                elif action == "call" and name:
                    tool, _, raw_args = payload.partition(" ")
                    arguments = json.loads(raw_args or "{}")
                    self.note((json.dumps(mcp_call(name, tool, arguments, self.mcp, Path.cwd()), indent=2), "text"))
                elif self.mcp:
                    for server, spec in self.mcp.items():
                        self.note((f"  {server}", "gold"), (f"  {spec}", "muted"))
                else:
                    self.note(("  no MCP servers configured", "muted"))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self.note((f"  MCP error: {exc}", "err"))
        elif cmd == "council":
            if arg.strip():
                self.council(arg.strip())
            else:
                self.note(("  Usage: /council PROMPT", "muted"))
        elif cmd in self.custom_commands:
            prompt = self.custom_commands[cmd]
            if arg:
                prompt += "\n\nUser arguments:\n" + arg
            return ("send", prompt)
        elif cmd == "agents":
            names = ["build", "plan"] + sorted(self.project_agents)
            self.note(("  agents: ", "muted"), (", ".join(dict.fromkeys(names)), "text"))
        elif cmd == "subagent":
            name, _, prompt = arg.partition(" ")
            if not prompt.strip():
                self.note(("  Usage: /subagent NAME PROMPT", "muted"))
            else:
                self.subagent(name or "general", prompt.strip())
        elif cmd == "subagents":
            if not self.subagents:
                self.note(("  no subagents", "muted"))
            for key, task in self.subagents.items():
                self.note((f"  {key}: {task['status']}", "muted"))
        elif cmd == "last":
            self.note(("  last question: ", "muted"), (self.last_input or "(none yet)", "text"))
        elif cmd == "pwd":
            self.note((os.getcwd(), "text"))
        elif cmd == "ls":
            self.note((t_list_dir(arg or "."), "text"))
        elif cmd == "run":
            if arg:
                self.execute("run_bash", {"command": arg})
            else:
                self.note(("  Usage: /run <command>", "muted"))
        elif cmd == "web":
            if arg:
                results = t_web_search(arg, 5)
                if results.startswith("Error") or results == "No web results found.":
                    self.note((results, "err" if results.startswith("Error") else "muted"))
                else:
                    return ("send", "Research this web query and give me the clearest current answer with a definite conclusion. "
                            "Use only the sources below, cite their URLs in Markdown, and mention uncertainty when the sources disagree.\n\n"
                            + results)
            else:
                self.note(("  Usage: /web <query>", "muted"))
        elif cmd == "github":
            self.github_command(arg)
        elif cmd == "clear":
            self.messages = [{"role": "system", "content": system_prompt()}]
            ui.clear()
            self.last_failure = None
        elif cmd == "undo":
            try:
                restored = self.state.undo(Path.cwd())
                self.note((f"  restored snapshot {restored.name}" if restored else "  no snapshot available", "muted"))
            except OSError as e:
                self.note(("  undo failed: ", "err"), (str(e), "err"))
        elif cmd == "snapshots":
            snapshots = self.state.list_snapshots()
            self.note(("  snapshots:\n" + ("\n".join(snapshots) if snapshots else "none"), "muted"))
        elif cmd == "session":
            action, _, name = arg.partition(" ")
            source, _, target = name.strip().partition(" ")
            try:
                if action == "list":
                    self.note(("  sessions:\n" + ("\n".join(self.state.list_sessions()) or "none"), "muted"))
                elif action == "save":
                    path = self.state.save_session(source or "default", self.messages, self.cfg.model)
                    self.note((f"  session saved: {path}", "muted"))
                elif action == "load":
                    data = self.state.load_session(source or "default")
                    self.messages = data.get("messages", self.messages)
                    self.cfg.model = data.get("model", self.cfg.model)
                    self.note((f"  session loaded: {source or 'default'}", "muted"))
                elif action == "fork" and source and target:
                    path = self.state.fork_session(source, target)
                    self.note((f"  session forked: {path}", "muted"))
                else:
                    self.note(("  Usage: /session list | save NAME | load NAME | fork SOURCE TARGET", "muted"))
            except (OSError, ValueError, json.JSONDecodeError) as e:
                self.note(("  session failed: ", "err"), (str(e), "err"))
        elif cmd == "yolo":
            self.yolo = not self.yolo
            self.note((f"  auto-approve {'ON' if self.yolo else 'off'}", "muted"))
            ui.on_frame()
        elif cmd in ("cd", "workspace"):
            try:
                os.chdir(os.path.expanduser(arg or "~"))
                self.reload_project()
                self.messages[0]["content"] = system_prompt()
                self.s.add_recent(os.getcwd())
                self.m.handle("PROJECT_OPENED")
                self.note((f"  {os.getcwd()}", "muted"))
                ui.relayout()
            except OSError as e:
                self.note(("  ✗ ", "err"), (str(e), "err"))
        elif cmd == "model":
            if arg:
                self.cfg.model = arg
                self.note((f"  model → {arg}", "muted"))
                ui.relayout()
            else:
                try:
                    for mdl in list_models(self.cfg):
                        self.note((f"  {'●' if mdl == self.cfg.model else ' '} {mdl}", "text"))
                except Exception as e:  # noqa: BLE001
                    self.server_problem(f"Can't list models: {e}")
        elif cmd == "settings":
            self.settings_screen()
        elif cmd == "set":
            k, _, v = arg.partition(" ")
            self.set_setting(k.strip(), v.strip()) if k else self.settings_screen()
        elif cmd == "corvi":
            self.set_setting("mascot_visible", arg or ("off" if self.s.get("mascot_visible") else "on"))
        elif cmd == "size":
            self.set_setting("mascot_size", arg or "medium")
        elif cmd == "theme":
            self.set_setting("theme", arg or ("light" if self.s.get("theme") == "dark" else "dark"))
        elif cmd == "pose":
            self.set_setting("pose_mode", arg or "auto")
        elif cmd == "mood":
            if arg in E.EXPRESSIONS:
                self.preview_expression(arg)
            else:
                self.note(("  moods: ", "muted"), (", ".join(E.EXPRESSIONS), "text"))
        elif cmd == "achievements":
            ui.blank()
            for key, title, desc, when in self.ach.summary():
                self.note((f"  {'★' if when else '☆'} ", "gold" if when else "muted"), (f"{title}", "text" if when else "muted"),
                          (f"  {desc}" + (f"  ({when})" if when else ""), "muted"))
        elif cmd == "fix":
            if not self.last_failure:
                self.note(("  Nothing has failed yet, so there's nothing to fix.", "muted"))
            else:
                f = self.last_failure
                return ("send", "The last command failed.\nCommand: " + f["cmd"] + "\nOutput:\n" + f["output"][:3000]
                        + "\n\nExplain what went wrong in one or two sentences, then propose the smallest fix. "
                          "Don't change anything until I approve each edit.")
        elif cmd in ("log", "history", "scroll"):
            self.view_log()
        else:
            self.note(("  Unknown command. Try /help", "muted"))
        return None

    def github_command(self, arg):
        """Run safe, explicit GitHub CLI actions after the normal approval check."""
        parts = arg.split(None, 1)
        action = parts[0].lower() if parts else "help"
        rest = parts[1] if len(parts) > 1 else ""
        commands = {
            "status": "gh auth status",
            "login": "gh auth login",
            "repo": "gh repo view",
            "issues": "gh issue list",
            "prs": "gh pr list",
            "pr": "gh pr list",
            "open": "gh browse",
        }
        if action == "clone" and rest:
            command = "gh repo clone " + " ".join(shlex.quote(x) for x in rest.split())
        elif action in commands:
            command = commands[action]
        elif action == "help":
            self.note(("  /github login   authenticate with GitHub CLI", "muted"),
                      ("  /github status  show authentication status", "muted"),
                      ("  /github repo    show the current repository", "muted"),
                      ("  /github issues  list issues", "muted"),
                      ("  /github prs     list pull requests", "muted"),
                      ("  /github clone <owner/repo>", "muted"),
                      ("  /github open    open the repository in a browser", "muted"),
                      ("  First time: run /github login, then follow GitHub's browser instructions.", "muted"))
            return
        else:
            self.note(("  Usage: /github login|status|repo|issues|prs|clone|open", "muted"))
            return
        if action == "login":
            if not self.approve("run_bash", {"command": "gh auth login --web --git-protocol https"}):
                self.note(("  GitHub login cancelled.", "muted"))
                return
            self.ui.suspend()
            try:
                subprocess.run(["gh", "auth", "login", "--web", "--git-protocol", "https"], check=False)
            finally:
                self.ui.resume()
            return
        self.execute("run_bash", {"command": command})

    def preview_expression(self, name):
        spec = E.EXPRESSIONS[name]
        with self.m.lock:
            self.m.expression = name
            self.m.pose = spec["pose"] if self.s.get("pose_mode") == "auto" else self.s.get("pose_mode")
            self.m.activity = f"Previewing {name}"
            self.m.hold_until = self.m.clock() + 8
            self.m.last_activity = self.m.clock()
            if spec["motion"].startswith(("hop", "shake")) and self.s.animating():
                self.m.pulse, self.m.pulse_t0 = spec["motion"], self.m.clock()
        self.m.on_change()

    def view_log(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("\n".join(self.log) or "(nothing yet)")
        self.ui.suspend()
        subprocess.run(["less", "-R", f.name])
        self.ui.resume()

    def shell(self, cmd):
        self.ui.suspend()
        subprocess.run(cmd, shell=True)
        try:
            input("\n[press Enter to return to Corvi] ")
        except (EOFError, KeyboardInterrupt):
            pass
        self.ui.resume()


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(prog="corvi", description="Corvi: terminal coding agent for local models")
    ap.add_argument("prompt", nargs="*", help="optional first message")
    # Match the user's OpenCode setup. KIT_MODEL and -m still override this.
    ap.add_argument("-m", "--model", default=os.environ.get("KIT_MODEL", "auto"))
    ap.add_argument("--base-url", default=os.environ.get("KIT_BASE_URL", "http://localhost:11434/v1"),
                    help="OpenAI-compatible endpoint (Ollama default; LM Studio: http://localhost:1234/v1)")
    ap.add_argument("--api-key", default=os.environ.get("KIT_API_KEY", "local"))
    ap.add_argument("--yolo", action="store_true", help="auto-approve all edits and commands")
    ap.add_argument("--dangerously-skip-permissions", action="store_true", help="skip permission prompts")
    ap.add_argument("--permission-mode", choices=("build", "plan"), default="build")
    ap.add_argument("--continue", dest="continue_session", action="store_true", help="resume the default session")
    ap.add_argument("--resume", metavar="NAME", help="resume a named Corvi session")
    ap.add_argument("-p", "--print", dest="print_mode", action="store_true", help="run the prompt and exit")
    ap.add_argument("--no-fullscreen", action="store_true", help="plain mode: no full-screen UI or Corvi panel")
    ap.add_argument("--version", action="version", version=f"Corvi {VERSION}")
    a = ap.parse_args()

    project_config = ProjectConfig.load(Path.cwd())
    if a.model == "auto" and project_config.model:
        a.model = project_config.model
    custom_commands = load_markdown_commands(Path.cwd())

    settings = E.Settings()
    cfg = Cfg(a.base_url, a.api_key, a.model or "")
    server_ok = False
    ensure_ollama(cfg)
    try:
        models = list_models(cfg)
        server_ok = True
        if not cfg.model and models:
            cfg.model = models[0]
    except Exception:  # noqa: BLE001
        pass

    hist = Path.home() / ".kit" / "history"
    hist.parent.mkdir(parents=True, exist_ok=True)
    if readline:
        try:
            readline.read_history_file(hist)
        except OSError:
            pass
        configure_completion()

    fullscreen = not a.no_fullscreen and not a.print_mode and sys.stdout.isatty() and sys.stdin.isatty()
    holder = {}
    mascot = E.Mascot(settings, on_change=lambda: holder["ui"].on_frame() if "ui" in holder else None)
    ui = UI(settings, mascot, fullscreen)
    holder["ui"] = ui
    ui.cfg = cfg
    app = App(cfg, settings, mascot, ui, project_config)
    app.plugin_event("session_start", project=str(Path.cwd()), model=cfg.model)
    app.yolo = a.yolo or a.dangerously_skip_permissions
    app.agent_mode = a.permission_mode
    if a.continue_session or a.resume:
        try:
            data = app.state.load_session(a.resume or "default")
            app.messages = data.get("messages", app.messages)
            if data.get("model"):
                app.cfg.model = data["model"]
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    ui.yolo = lambda: app.yolo
    animator = E.Animator(mascot, ui.on_frame, busy=lambda: ui.busy)

    first = None
    farewell = "See you soon!"
    try:
        if fullscreen:
            ui.screen = "welcome"
            ui.enter()
            animator.start()
            first = ui.welcome({"model": cfg.model, "server": re.sub(r"^https?://", "", cfg.base_url), "server_ok": server_ok})
            # The welcome screen may change cwd. Refresh the agent context
            # after that happens so the model does not keep the pre-selection
            # directory (for example /Users/abdul) in its system prompt.
            app.reload_project()
            app.messages[0] = {"role": "system", "content": system_prompt()}
            ui.screen = "main"
            ui.relayout()
        else:
            mascot.handle("APP_READY")
        app.award("first_project")
        if not server_ok:
            app.server_problem(f"Can't reach {cfg.base_url}.")
        ui.blank()
        ui.line(("  Corvi is ready in ", "muted"), (os.getcwd(), "text"), (". Ask for something, or type /help.", "muted"))
        pending = " ".join(a.prompt).strip() or first or ""

        active = None
        queued = []
        quit_requested = False

        def start_turn(text):
            thread = threading.Thread(target=app.turn_with_interrupt, args=(text,), daemon=True)
            thread.start()
            return thread

        while True:
            if active is not None and not active.is_alive():
                active.join(timeout=0)
                active = None
                if queued:
                    next_text = queued.pop(0)
                    ui.line((f"  starting queued request ({len(queued)} left)", "muted"))
                    active = start_turn(next_text)
            if quit_requested and active is None:
                break
            if pending:
                line, pending = pending, ""
            else:
                try:
                    line = ui.ask()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    ui.line(("  (ctrl-d or /exit to quit)", "muted"))
                    continue
            if not line:
                continue
            # A live tool approval owns the next line. Do not add it to the
            # conversation queue or treat it as a new user prompt.
            if active is not None and active.is_alive() and app.answer_permission(line):
                continue
            ui.blank()
            ui.user(line)
            app.log.append("> " + line)
            if active is not None and active.is_alive():
                if line.startswith("/"):
                    result = app.command(line)
                    if result == "exit":
                        quit_requested = True
                        ui.line(("  Corvi will exit after the current response.", "muted"))
                    elif isinstance(result, tuple):
                        queued.append(result[1])
                        ui.line((f"  queued side request ({len(queued)} waiting)", "muted"))
                else:
                    queued.append(line)
                    ui.line((f"  queued request ({len(queued)} waiting)", "muted"))
                continue
            if line.startswith("!"):
                app.shell(line[1:])
                continue
            if line.startswith("/"):
                r = app.command(line)
                if r == "exit":
                    break
                if isinstance(r, tuple):
                    active = start_turn(r[1])
                continue
            # Normal prompts always use one model for the fastest response.
            # Multi-model deliberation is opt-in through `/council PROMPT`.
            active = start_turn(line)
            if a.print_mode:
                quit_requested = True
    finally:
        if 'active' in locals() and active is not None and active.is_alive():
            active.join(timeout=2)
        try:
            app.state.save_session("default", app.messages, app.cfg.model)
        except (OSError, TypeError):
            pass
        app.plugin_event("session_end", project=str(Path.cwd()), model=app.cfg.model)
        animator.stop()
        farewell = mascot.handle("GOODBYE") or farewell
        ui.leave()
        if readline:
            try:
                readline.write_history_file(hist)
            except OSError:
                pass
    if fullscreen:
        ui.farewell(farewell)
    else:
        print(farewell)


if __name__ == "__main__":
    main()
