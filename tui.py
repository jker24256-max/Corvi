"""
Full-screen terminal UI for Kit + Corvi.

Layout (side mode):                      Layout (strip mode, narrow terminals):
  row 1        header                      row 1        header
  rows 2..R-5  transcript | Corvi panel    rows 2..9    Corvi strip
  row  R-4     live line                   rows 10..    transcript
  row  R-3     input rule                  ...
  row  R-2     input
  row  R-1     input rule
  row  R       status bar

The transcript is painted by us (own wrapping), so Corvi can sit beside it and
animate without ever touching command output. All drawing goes through one
locked writer and is wrapped in save/restore-cursor so typing is never disturbed.
"""
from __future__ import annotations

import atexit
import os
import random
import re
import select
import shutil
import signal
import subprocess
import sys
import textwrap
import termios
import threading
import time
import tty
from pathlib import Path

from mascot import engine as E
from mascot import render as R

try:
    import readline
except ImportError:  # pragma: no cover
    readline = None

# ════════════════════════════════════════════════════════════════════════════
#  DESIGN TOKENS  (one place for every colour)
# ════════════════════════════════════════════════════════════════════════════
BRAND = {
    "raven": (0x1E, 0x27, 0x42), "slate": (0x2F, 0x3E, 0x63), "electric": (0x4D, 0x7C, 0xFF),
    "cream": (0xF5, 0xE6, 0xC8), "gold": (0xFF, 0xD1, 0x66),
    "ok": (0x70, 0xC9, 0x94), "err": (0xF0, 0x78, 0x78), "warn": (0xE9, 0xB8, 0x5C),
    # Keep secondary text bright enough for small or low-contrast terminals.
    # The previous muted colour was too close to the dark background, which
    # made council status and response text difficult to read.
    "info": (0x8D, 0xC4, 0xFF), "muted": (0xC0, 0xC8, 0xD8),
}
THEMES = {
    "dark": {
        "bg": BRAND["raven"], "panel": (36, 47, 79), "text": (0xFF, 0xF4, 0xDC), "muted": BRAND["muted"],
        "gold": BRAND["gold"], "electric": BRAND["electric"], "ok": BRAND["ok"], "err": BRAND["err"],
        "warn": BRAND["warn"], "info": BRAND["info"], "user_bg": BRAND["slate"], "rule": (70, 86, 134),
        "header_bg": (22, 30, 54), "header_fg": BRAND["cream"], "on_gold": BRAND["raven"],
        "stage": {"sky_top": (243, 232, 205), "sky_bot": (229, 214, 184), "floor": (203, 186, 152), "shadow": (96, 84, 80)},
    },
    "light": {
        "bg": (250, 244, 232), "panel": (236, 228, 208), "text": BRAND["raven"], "muted": (104, 112, 136),
        "gold": (166, 112, 12), "electric": (52, 92, 214), "ok": (36, 140, 84), "err": (200, 64, 64),
        "warn": (178, 120, 20), "info": (44, 112, 200), "user_bg": (226, 218, 198), "rule": (196, 184, 156),
        "header_bg": (238, 228, 206), "header_fg": BRAND["raven"], "on_gold": BRAND["raven"],
        "stage": {"sky_top": (226, 235, 250), "sky_bot": (206, 220, 244), "floor": (176, 192, 224), "shadow": (70, 80, 120)},
    },
}
T = dict(THEMES["dark"])
COMMANDS = [
    "/help", "/btw", "/ask", "/plan", "/review", "/research", "/model", "/clear", "/fix", "/yolo",
    "/status", "/pwd", "/ls", "/run", "/web", "/github", "/cd", "/workspace", "/settings", "/set",
    "/corvi", "/size", "/theme", "/pose", "/mood", "/achievements", "/log", "/history", "/scroll", "/exit",
]


def set_theme(name):
    T.clear()
    T.update(THEMES.get(name, THEMES["dark"]))


def col(key):
    v = T.get(key) or BRAND.get(key) or T["text"]
    return v


def fg(c):
    return R.sgr_fg(c if isinstance(c, tuple) else col(c))


def bg(c):
    return R.sgr_bg(c if isinstance(c, tuple) else col(c))


def base():
    return "\x1b[0m" + fg("text") + bg("bg")


def sty(style):
    """Style key -> SGR (colours only; callers re-apply base() afterwards)."""
    if style == "text" or style is None:
        return ""
    if style == "bold":
        return "\x1b[1m"
    if style == "accent":
        return fg("gold") + "\x1b[1m"
    if style == "user":
        return fg("text") + bg("user_bg")
    if style == "usergold":
        return fg("gold") + bg("user_bg") + "\x1b[1m"
    if style == "code":
        return fg("info") + bg("panel")
    if style == "panel":
        return fg("text") + bg("panel")
    return fg(style)


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def vlen(s):
    return len(ANSI_RE.sub("", s))


def rl(s):
    return ANSI_RE.sub(lambda m: "\001" + m.group(0) + "\002", s)


def short_path(p):
    home = str(Path.home())
    return "~" + p[len(home):] if p.startswith(home) else p


def clip_left(s, n):
    return s if len(s) <= n else "…" + s[-(max(n, 2) - 1):]


def wrap_segs(segs, width, indent):
    """Greedy word-wrap of styled segments, keeping each word's style; continuation lines are indented."""
    lines, used = [[]], 0
    for text, style in segs:
        for part in re.findall(r"\S+\s*|\s+", text):
            n = len(part.rstrip())
            if used + n > width and used > indent:
                lines.append([(" " * indent, "text")])
                used = indent
                part = part.lstrip()
            lines[-1].append((part, style))
            used += len(part)
    return lines


def wrap(text, width):
    out = []
    for para in text.split("\n"):
        if not para.strip():
            out.append("")
        else:
            out += textwrap.wrap(para, max(width, 8), replace_whitespace=False, drop_whitespace=True,
                                 break_long_words=True, break_on_hyphens=False) or [""]
    return out


SPIN = "✻✽✶✳✢·"
VERBS = ["Sniffing", "Pouncing", "Digging", "Foraging", "Scampering", "Tracking", "Burrowing", "Prowling"]
SIZES = {"small": 9, "medium": 13, "large": 17}

WORDMARK = {
    "C": [" ████", "█    ", "█    ", "█    ", " ████"],
    "O": [" ███ ", "█   █", "█   █", "█   █", " ███ "],
    "R": ["████ ", "█   █", "████ ", "█  █ ", "█   █"],
    "V": ["█   █", "█   █", "█   █", " █ █ ", "  █  "],
    "I": ["█████", "  █  ", "  █  ", "  █  ", "█████"],
}


# ════════════════════════════════════════════════════════════════════════════
#  UI
# ════════════════════════════════════════════════════════════════════════════
class UI:
    def __init__(self, settings, mascot, enabled):
        self.s, self.m, self.enabled = settings, mascot, enabled
        self.lock = threading.RLock()
        self._wlock = threading.Lock()
        self.entries = []
        self.rows, self.cols = 30, 100
        self.L = {"mode": "none"}
        self.screen = "main"                  # main | welcome
        self.busy = False
        self.busy_t0 = 0.0
        self.verb = VERBS[0]
        self.in_input = False
        self.cfg = None
        self.yolo = lambda: False
        self.dirty = False
        self.scroll_offset = 0
        self._last_paint = 0.0
        self._last_full_paint = 0.0
        self._active = False
        self.welcome_ctx = None
        set_theme(settings.get("theme"))

    # -- low-level output ---------------------------------------------------------------
    def _emit(self, s):
        data = s.encode("utf-8", "replace")
        with self._wlock:
            while data:
                try:
                    n = os.write(1, data)
                    data = data[n:]
                except InterruptedError:
                    continue
                except BlockingIOError:
                    time.sleep(0.001)

    def _overlay(self, s):
        """Draw without disturbing the cursor (so typing is never interrupted)."""
        self._emit("\x1b7" + s + "\x1b8")

    # -- lifecycle ---------------------------------------------------------------------
    def enter(self):
        if not self.enabled:
            return
        self._active = True
        self._emit("\x1b[?1049h\x1b[?25l")
        self.relayout()
        atexit.register(self.leave)
        try:
            signal.signal(signal.SIGWINCH, lambda *_: self.relayout())
        except (ValueError, AttributeError):
            pass
        self._emit("\x1b]0;Corvi — Kit\x07")

    def leave(self):
        if self.enabled and self._active:
            self._active = False
            self._emit("\x1b[0m\x1b[?25h\x1b[?1049l")

    def suspend(self):
        if self.enabled and self._active:
            self._active = False
            self._emit("\x1b[0m\x1b[?25h\x1b[?1049l")

    def resume(self):
        if self.enabled and not self._active:
            self._active = True
            self._emit("\x1b[?1049h\x1b[?25l")
            self.relayout()

    # -- geometry --------------------------------------------------------------------------
    def measure(self):
        sz = shutil.get_terminal_size((100, 30))
        self.cols, self.rows = max(sz.columns, 40), max(sz.lines, 12)
        top, bot = 2, self.rows - 5
        avail = bot - top + 1
        L = {"mode": "none", "tr": top, "tc": 1, "th": avail, "tw": self.cols}
        if self.s.get("mascot_visible"):
            want = SIZES[self.s.get("mascot_size")]
            sprite = min(want, avail - 13)
            while sprite >= 6:
                stage_cols = max(R.sprite_cols(sprite) + 6, 26)
                if self.cols - (stage_cols + 2) - 1 >= 46:
                    L.update(mode="side", sprite=sprite, scols=stage_cols, srows=sprite + 3,
                             pr=top, pc=self.cols - stage_cols - 1, ph=avail, pw=stage_cols + 2,
                             tw=self.cols - stage_cols - 4)
                    break
                sprite -= 1
            if L["mode"] == "none" and avail >= 16:
                L.update(mode="strip", sprite=5, scols=R.sprite_cols(5) + 6, srows=8, pr=top, pc=1, ph=8, pw=self.cols,
                         tr=top + 8, th=avail - 8)
        self.L = L

    def relayout(self):
        with self.lock:
            self.measure()
            if not self.enabled:
                return
            self._emit(base() + "\x1b[2J")
            self.paint_all()
            if self.in_input:
                buf = readline.get_line_buffer() if readline else ""
                self._emit(f"\x1b[{self.rows - 2};1H{self._prompt_plain()}{buf}")

    # -- transcript model ----------------------------------------------------------------
    def _add(self, entry):
        with self.lock:
            self.entries.append(entry)
            if len(self.entries) > 4000:
                del self.entries[:500]
            self.scroll_offset = 0
        self.touch(force=True)

    def line(self, *segs):
        segs = [(s, "text") if isinstance(s, str) else s for s in segs]
        segs = [(re.sub(r"[\x00-\x08\x0b-\x1f]", "", t.replace("\t", "  ")), st) for t, st in segs]
        if not self.enabled:
            print("".join(t for t, _ in segs))
            return
        self._add({"k": "line", "segs": segs})

    def blank(self):
        if not self.enabled:
            print()
            return
        self._add({"k": "blank"})

    def user(self, text):
        if not self.enabled:
            print(f"> {text}")
            return
        self._add({"k": "user", "text": text})

    def md_new(self):
        e = {"k": "md", "text": ""}
        if self.enabled:
            with self.lock:
                self.entries.append(e)
        else:
            sys.stdout.write("\n● ")
        return e

    def md_add(self, e, text):
        if not self.enabled:
            sys.stdout.write(text)
            sys.stdout.flush()
            return
        e["text"] += text
        e.pop("cache", None)
        self.touch()

    def md_end(self, e):
        if not self.enabled:
            print()
        else:
            self.touch(force=True)

    def clear(self):
        with self.lock:
            self.entries.clear()
        if self.enabled:
            self.touch(force=True)

    def _phys(self, e, w):
        key = w
        c = e.get("cache")
        if c and c[0] == key and e["k"] != "md":
            return c[1]
        out = []
        k = e["k"]
        if k == "line":
            total = sum(len(t) for t, _ in e["segs"])
            if total > w:
                lead = len(e["segs"][0][0]) - len(e["segs"][0][0].lstrip())
                lead += 2 if e["segs"][0][0].strip() in ("◆", "✗", "⎿", "●", "★") else 0
                for ln in wrap_segs(e["segs"], w, min(lead + 2, 12)):
                    out.append((ln, None))
            else:
                out.append((e["segs"], None))
        elif k == "blank":
            out.append(([], None))
        elif k == "user":
            first = True
            for ln in wrap(e["text"], w - 4):
                out.append(([(" ❯ " if first else "   ", "usergold"), (ln, "user")], "user_bg"))
                first = False
        elif k == "md":
            fence, first = False, True
            for raw in e["text"].split("\n"):
                if raw.strip().startswith("```"):
                    fence = not fence
                    continue
                parts = [raw[:w - 4]] if fence else (wrap(raw, w - 2) if raw.strip() else [""])
                for p in parts:
                    lead = ("● ", "accent") if first else ("  ", "text")
                    first = False
                    out.append(([lead, ("  " + p, "code") if fence else (p, "text")] if fence else [lead, (p, "text")], None))
        e["cache"] = (key, out)
        return out

    def _render_line(self, segs, width, line_bg=None):
        b = base() if not line_bg else "\x1b[0m" + fg("text") + bg(line_bg)
        out, used = [], 0
        for text, style in segs:
            room = width - used
            if room <= 0:
                break
            t = text[:room]
            out.append(sty(style) + t + b)
            used += len(t)
        out.append(" " * (width - used))
        return b + "".join(out) + base()

    def paint_transcript(self):
        if not self.enabled or self.screen != "main":
            return
        L = self.L
        w, h = L["tw"], L["th"]
        with self.lock:
            phys = []
            for e in self.entries:
                phys += self._phys(e, w)
            # A terminal tab switch, resize, or pager return can leave an
            # old scroll offset larger than the current transcript. Clamp it
            # so the main view never redraws as an apparently empty screen.
            self.scroll_offset = min(self.scroll_offset, max(0, len(phys) - h))
        end = max(0, len(phys) - self.scroll_offset)
        phys = phys[max(0, end - h):end]
        pad = h - len(phys)
        rows = []
        for i in range(h):
            if i < pad:
                rows.append(self._render_line([], w))
            else:
                segs, lb = phys[i - pad]
                rows.append(self._render_line(segs, w, lb))
        self._overlay("".join(f"\x1b[{L['tr'] + i};{L['tc']}H{ln}" for i, ln in enumerate(rows)))
        self.dirty = False
        self._last_paint = time.monotonic()

    def scroll_transcript(self, delta):
        with self.lock:
            self.scroll_offset = max(0, self.scroll_offset + int(delta))
        self.paint_transcript()

    def touch(self, force=False):
        if not self.enabled:
            return
        if force or time.monotonic() - self._last_paint > 0.04:
            self.paint_transcript()
        else:
            self.dirty = True

    # -- chrome ------------------------------------------------------------------------------
    def _pad(self, s, width, b=None):
        b = b or base()
        return s + b + " " * max(0, width - vlen(s))

    def paint_header(self):
        c = self.cols
        hb = bg("header_bg")
        model = (self.cfg.model if self.cfg and self.cfg.model else "no model")
        left = (f"\x1b[0m{bg('gold')}{fg('on_gold')}\x1b[1m {self.m.s.get('theme') and 'CORVI'} \x1b[0m{hb}{fg('header_fg')}  "
                f"{model}  {fg('muted')}{clip_left(short_path(os.getcwd()), max(10, c - len(model) - 40))}")
        right = f"{fg('gold')}auto-approve ON " if self.yolo() else f"{fg('muted')}Your Friendly Coding Companion. "
        gap = max(1, c - vlen(left) - vlen(right) - 1)
        line = left + hb + " " * gap + right
        return f"\x1b[1;1H{hb}{line}{hb}" + " " * max(0, c - vlen(line)) + base()

    def paint_status(self):
        c = self.cols
        snap = self.m.snapshot()
        if self.yolo():
            left = f"{fg('gold')}▸▸ auto-approve on{fg('muted')} · /yolo to turn off"
        else:
            left = f"{fg('muted')}▸ asks before edits & commands · /yolo to auto-approve"
        if self.L["mode"] == "none" and snap["message"]:
            left = f"{fg('gold')}Corvi:{fg('text')} {snap['message']}"
        right = f"{fg('muted')}/help · /history full log · ctrl-c stop · ctrl-d exit "
        if vlen(left) + vlen(right) + 3 > c:
            right = ""
        gap = max(1, c - vlen(left) - vlen(right) - 1)
        return f"\x1b[{self.rows};1H{base()} {left}{base()}{' ' * gap}{right}{base()}"

    def paint_rules(self):
        r = fg("rule") + "─" * self.cols
        return f"\x1b[{self.rows - 3};1H{base()}{r}{base()}\x1b[{self.rows - 1};1H{base()}{r}{base()}"

    def paint_live(self):
        row = self.rows - 4
        if self.busy:
            secs = int(time.monotonic() - self.busy_t0)
            f = SPIN[int(time.monotonic() * 8) % len(SPIN)] if self.s.animating() else "✻"
            s = f"{fg('gold')} {f} {self.verb}…{fg('muted')} ({secs}s · ctrl-c to interrupt)"
        elif self.scroll_offset:
            s = f"{fg('muted')}↑ transcript history · PageUp/PageDown · /history for the full session"
        else:
            s = ""
        return f"\x1b[{row};1H{base()}{self._pad(s, self.cols)}"

    def paint_all(self):
        if self.screen == "welcome":
            self._emit(base() + "\x1b[2J")
            self.paint_welcome()
            self._last_full_paint = time.monotonic()
            return
        self._overlay(self.paint_header() + self.paint_rules() + self.paint_status() + self.paint_live()
                      + f"\x1b[{self.rows - 2};1H{base()}{' ' * self.cols}")
        self.paint_transcript()
        self.paint_panel()
        self._last_full_paint = time.monotonic()

    # -- Corvi companion panel ----------------------------------------------------------------
    def _stage_lines(self, scols, srows, sprite, pose_override=None):
        now = time.monotonic()
        snap = self.m.snapshot()
        anim = self.s.animating()
        fp = E.frame_params(snap, now, anim)
        pose = pose_override or fp["pose"]
        expr = E.EXPRESSIONS[snap["expression"]]
        eyes = fp["eyes"] if R.has_eyes(pose) else "open"
        cells = R.render_stage(pose, scols, srows, sprite, eyes, fp["dx"], fp["dy"], stage=T["stage"],
                               quad=self.s.get("glyphs") == "quad")
        items = [(r, c, t, col(k)) for r, c, t, k in E.effect_items(expr["effect"], now, scols, srows, anim)]
        if anim:
            ambient = ("✦", "·", "✧", "·", "✦", "·")
            for i, glyph in enumerate(ambient):
                ar = (i * 3 + int(now * (1 + i % 2))) % max(1, srows)
                ac = (i * 7 + int(now * 2)) % max(1, scols)
                items.append((ar, ac, glyph, col("electric" if i % 2 else "gold")))
        return R.cells_to_ansi(R.overlay(cells, items), reset=base()), snap, now

    def _bar(self, snap, now, width):
        p = snap["progress"]
        if p["active"]:
            n = width - 2
            pos = int(now * 6) % (n * 2 - 2) if self.s.animating() else 0
            pos = pos if pos < n else (n * 2 - 2 - pos)
            cells = "".join("▰" if abs(i - pos) <= 1 else "▱" for i in range(n))
            return f"{fg('gold')}{cells}"
        return f"{fg('muted')}{'▱' * (width - 2)}"

    def paint_panel(self):
        if not self.enabled or self.screen != "main" or self.L["mode"] == "none":
            return
        with self.lock:
            L = self.L
            stage, snap, now = self._stage_lines(L["scols"], L["srows"], L["sprite"])
            expr = E.EXPRESSIONS[snap["expression"]]
            pose_label = E.POSES.get(snap["pose"], {}).get("label", snap["pose"])
            p = snap["progress"]
            ach = self.m.s.get("achieved")
            if L["mode"] == "side":
                out = self._panel_side(L, stage, snap, now, expr, pose_label, p, ach)
            else:
                out = self._panel_strip(L, stage, snap, now, expr, pose_label, p, ach)
            self._overlay(out)

    def _panel_side(self, L, stage, snap, now, expr, pose_label, p, ach):
        iw, h, r0, c0 = L["scols"], L["ph"], L["pr"], L["pc"]
        bd, pb = fg("rule"), bg("panel")
        title = f" Corvi · {pose_label} "
        dot_col = "err" if snap["expression"] in ("error", "confused", "sad") else ("gold" if p["active"] else "ok")
        top = f"{base()}{bd}╭─{fg('gold')}\x1b[1m{title}\x1b[0m{base()}{bd}" + "─" * max(0, iw - len(title) - 2) + f"{fg(dot_col)}●{bd}╮"
        rows = [top]
        for ln in stage:
            rows.append(f"{base()}{bd}│{ln}{base()}{bd}│")
        msg = snap["toast"] or snap["message"]
        mstyle = "gold" if snap["toast"] else "text"
        lines = wrap(("★ " + msg) if snap["toast"] else (f"“{msg}”" if msg else ""), iw - 4)[:4] or [""]
        bub_rows = 4
        for i in range(bub_rows):
            t = lines[i] if i < len(lines) else ""
            rows.append(f"{base()}{bd}│{bg('panel')}{fg(mstyle) if msg else fg('muted')} {t:<{iw - 2}} {base()}{bd}│")
        elapsed = int(now - p["t0"]) if p["active"] else 0
        info = [
            f"{fg('gold')}◆ {snap['activity'][:iw - 4]}",
            f"{fg('muted')}mood {expr['label']}",
            f"{self._bar(snap, now, iw - 2)}" if p["active"] else f"{fg('muted')}✓ {p['ok']}  ✗ {p['failed']}  ·  ★ {len(ach)}/{len(E.ACHIEVEMENTS)}",
            f"{fg('muted')}step {p['steps']} · {elapsed}s" if p["active"] else f"{fg('muted')}session summary",
        ]
        for t in info:
            rows.append(f"{base()}{bd}│{bg('panel')} {t}{bg('panel')}{' ' * max(0, iw - 1 - vlen(t))}{base()}{bd}│")
        while len(rows) < h - 1:
            rows.append(f"{base()}{bd}│{bg('panel')}{' ' * iw}{base()}{bd}│")
        rows.append(f"{base()}{bd}╰" + "─" * iw + "╯" + base())
        return "".join(f"\x1b[{r0 + i};{c0}H{ln}" for i, ln in enumerate(rows[:h]))

    def _panel_strip(self, L, stage, snap, now, expr, pose_label, p, ach):
        r0, c0, sc = L["pr"], L["pc"], L["scols"]
        tw = self.cols - sc - 2
        msg = snap["toast"] or snap["message"]
        txt = [f"{fg('gold')}\x1b[1mCorvi{base()}{fg('muted')} · {pose_label} · {expr['label']}",
               f"{fg('gold')}◆ {snap['activity']}",
               ""]
        txt += [f"{fg('text')}{t}" for t in wrap(f"“{msg}”" if msg else "", tw)[:3]]
        txt += ["", (self._bar(snap, now, min(tw, 24)) if p["active"] else f"{fg('muted')}✓ {p['ok']}  ✗ {p['failed']}  ★ {len(ach)}/{len(E.ACHIEVEMENTS)}")]
        out = []
        for i, ln in enumerate(stage):
            t = txt[i] if i < len(txt) else ""
            out.append(f"\x1b[{r0 + i};{c0}H{ln}{base()}  {t}{base()}{' ' * max(0, tw - vlen(t))}")
        return "".join(out)

    # -- animation callback --------------------------------------------------------------------
    def on_frame(self):
        if not self.enabled or not self._active:
            return
        if self.screen == "welcome":
            self.paint_hero()
            return
        # Terminal windows can lose a repaint while Corvi is idle in the raw
        # input reader. Periodically restore the complete layout, but never do
        # this while the user is editing a line.
        if not self.in_input and time.monotonic() - self._last_full_paint >= 5.0:
            self.paint_all()
            return
        if self.dirty:
            self.paint_transcript()
        self.paint_panel()
        self._overlay(self.paint_live() + self.paint_status())

    # -- turn spinner -----------------------------------------------------------------------------
    def begin_turn(self):
        self.busy, self.busy_t0, self.verb = True, time.monotonic(), random.choice(VERBS)

    def end_turn(self):
        self.busy = False
        if self.enabled:
            self._overlay(self.paint_live())

    # -- input ----------------------------------------------------------------------------------------
    def _prompt_plain(self):
        return f"{base()} {fg('gold')}\x1b[1m❯{base()} "

    def ask(self, label=None):
        """Read one line in the input box. label: optional prompt text (e.g. approval question)."""
        if not self.enabled:
            return input(f"{label or '>'} ").strip()
        if label is None:
            return self._ask_command_line()
        prompt = f" {fg('gold')}\x1b[1m❯{base()} " if not label else f" {fg('gold')}{label}{base()} ❯ "
        self.in_input = True
        palette_rows = []
        if not label:
            palette_rows = [
                f"{fg('muted')}Commands  {fg('gold')}/help  /btw  /plan  /review  /research  /web  /github  /workspace",
                f"{fg('muted')}          /status  /ls  /run  /fix  /history  /settings  /exit   {fg('text')}(/ + Tab for all)",
            ]
            self._emit(
                f"\x1b[{self.rows - 5};1H{base()}{' ' * self.cols}"
                f"\x1b[{self.rows - 4};1H{base()}{' ' * self.cols}"
                f"\x1b[{self.rows - 5};2H{palette_rows[0]}"
                f"\x1b[{self.rows - 4};2H{palette_rows[1]}"
            )
        self._emit(f"\x1b[{self.rows - 2};1H{base()}{' ' * self.cols}\x1b[{self.rows - 2};1H\x1b[?25h")
        try:
            return input(rl(base() + prompt)).strip()
        finally:
            self.in_input = False
            clear = f"\x1b[?25l\x1b[{self.rows - 2};1H{base()}{' ' * self.cols}"
            if palette_rows:
                clear += f"\x1b[{self.rows - 5};1H{base()}{' ' * self.cols}"
                clear += f"\x1b[{self.rows - 4};1H{base()}{' ' * self.cols}"
            self._emit(clear)

    def _ask_command_line(self):
        """Raw-key input with an interactive slash-command picker."""
        line, selected = "", 0
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        self.in_input = True
        try:
            tty.setraw(fd)
            while True:
                prefix = line if line.startswith("/") and " " not in line else None
                matches = [c for c in COMMANDS if c.startswith(prefix)] if prefix is not None else []
                if matches:
                    selected = max(0, min(selected, len(matches) - 1))
                else:
                    selected = 0
                self._draw_command_line(line, matches, selected)
                ch = os.read(fd, 1).decode("utf-8", "ignore")
                if ch in ("\r", "\n"):
                    if matches and line.startswith("/") and " " not in line:
                        line = matches[selected] + " "
                        selected = 0
                        continue
                    return line.strip()
                if ch == "\x03":
                    raise KeyboardInterrupt
                if ch == "\x04":
                    raise EOFError
                if ch == "\x0c":  # Ctrl-L: redraw the current transcript
                    self.scroll_offset = 0
                    self.paint_transcript()
                    continue
                if ch in ("\x7f", "\b"):
                    line = line[:-1]; selected = 0; continue
                if ch == "\t" and matches:
                    line = matches[selected]; selected = 0; continue
                if ch == "\x1b":
                    # Read escape sequences as raw bytes. Python's buffered
                    # text reader can return only the '[' and leak the final
                    # 'A'/'B' into the prompt as literal text.
                    ready, _, _ = select.select([fd], [], [], 0.20)
                    seq = os.read(fd, 2).decode("ascii", "ignore") if ready else ""
                    if seq in ("[5", "[6"):
                        if select.select([fd], [], [], 0.05)[0]:
                            os.read(fd, 1)  # trailing '~'
                        self.scroll_transcript(8 if seq == "[5" else -8)
                        continue
                    if seq == "[A" and matches:
                        selected = (selected - 1) % len(matches)
                    elif seq == "[B" and matches:
                        selected = (selected + 1) % len(matches)
                    else:
                        line, selected = "", 0
                    continue
                if ch.isprintable():
                    line += ch; selected = 0
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            self.in_input = False
            self._emit(f"\x1b[?25h\x1b[{self.rows - 2};1H{base()}{' ' * self.cols}")
            for row in range(self.rows - 8, self.rows - 3):
                self._emit(f"\x1b[{row};1H{base()}{' ' * self.cols}")

    def _draw_command_line(self, line, matches, selected):
        prompt = f" {fg('gold')}\x1b[1m❯{base()} {line}"
        if matches:
            for offset in range(5):
                row, idx = self.rows - 8 + offset, selected + offset
                self._emit(f"\x1b[{row};1H{base()}{' ' * self.cols}\x1b[{row};2H")
                if idx < len(matches):
                    marker = "❯ " if idx == selected else "  "
                    style = f"{bg('gold')}{fg('on_gold')}" if idx == selected else fg('muted')
                    self._emit(f"{style}{marker}{matches[idx]}{base()}")
        else:
            # The picker occupies the lower transcript rows. When it closes
            # (or ordinary text is being typed), redraw those rows instead of
            # leaving them blank and hiding the newest assistant output.
            self.paint_transcript()
            for row in (self.rows - 4, self.rows - 3):
                self._emit(f"\x1b[{row};1H{base()}{' ' * self.cols}")
        self._emit(f"\x1b[{self.rows - 2};1H{base()}{' ' * self.cols}\x1b[{self.rows - 2};1H{prompt}")
        if matches:
            hint = f"{fg('muted')}↑↓ choose  ·  enter insert  ·  esc close{base()}"
            self._emit(f"\x1b[{self.rows - 3};2H{hint}")
        self._emit(f"\x1b[{self.rows - 2};{len(line) + 4}H\x1b[?25h")

    # -- welcome screen --------------------------------------------------------------------------------------
    def _git_branch(self):
        try:
            return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True,
                                  timeout=1).stdout.strip() or None
        except Exception:  # noqa: BLE001
            return None

    def paint_welcome(self):
        ctx = self.welcome_ctx
        if not ctx:
            return
        c, r = self.cols, self.rows
        sprite = max(6, min(20, r - 14))
        scols = R.sprite_cols(sprite) + 10
        srows = sprite + 3
        rw = min(60, c - scols - 6)
        if rw < 34:                       # too narrow for two columns: hero only
            rw = 0
        total_w = scols + (3 + rw if rw else 0)
        x0 = max(1, (c - total_w) // 2 + 1)
        right = self._welcome_text(rw) if rw else []
        content_h = max(srows + 4, len(right))
        y0 = max(1, (r - content_h) // 2)
        ctx.update(x0=x0, y0=y0, scols=scols, srows=srows, sprite=sprite)
        out = []
        for i, ln in enumerate(right):
            out.append(f"\x1b[{y0 + i};{x0 + scols + 3}H{base()}{ln}{base()}")
        self._overlay("".join(out))
        self.paint_hero()

    def paint_hero(self):
        ctx = self.welcome_ctx
        if not ctx or "x0" not in ctx:
            return
        with self.lock:
            stage, snap, now = self._stage_lines(ctx["scols"], ctx["srows"], ctx["sprite"],
                                                 pose_override=None)
            x0, y0 = ctx["x0"], ctx["y0"]
            out = [f"\x1b[{y0 + i};{x0}H{ln}" for i, ln in enumerate(stage)]
            msg = snap["toast"] or snap["message"] or ctx.get("hello", "")
            lines = wrap(f"“{msg}”", ctx["scols"] - 2)[:3]
            for i in range(3):
                t = lines[i] if i < len(lines) else ""
                out.append(f"\x1b[{y0 + ctx['srows'] + 1 + i};{x0}H{base()}{fg('text')}{t.center(ctx['scols'])}{base()}")
            self._overlay("".join(out))

    def _welcome_text(self, rw):
        ctx = self.welcome_ctx
        lines = [""]
        word = ""
        rows = []
        for i in range(5):
            row = "  ".join(WORDMARK[ch][i] for ch in "CORVI")
            rows.append(f"{fg('gold')}{row}")
        lines += rows
        lines += [f"{fg('text')}\x1b[1mYour Friendly Coding Companion.", ""]
        ok = ctx["server_ok"]
        dot = lambda good: f"{fg('ok' if good else 'err')}●{base()}"
        lines += [
            f" {dot(ok)} {fg('muted')}Model      {base()}{ctx['model'] or 'none found'}" + ("" if ok else f"  {fg('err')}server not reachable"),
            f" {dot(True)} {fg('muted')}Server     {base()}{clip_left(ctx['server'], rw - 16)}",
            f" {dot(True)} {fg('muted')}Workspace  {base()}{clip_left(short_path(os.getcwd()), rw - 16)}"
            + (f"  {fg('muted')}git:{ctx['branch']}" if ctx.get("branch") else ""),
            f" {dot(True)} {fg('muted')}Safety     {base()}asks before every edit and command",
            "",
        ]
        if not ok:
            lines += [f" {fg('warn')}Start your model server (e.g. `ollama serve`), or pass --base-url.", ""]
        lines += [f"{fg('gold')}\x1b[1m{ctx['heading']}"] + [f"{fg('text')}{x}" for x in ctx["options"]]
        if ctx.get("error"):
            lines += ["", f"{fg('err')}{ctx['error']}"]
        return [l[:0] + l if vlen(l) <= rw else l for l in lines]

    def welcome(self, env):
        """Two-step onboarding: pick workspace, pick a quick start. Returns (first_prompt or None)."""
        if not self.enabled:
            return None
        self.screen = "welcome"
        ctx = self.welcome_ctx = dict(env)
        ctx["hello"] = E.PERSONALITY["lines"]["APP_READY"][0]
        ctx["branch"] = self._git_branch()
        self.measure()
        recents = [p for p in self.s.get("recent_dirs") if os.path.isdir(p) and p != os.getcwd()][:3]
        ctx["heading"] = "Choose a workspace"
        ctx["options"] = [f" [1] {short_path(os.getcwd())}  (current folder)"] + \
                         [f" [{i + 2}] {short_path(p)}" for i, p in enumerate(recents)] + \
                         [f" {fg('muted')}…or type a path, or press Enter for the current folder"]
        self.m.handle("APP_READY")
        self._emit(base() + "\x1b[2J")
        self.paint_welcome()
        choices = [os.getcwd()] + recents
        while True:
            ctx["error"] = ""
            try:
                ans = self._welcome_ask("Workspace")
            except (EOFError, KeyboardInterrupt):
                return None
            if ans == "":
                break
            if ans.isdigit() and 1 <= int(ans) <= len(choices):
                target = choices[int(ans) - 1]
            else:
                target = os.path.abspath(os.path.expanduser(ans))
            if os.path.isdir(target):
                os.chdir(target)
                ctx["branch"] = self._git_branch()
                break
            ctx["error"] = f"“{ans}” isn't a folder. Try again."
            self._emit(base() + "\x1b[2J")
            self.paint_welcome()
        self.s.add_recent(os.getcwd())
        self.m.handle("PROJECT_OPENED")
        self.m.say(E.PERSONALITY["lines"]["PROJECT_OPENED"][0])
        actions = [
            ("Explore this project", "Take a look around this project and give me a short tour: what it does, how it is laid out, and how to run it."),
            ("Run the tests and fix failures", "Run this project's tests. If anything fails, diagnose it and propose a fix."),
            ("Review my uncommitted changes", "Review my uncommitted changes (use git diff) and point out any problems."),
            ("Build something new", None),
            ("Just chat", None),
        ]
        ctx["heading"] = "Quick start"
        ctx["options"] = [f" [{i + 1}] {a[0]}" for i, a in enumerate(actions)] + [f" {fg('muted')}Press Enter to start with an empty prompt"]
        ctx["error"] = ""
        self._emit(base() + "\x1b[2J")
        self.paint_welcome()
        try:
            ans = self._welcome_ask("Start")
        except (EOFError, KeyboardInterrupt):
            ans = ""
        first = actions[int(ans) - 1][1] if ans.isdigit() and 1 <= int(ans) <= len(actions) else None
        self.screen = "main"
        self.welcome_ctx = None
        return first

    def _welcome_ask(self, label):
        ctx = self.welcome_ctx
        y = min(self.rows - 1, ctx["y0"] + max(ctx["srows"] + 4, 20) + 1)
        y = min(y, self.rows - 1)
        self.in_input = True
        self._emit(f"\x1b[{y};{ctx['x0'] + ctx['scols'] + 3}H{base()}{' ' * 40}\x1b[{y};{ctx['x0'] + ctx['scols'] + 3}H\x1b[?25h")
        try:
            return input(rl(f"{base()}{fg('gold')}\x1b[1m{label} ❯{base()} ")).strip()
        finally:
            self.in_input = False
            self._emit("\x1b[?25l")

    # -- farewell (after leaving the full-screen view) -------------------------------------------------------
    def farewell(self, text):
        self.m.handle("GOODBYE")
        cells = R.render_stage("greeting", 20, 9, 6, "open", 0, 0, stage=THEMES["dark"]["stage"], quad=self.s.get("glyphs") == "quad")
        lines = R.cells_to_ansi(cells, reset="\x1b[0m")
        mid = len(lines) // 2
        print()
        for i, ln in enumerate(lines):
            tail = ""
            if i == mid - 1:
                tail = f"  \x1b[1m{text}\x1b[0m"
            elif i == mid:
                tail = "  \x1b[2mCorvi · Your Friendly Coding Companion.\x1b[0m"
            print(" " + ln + tail)
        print()
