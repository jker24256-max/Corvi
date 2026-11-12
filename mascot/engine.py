"""
Corvi's brain. No drawing happens here and nothing here can touch command
execution: the app reports events in, and Corvi's state (expression, pose,
activity, message, progress) comes out.

  settings      - persistent user preferences            (~/.kit/settings.json)
  Dialogue      - what Corvi says, how often, never twice in a row
  Mascot        - state manager: event -> expression + pose + message
  frame_params  - pure function: state + time -> dx/dy/eyes/effects (animation)
  Animator      - lightweight timer thread (sleeps when nothing is moving)
  Achievements  - optional milestones
  helpers       - command classification and error explanations
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

CONFIG = Path(__file__).parent / "config"


def load_json(name):
    return json.loads((CONFIG / name).read_text())


EXPRESSIONS = load_json("expressions.json")
POSES = load_json("poses.json")
EVENTS = load_json("events.json")
PERSONALITY = load_json("personality.json")

# ════════════════════════════════════════════════════════════════════════════
#  SETTINGS  (persisted)
# ════════════════════════════════════════════════════════════════════════════
DEFAULTS = {
    "mascot_visible": True,
    "mascot_size": "medium",        # small | medium | large
    "animations": True,
    "reduced_motion": "auto",       # auto | on | off
    "dialogue": "normal",           # off | low | normal | chatty
    "sound": False,
    "theme": "dark",                # dark | light
    "reactions": True,              # expression reactions
    "pose_mode": "auto",            # auto | any pose name (locks the pose)
    "glyphs": "quad",               # quad | half
    "achievements": True,
    "recent_dirs": [],
    "achieved": {},
}
CHOICES = {
    "mascot_size": ["small", "medium", "large"],
    "reduced_motion": ["auto", "on", "off"],
    "dialogue": ["off", "low", "normal", "chatty"],
    "theme": ["dark", "light"],
    "pose_mode": ["auto"] + [p for p in POSES if p != "front"],
    "glyphs": ["quad", "half"],
}
BOOLS = ["mascot_visible", "animations", "sound", "reactions", "achievements"]
_TRUE, _FALSE = {"on", "true", "yes", "1"}, {"off", "false", "no", "0"}


class Settings:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path.home() / ".kit" / "settings.json"
        self.data = dict(DEFAULTS)
        try:
            saved = json.loads(self.path.read_text())
            for k, v in saved.items():
                if k in DEFAULTS:
                    self.data[k] = v
        except (OSError, ValueError):
            pass
        self._system_reduced = None

    def get(self, key):
        return self.data[key]

    def set(self, key, value):
        """Validate + persist. Returns (ok, message)."""
        if key not in DEFAULTS or key in ("recent_dirs", "achieved"):
            return False, f"Unknown setting '{key}'."
        v = str(value).strip().lower()
        if key in BOOLS:
            if v in _TRUE:
                self.data[key] = True
            elif v in _FALSE:
                self.data[key] = False
            else:
                return False, f"{key} must be on or off."
        else:
            if v not in CHOICES[key]:
                return False, f"{key} must be one of: {', '.join(CHOICES[key])}."
            self.data[key] = v
        self.save()
        return True, f"{key} = {self.data[key]}"

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2))
        except OSError:
            pass

    def add_recent(self, path):
        rec = [p for p in self.data["recent_dirs"] if p != path]
        self.data["recent_dirs"] = ([path] + rec)[:6]
        self.save()

    def reduced_motion(self):
        mode = self.data["reduced_motion"]
        if mode != "auto":
            return mode == "on"
        if os.environ.get("KIT_REDUCED_MOTION", "").lower() in _TRUE:
            return True
        if self._system_reduced is None:          # macOS accessibility preference
            self._system_reduced = False
            if sys.platform == "darwin":
                try:
                    out = subprocess.run(["defaults", "read", "com.apple.universalaccess", "reduceMotion"],
                                         capture_output=True, text=True, timeout=1).stdout.strip()
                    self._system_reduced = out == "1"
                except Exception:  # noqa: BLE001
                    pass
        return self._system_reduced

    def animating(self):
        return bool(self.data["animations"]) and not self.reduced_motion()


# ════════════════════════════════════════════════════════════════════════════
#  DIALOGUE
# ════════════════════════════════════════════════════════════════════════════
class _Safe(dict):
    def __missing__(self, key):
        return ""


class Dialogue:
    def __init__(self, settings, clock=time.monotonic, rng=random):
        self.s, self.clock, self.rng = settings, clock, rng
        self.recent = deque(maxlen=8)
        self.last_ts = -1e9

    def pick(self, event, ctx=None, priority="low"):
        level = self.s.get("dialogue")
        lines = PERSONALITY["lines"].get(event)
        if level == "off" or not lines:
            return None
        now = self.clock()
        if priority == "high":
            if now - self.last_ts < 1.0:
                return None
        else:
            if now - self.last_ts < PERSONALITY["cooldown"][level]:
                return None
            if self.rng.random() > PERSONALITY["frequency"][level]:
                return None
        fresh = [l for l in lines if l not in self.recent] or lines
        line = self.rng.choice(fresh)
        self.recent.append(line)
        self.last_ts = now
        text = line.format_map(_Safe(ctx or {}))
        return re.sub(r"\s+", " ", text).replace("Peeking at ...", "Peeking around...").strip()


# ════════════════════════════════════════════════════════════════════════════
#  ACHIEVEMENTS
# ════════════════════════════════════════════════════════════════════════════
ACHIEVEMENTS = {
    "first_project": ("First project", "Opened your first workspace with Corvi."),
    "first_build":   ("First successful build", "A build command finished cleanly."),
    "first_tests":   ("First passing test suite", "Tests ran and every one passed."),
    "first_commit":  ("First commit", "Committed work with git."),
    "first_deploy":  ("First deployment", "A deploy or publish command succeeded."),
    "debug_session": ("Debugging session", "A failing command was fixed and now passes."),
}


# ════════════════════════════════════════════════════════════════════════════
#  MASCOT STATE MANAGER
# ════════════════════════════════════════════════════════════════════════════
class Mascot:
    IDLE_AFTER, SLEEP_AFTER = 45.0, 180.0

    def __init__(self, settings, on_change=None, clock=time.monotonic, rng=random):
        self.s, self.clock, self.rng = settings, clock, rng
        self.on_change = on_change or (lambda: None)
        self.lock = threading.RLock()
        self.dialogue = Dialogue(settings, clock, rng)
        now = clock()
        self.expression, self.pose = "idle", "idle"
        self.activity, self.event = "Ready", None
        self.message, self.message_until = "", 0.0
        self.hold_until = 0.0
        self.pulse, self.pulse_t0 = None, 0.0
        self.last_activity = now
        self.state_since = now
        self.next_blink = now + rng.uniform(2.5, 5.5)
        self.blink_until = 0.0
        self.toast, self.toast_until = "", 0.0
        self.progress = {"active": False, "steps": 0, "t0": 0.0, "ok": 0, "failed": 0}
        self.history = deque(maxlen=50)        # (event, expression, pose) - used by tests/diagnostics

    # -- events in ------------------------------------------------------------------
    def handle(self, event, **ctx):
        spec = EVENTS.get(event)
        if not spec:
            return None
        now = self.clock()
        with self.lock:
            self.event = event
            if event not in ("APP_IDLE", "APP_SLEEP"):
                self.last_activity = now
            expr = spec["expression"] if self.s.get("reactions") else "idle"
            pose = spec["pose"] if self.s.get("reactions") else "idle"
            if self.s.get("pose_mode") != "auto":
                pose = self.s.get("pose_mode")
            self.expression, self.pose, self.state_since = expr, pose, now
            ctx.setdefault("target", "")
            ctx.setdefault("code", "?")
            self.activity = re.sub(r"\s+", " ", spec["activity"].format_map(_Safe(ctx))).strip()
            self.hold_until = now + spec["hold"] if spec.get("hold") else 0.0
            if spec.get("pulse") and self.s.animating():
                self.pulse, self.pulse_t0 = spec["pulse"], now
            msg = self.dialogue.pick(event, ctx, spec.get("priority", "low"))
            if msg:
                self.message, self.message_until = msg, now + 9 + len(msg) * 0.04
            # progress bookkeeping (real counters, fed by real events)
            p = self.progress
            if event == "USER_INPUT":
                p.update(active=True, steps=0, t0=now)
            elif event in ("FILE_READING", "FILE_WRITING", "COMMAND_STARTED", "TESTS_STARTED", "BUILD_STARTED"):
                p["steps"] += 1
            elif event in ("COMMAND_SUCCESS", "TESTS_PASSED", "BUILD_SUCCEEDED"):
                p["ok"] += 1
            elif event in ("COMMAND_FAILED", "TESTS_FAILED"):
                p["failed"] += 1
            elif event in ("TASK_COMPLETED", "REPLY_COMPLETED", "TURN_FAILED", "INTERRUPTED", "SERVER_ERROR", "USER_DECLINED"):
                p["active"] = False
            self.history.append((event, expr, pose))
        self.on_change()
        return msg

    def finish_turn(self):
        """Safety net: a turn is over, so the progress bar must stop whatever else happened."""
        with self.lock:
            self.progress["active"] = False
        self.on_change()

    def say(self, text, ttl=8.0):
        with self.lock:
            self.message, self.message_until = text, self.clock() + ttl
        self.on_change()

    def announce(self, text, ttl=7.0):
        with self.lock:
            self.toast, self.toast_until = text, self.clock() + ttl
        self.on_change()

    # -- time-driven changes -----------------------------------------------------------
    def tick(self):
        """Expire holds/messages, drift to sleepy, schedule blinks. Returns True if state changed."""
        now = self.clock()
        changed = False
        with self.lock:
            if self.message and now > self.message_until:
                self.message, changed = "", True
            if self.toast and now > self.toast_until:
                self.toast, changed = "", True
            if self.hold_until and now > self.hold_until:
                self.hold_until = 0.0
                self.expression, self.pose, self.activity, self.event = "idle", "idle", "Ready", None
                if self.s.get("pose_mode") != "auto":
                    self.pose = self.s.get("pose_mode")
                changed = True
            busy = self.progress["active"]
            quiet = now - self.last_activity
            if not busy and self.hold_until == 0.0:
                if quiet > self.SLEEP_AFTER and self.event != "APP_SLEEP":
                    changed = True
                elif quiet > self.IDLE_AFTER and self.event not in ("APP_IDLE", "APP_SLEEP"):
                    changed = True
            if now > self.next_blink:
                self.blink_until = now + 0.16
                self.next_blink = now + self.rng.uniform(2.5, 6.0)
        # idle transitions call handle() outside the lock to avoid re-entrancy churn
        if not self.progress["active"] and self.hold_until == 0.0:
            quiet = now - self.last_activity
            if quiet > self.SLEEP_AFTER and self.event != "APP_SLEEP":
                self.handle("APP_SLEEP")
            elif quiet > self.IDLE_AFTER and self.event not in ("APP_IDLE", "APP_SLEEP"):
                self.handle("APP_IDLE")
        return changed

    def snapshot(self):
        with self.lock:
            return {
                "expression": self.expression, "pose": self.pose, "activity": self.activity,
                "message": self.message, "toast": self.toast, "progress": dict(self.progress),
                "event": self.event, "pulse": self.pulse, "pulse_t0": self.pulse_t0,
                "blink": self.clock() < self.blink_until,
            }


# ════════════════════════════════════════════════════════════════════════════
#  ANIMATION  (pure: state + time -> frame parameters)
# ════════════════════════════════════════════════════════════════════════════
PULSE_LEN = {"hop": 1.1, "hop_small": 0.6, "shake": 0.9}
POSE_FLUTTER = {"greeting": ("greeting", "idle"), "celebrating": ("celebrating", "greeting")}


def _motion_offsets(motion, now, t_state):
    if motion == "breathe":
        return 0, (1 if math.sin(now * 2 * math.pi / 2.8) > 0.25 else 0)
    if motion == "slow_breathe":
        return 0, (1 if math.sin(now * 2 * math.pi / 4.5) > 0.1 else 0)
    if motion == "bob":
        return 0, (-1 if math.sin(now * 2 * math.pi / 1.4) > 0 else 0)
    if motion == "typing":
        return 0, (1 if int(now * 4) % 2 else 0)
    if motion == "sway":
        return (int(round(math.sin(now * 2 * math.pi / 3.2))), 0)
    if motion == "page":
        return 0, (1 if int(now * 1.5) % 2 else 0)
    if motion == "hop":
        return 0, -int(round(3 * abs(math.sin(now * 2 * math.pi / 0.9))))
    if motion == "hop_small":
        return 0, -int(round(2 * abs(math.sin(now * 2 * math.pi / 0.8))))
    if motion == "shake" or motion == "shake_small":
        amp = 2 if motion == "shake" else 1
        return (amp if int(now * 8) % 2 else -amp), 0
    return 0, 0


def frame_params(snap, now, animating):
    """What to draw right now. Pure and deterministic given (snap, now)."""
    expr = EXPRESSIONS[snap["expression"]]
    pose = snap["pose"]
    eyes = expr["eyes"]
    dx = dy = 0
    if animating:
        flutter = POSE_FLUTTER.get(pose)
        if flutter and snap["event"] in ("APP_READY", "GOODBYE", "TASK_COMPLETED", "TESTS_PASSED", "BUILD_SUCCEEDED", "ACHIEVEMENT"):
            pose = flutter[int(now / 0.4) % 2]
        motion = POSES.get(snap["pose"], {}).get("motion", "breathe")
        if expr["motion"] not in ("breathe", "slow_breathe") or motion in ("breathe", "slow_breathe"):
            motion = expr["motion"]
        pulse = snap.get("pulse")
        if pulse and now - snap["pulse_t0"] < PULSE_LEN.get(pulse, 0.8):
            motion = pulse
            t = now - snap["pulse_t0"]
            if pulse == "hop":
                dy = -int(round(5 * abs(math.sin(math.pi * t / 0.55))))
            elif pulse == "hop_small":
                dy = -int(round(3 * abs(math.sin(math.pi * t / 0.6))))
            else:
                dx = (2 if int(t * 12) % 2 else -2)
        else:
            dx, dy = _motion_offsets(motion, now, 0)
        if snap["blink"] and eyes == "open":
            eyes = "closed"
    return {"pose": pose, "eyes": eyes, "dx": dx, "dy": dy}


EFFECTS = {
    "sparkle":  [("✦", "gold", 0, 0), ("✧", "gold", 2, 3), ("·", "gold", 1, -3)],
    "confetti": [("✦", "gold", 0, 0), ("✶", "electric", 1, 4), ("✧", "ok", 3, -2), ("•", "err", 2, 6), ("✦", "info", 0, -5)],
    "star":     [("★", "gold", 0, 0)],
    "question": [("?", "info", 0, 0)],
    "bang":     [("!", "gold", 0, 0)],
    "bang_red": [("!", "err", 0, 0)],
    "dots":     [("…", "muted", 0, 0)],
}


def effect_items(effect, now, cols, rows, animating):
    """[(row, col, text, colour-key)] relative to the stage. Corvi's head sits in the upper middle."""
    if effect in (None, "none"):
        return []
    r0, c0 = 1, cols - 8
    if effect == "thought":
        n = 1 + int(now * 1.6) % 3 if animating else 3
        return [(r0 + 3 - i, c0 + i * 2, "o" if i < 2 else "O", "muted") for i in range(n)]
    if effect == "zzz":
        n = 1 + int(now * 0.9) % 3 if animating else 2
        return [(r0 + 2 - i, c0 + i * 2, "z" if i < 2 else "Z", "info") for i in range(n)]
    out = []
    spin = int(now * 2.5) % 3 if animating else 0
    for i, (ch, col, dr, dc) in enumerate(EFFECTS.get(effect, [])):
        if animating and (i + spin) % 3 == 2:
            ch = "·"
        out.append((r0 + dr, c0 + dc, ch, col))
    return out


class Animator:
    """One timer thread. Wakes quickly only while something moves; otherwise sleeps long."""

    def __init__(self, mascot, redraw, busy=lambda: False):
        self.m, self.redraw, self.busy = mascot, redraw, busy
        self.cond = threading.Condition()
        self.stop_flag = False
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="corvi-animator")
        self.thread.start()

    def stop(self):
        with self.cond:
            self.stop_flag = True
            self.cond.notify_all()
        if self.thread:
            self.thread.join(timeout=1)

    def poke(self):
        with self.cond:
            self.cond.notify_all()

    def interval(self):
        snap = self.m.snapshot()
        if self.m.s.animating():
            return 0.5 if snap["pose"] == "sleeping" else 0.125
        return 1.0 if self.busy() else 4.0      # reduced motion: only spinner/timers, no movement

    def _run(self):
        while True:
            with self.cond:
                if self.stop_flag:
                    return
                self.cond.wait(self.interval())
                if self.stop_flag:
                    return
            try:
                self.m.tick()
                self.redraw()
            except Exception:  # noqa: BLE001  - never let the mascot crash the app
                pass


# ════════════════════════════════════════════════════════════════════════════
#  ACHIEVEMENT TRACKER
# ════════════════════════════════════════════════════════════════════════════
class Achievements:
    def __init__(self, settings):
        self.s = settings

    def unlock(self, key):
        if not self.s.get("achievements") or key not in ACHIEVEMENTS:
            return None
        got = self.s.get("achieved")
        if key in got:
            return None
        got[key] = time.strftime("%Y-%m-%d")
        self.s.save()
        return ACHIEVEMENTS[key][0]

    def summary(self):
        got = self.s.get("achieved")
        return [(k, v[0], v[1], got.get(k)) for k, v in ACHIEVEMENTS.items()]


# ════════════════════════════════════════════════════════════════════════════
#  COMMAND CLASSIFICATION + ERROR EXPLANATIONS  (heuristics; clearly labelled as such)
# ════════════════════════════════════════════════════════════════════════════
_KINDS = [
    ("commit", r"\bgit\s+commit\b"),
    ("deploy", r"\b(vercel|netlify|flyctl|fly|wrangler|firebase)\s+(deploy|publish)\b|\bnpm\s+publish\b|\bdocker\s+push\b|\bkubectl\s+apply\b|\bgit\s+push\s+\S*\s*heroku\b|\bgh\s+release\b"),
    ("tests", r"\b(pytest|py\.test|jest|vitest|mocha|rspec|phpunit|ctest)\b|\bpython3?\s+-m\s+(pytest|unittest)\b|\b(npm|yarn|pnpm|bun)\s+(run\s+)?test\b|\b(cargo|go|swift|make|gradle|gradlew|mvn)\s+test\b|xcodebuild\b.*\btest\b"),
    ("build", r"\b(npm|yarn|pnpm|bun)\s+run\s+build\b|\b(yarn|pnpm|bun)\s+build\b|\b(cargo|go|swift)\s+build\b|\bmake(\s+(all|build))?\s*$|\bmake\s+(all|build)\b|\btsc\b|\bxcodebuild\b|\bgradlew?\s+build\b|\bmvn\s+(package|install|compile)\b|\bcmake\s+--build\b|\bpython3?\s+-m\s+build\b"),
]


def classify_command(cmd):
    c = cmd.strip()
    for kind, rx in _KINDS:
        if re.search(rx, c):
            return kind
    return "other"


_ERRORS = [
    (r"command not found|not recognized as an internal", "Command not found",
     "The program isn't installed, or isn't on your PATH.",
     ["Check the spelling", "Install it (e.g. `brew install <name>`)", "Run `which <name>` to see if it's on PATH"]),
    (r"No such file or directory|ENOENT|FileNotFoundError", "File or folder not found",
     "A path in the command doesn't exist from the current directory.",
     ["Run `pwd` and `ls` to confirm where you are", "Check the path spelling", "Use /cd to move to the project folder"]),
    (r"Permission denied|EACCES|PermissionError", "Permission denied",
     "Your user isn't allowed to do that to that file or port.",
     ["Check ownership with `ls -l`", "`chmod +x <file>` if it's a script you need to run", "Avoid sudo unless you know why it's needed"]),
    (r"ModuleNotFoundError|ImportError|No module named", "Missing Python module",
     "Python can't find a package the code imports.",
     ["Install it: `python3 -m pip install <package>`", "Make sure the right virtualenv is active"]),
    (r"Cannot find module|MODULE_NOT_FOUND|npm ERR! missing", "Missing Node module",
     "Node can't find a dependency.",
     ["Run `npm install` in the project folder", "Check the import path for typos"]),
    (r"SyntaxError|IndentationError|syntax error", "Syntax error",
     "The code isn't valid syntax near the line shown.",
     ["Look at the line above the caret", "Check brackets, quotes and indentation", "Ask me to /fix it and I'll propose an edit"]),
    (r"address already in use|EADDRINUSE", "Port already in use",
     "Another process is already listening on that port.",
     ["Find it: `lsof -i :<port>`", "Stop it, or choose a different port"]),
    (r"AssertionError|FAILED|\d+ failed|Tests? failed", "Test failure",
     "At least one test expected something different from what it got.",
     ["Read the first failing assertion", "Ask me to /fix it, then re-run the tests"]),
    (r"Traceback \(most recent call last\)", "Python exception",
     "The program crashed. The last line of the traceback names the cause.",
     ["Read the last line first", "Ask me to /fix it"]),
    (r"fatal: not a git repository", "Not a git repository",
     "Git commands need to run inside a repo.",
     ["`git init` to start one", "Use /cd to enter the right folder"]),
]


def explain_error(command, output):
    for rx, title, why, fixes in _ERRORS:
        if re.search(rx, output or "", re.I):
            return {"title": title, "why": why, "fixes": fixes}
    return None


def first_error_line(output):
    lines = [l.strip() for l in (output or "").splitlines() if l.strip()]
    for l in reversed(lines):
        if re.search(r"error|fail|exception|not found|denied|fatal", l, re.I):
            return l[:140]
    return lines[-1][:140] if lines else ""
