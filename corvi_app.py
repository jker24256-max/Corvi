"""Corvi desktop app - professional AI coding companion with polished UI.

Run with: python3 corvi_app.py
A modern, professional desktop application for local AI-powered coding with
a pet mascot (Corvi the raven), achievement system, and rich interactive features.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import json
import os
import subprocess
import sys
import time

import kit
from mascot.engine import Achievements, Settings
from corvi_council import deliberate


class CorviApp(tk.Tk):
    """Professional desktop coding companion with mascot panel and Codex-like UX."""

    # ── colour palette ──────────────────────────────────────────────
    BG_DARK     = "#0f0f17"       # main window bg
    BG_CARD     = "#1e1e24"       # cards / panels
    BG_ACCENT   = "#2a2a3a"       # subtle accent bg
    TEXT_PRIMARY= "#e8e8f0"       # primary text
    TEXT_SECONDARY= "#b5b5c5"     # secondary text
    TEXT_MUTED  = "#858596"       # muted text
    ACCENT_CYAN = "#00d4aa"       # accent colour
    ACCENT_ORANGE = "#ff6b35"     # warn / highlight
    ACCENT_BLUE = "#3b82f6"       # interactive blue
    BORDER_COLOR= "#3a3a4a"       # dividers / borders

    # ── spacing constants ───────────────────────────────────────────
    GAP_XS      = 4
    GAP_S       = 8
    GAP_M       = 12
    GAP_L       = 16
    GAP_XL      = 24
    GAP_2XL     = 32

    PAD_X       = 16
    PAD_Y       = 12

    # ── typography constants ────────────────────────────────────────
    FX_SYSTEM   = "SF Pro Display, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    FX_MONO     = "SF Mono, Menlo, Monaco, Consolas, 'Liberation Mono', monospace"

    FONT_TITLE  = ("SF Pro Display", 20, "bold")
    FONT_SUBTITLE = ("SF Pro Display", 13, "bold")
    FONT_BODY   = ("SF Pro Text", 13)
    FONT_SMALL  = ("SF Pro Text", 11)
    FONT_MONO_11= ("SF Mono", 11)
    FONT_MONO_13= ("SF Mono", 13)

    # ── -----------------------------------------------------------------
    def __init__(self):
        super().__init__()
        self.title("Corvi")
        self.geometry("1200x780")
        self.minsize(960, 600)
        self._setup_window()
        self.cfg = kit.Cfg("http://localhost:11434/v1", "ollama", "auto")
        self.project = Path.cwd()
        self.messages = []
        self.achievements = Achievements(Settings())
        self.models = []
        self._build()
        self._append_system("Welcome to Corvi. Choose a model or leave it on Auto, select a project, and start chatting.")
        self._refresh_models()
        self._wire_events()

    # ── window chrome ───────────────────────────────────────────────
    def _setup_window(self):
        """Set up window appearance (title bar, transparency, etc.)."""
        try:
            if sys.platform == "darwin":
                pass
        except Exception:
            pass
        try:
            self.tk.call("tk", "scaling", 1.0)
        except Exception:
            pass
        self.configure(background=self.BG_DARK)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.BG_DARK)
        style.configure("TLabel", background=self.BG_DARK, foreground=self.TEXT_PRIMARY)
        style.configure("TButton", background=self.BG_ACCENT, foreground=self.TEXT_PRIMARY,
                        padding=(10, 6), borderwidth=0, relief="flat")
        style.map("TButton", background=[("active", self.ACCENT_BLUE)], foreground=[("active", "white")])
        style.configure("Action.TButton", background=self.BG_CARD, foreground=self.TEXT_PRIMARY,
                        anchor="w", padding=(12, 8))
        style.map("Action.TButton", background=[("active", self.BG_ACCENT)])
        style.configure("TCheckbutton", background=self.BG_DARK, foreground=self.TEXT_PRIMARY)
        style.configure("TCombobox", fieldbackground=self.BG_ACCENT, background=self.BG_ACCENT,
                        foreground=self.TEXT_PRIMARY, arrowcolor=self.ACCENT_CYAN,
                        bordercolor=self.BORDER_COLOR, lightcolor=self.BORDER_COLOR,
                        darkcolor=self.BORDER_COLOR)
        style.map("TCombobox", fieldbackground=[("readonly", self.BG_ACCENT)],
                  foreground=[("readonly", self.TEXT_PRIMARY)])
        style.configure("Input.TFrame", background=self.BG_CARD, relief="flat")
        style.configure("Vertical.TScrollbar", troughcolor=self.BG_DARK, background=self.BG_ACCENT,
                        bordercolor=self.BG_DARK, arrowcolor=self.TEXT_SECONDARY)

    # ── main build ──────────────────────────────────────────────────
    def _build(self):
        """Layout the entire UI."""
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_navigation()
        self._build_top_bar()
        self._build_main()
        self._build_status_bar()

    def _build_navigation(self):
        """Codex-style task navigation rail."""
        nav = ttk.Frame(self, padding=(12, 14, 10, 12))
        nav.grid(row=0, column=0, rowspan=3, sticky="nsew")
        nav.configure(width=230)
        nav.grid_propagate(False)
        nav.columnconfigure(0, weight=1)
        ttk.Label(nav, text="◈  CORVI", font=self.FONT_TITLE,
                  foreground=self.ACCENT_CYAN).grid(row=0, column=0, sticky="w", pady=(0, 18))
        ttk.Button(nav, text="＋  New task", style="Action.TButton",
                   command=self._new_task).grid(row=1, column=0, sticky="ew", pady=(0, 18))
        ttk.Label(nav, text="WORKSPACE", font=self.FONT_SMALL,
                  foreground=self.TEXT_MUTED).grid(row=2, column=0, sticky="w", pady=(0, 6))
        self.nav_project = ttk.Label(nav, text=self._proj_short(), foreground=self.TEXT_SECONDARY,
                                     wraplength=190)
        self.nav_project.grid(row=3, column=0, sticky="w", pady=(0, 16))
        ttk.Button(nav, text="⌂  Open project", style="Action.TButton",
                   command=self._choose_project).grid(row=4, column=0, sticky="ew", pady=2)
        ttk.Button(nav, text="▣  Session history", style="Action.TButton",
                   command=self._do_view_session).grid(row=5, column=0, sticky="ew", pady=2)
        ttk.Label(nav, text="TOOLS", font=self.FONT_SMALL,
                  foreground=self.TEXT_MUTED).grid(row=6, column=0, sticky="w", pady=(22, 6))
        for row, (label, command) in enumerate((("✦  Explain project", self._do_explain_project),
                                                 ("⌕  Find bugs", self._do_find_bugs),
                                                 ("?  Ollama help", lambda: self._send_text("Explain how to use Ollama with this project."))), start=7):
            ttk.Button(nav, text=label, style="Action.TButton", command=command).grid(row=row, column=0, sticky="ew", pady=2)
        nav.rowconfigure(11, weight=1)
        ttk.Label(nav, text="Local-first · Ollama\nSafe edits require approval",
                  foreground=self.TEXT_MUTED, font=self.FONT_SMALL).grid(row=12, column=0, sticky="sw")

    def _build_top_bar(self):
        """Top bar with app name, model selector, and actions."""
        top = ttk.Frame(self, padding=(self.GAP_L, self.GAP_M, self.GAP_L, self.GAP_M))
        top.grid(row=0, column=1, sticky="ew")
        top.columnconfigure(6, weight=1)

        # left: app name & mascot indicator
        ttk.Label(top, text="New task", font=self.FONT_TITLE, foreground=self.TEXT_PRIMARY).grid(
            row=0, column=0, padx=(0, self.GAP_S), sticky="w")

        # centre: model selector
        ttk.Label(top, text="Model", font=self.FONT_SMALL, foreground=self.TEXT_SECONDARY).grid(
            row=0, column=1, padx=(0, self.GAP_XS))

        self.model = ttk.Combobox(top, state="readonly", width=20, font=self.FONT_SMALL)
        self.model.set("auto")
        self.model.grid(row=0, column=2, padx=(0, self.GAP_M))

        # refresh button - wrapped in lambda
        ttk.Button(top, text="Refresh",
                    command=lambda: self._refresh_models(),
                    takefocus=False).grid(row=0, column=3, padx=(0, self.GAP_M))

        # project button - wrapped in lambda
        ttk.Button(top, text="Project",
                    command=lambda: self._choose_project(),
                    takefocus=False).grid(row=0, column=4, padx=(0, self.GAP_XS))

        # council checkbutton (no command issue, uses variable)
        self.council_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Council", variable=self.council_var,
                        takefocus=False).grid(row=0, column=5, padx=(0, self.GAP_XS))

    def _build_sidebar(self):
        """Left sidebar with quick actions and info."""
        side = ttk.Frame(self, padding=(self.GAP_L, self.GAP_S, self.GAP_M, self.GAP_S))
        side.grid(row=1, column=0, sticky="ns")
        side.rowconfigure(10, weight=1)

        # workspace header
        ttk.Label(side, text="WORKSPACE", font=self.FONT_SUBTITLE,
                   foreground=self.ACCENT_CYAN).grid(row=0, column=0, sticky="w", pady=(0, self.GAP_S))

        self.proj_label = ttk.Label(side, text=self._proj_short(), font=self.FONT_BODY,
                                     foreground=self.TEXT_SECONDARY)
        self.proj_label.grid(row=1, column=0, sticky="w")

        # quick action buttons
        ttk.Label(side, text="QUICK ACTIONS", font=self.FONT_SUBTITLE,
                   foreground=self.ACCENT_CYAN).grid(row=2, column=0, sticky="w", pady=(self.GAP_L, self.GAP_XS))

        actions = [
            ("📝 Explain project", self._do_explain_project),
            ("🐛 Find bugs", self._do_find_bugs),
            ("🔧 Ollama help", lambda: self._send_text("Ollama help")),
            ("📊 View session", self._do_view_session),
            ("🏆 Achievements", self._show_achievements),
        ]

        for i, (label, cmd) in enumerate(actions):
            # wrap each command in lambda to avoid tkinter lookup issues
            btn = ttk.Button(side, text=label,
                             command=lambda c=cmd: c(),
                             style="Action.TButton")
            btn.grid(row=3+i, column=0, sticky="w", pady=self.GAP_XS//2)

        side.rowconfigure(10, weight=1)

    def _build_main(self):
        """Main chat area with transcript and input."""
        main = ttk.Frame(self, padding=(self.GAP_XS, self.GAP_S, self.GAP_XS, self.GAP_S))
        main.grid(row=1, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        # The transcript expands; the composer stays compact at the bottom.
        main.rowconfigure(0, weight=1)
        main.rowconfigure(1, weight=0)

        # chat transcript
        self.chat = tk.Text(
            main, wrap="word", state="disabled",
            font=self.FONT_BODY,
            background="#181922",
            foreground=self.TEXT_PRIMARY,
            insertbackground=self.ACCENT_CYAN,
            selectbackground=self.ACCENT_BLUE,
            selectforeground="white",
            relief="flat", borderwidth=0,
        )
        self.chat.grid(row=0, column=0, sticky="nsew", pady=(self.GAP_L, self.GAP_M))
        self._apply_chat_tags()

        # scrollbar
        v_scroll = ttk.Scrollbar(main, orient="vertical", command=self.chat.yview,
                                  style="Vertical.TScrollbar")
        v_scroll.grid(row=0, column=1, sticky="ns", pady=0)
        self.chat.configure(yscrollcommand=v_scroll.set)

        # input area
        bottom = ttk.Frame(main, style="Input.TFrame")
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(self.GAP_M, 0))
        bottom.columnconfigure(0, weight=1)

        # entry
        self.entry = tk.Entry(
            bottom, font=self.FONT_MONO_13,
            background=self.BG_ACCENT,
            foreground=self.TEXT_PRIMARY,
            insertbackground=self.ACCENT_CYAN,
            relief="flat", borderwidth=0,
            selectbackground=self.ACCENT_BLUE,
            selectforeground="white",
        )
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, self.GAP_XS))
        self.entry.bind("<Return>", self._on_enter_pressed)
        self.entry.bind("<Shift-Return>", self._on_shift_enter)
        self.entry.bind("<FocusIn>", self._on_entry_focus_in)
        self.entry.bind("<FocusOut>", self._on_entry_focus_out)

        # send button
        send_btn = ttk.Button(bottom, text="Send  ➜", width=10, takefocus=False,
                               command=self._send_entry)
        send_btn.grid(row=0, column=1, padx=(self.GAP_XS, 0))

        # hint text (hidden on focus)
        self.hint_var = tk.StringVar(value="Type a message (Ctrl+Enter to send)")
        self.hint_label = ttk.Label(bottom, textvariable=self.hint_var,
                                     font=self.FONT_SMALL, foreground=self.TEXT_MUTED)

    # ── status bar ────────────────────────────────────────────────
    def _build_status_bar(self):
        """Professional status bar at bottom of main window."""
        self.status = ttk.Label(self, text="Connecting to Ollama…",
                                 font=self.FONT_SMALL, foreground=self.TEXT_MUTED)
        self.status.grid(row=2, column=1, sticky="ew", padx=self.GAP_L, pady=(0, 8))
        self._update_status_bar()

    def _update_status_bar(self):
        """Refresh status bar text."""
        try:
            model = self.model.get() or "auto"
            proj = self._proj_short()
            # Only update to model name after we have models loaded
            if self.model["values"] and len(self.model["values"]) > 1:
                self.status.configure(text=f"Model: {model}  |  {proj}")
            else:
                self.status.configure(text="Connecting to Ollama…")
        except Exception:
            self.status.configure(text="Connecting to Ollama…")
        self.after(3000, self._update_status_bar)

    # ── event wiring ──────────────────────────────────────────────
    def _wire_events(self):
        """Bind miscellaneous events."""
        self.bind("<Escape>", self._on_escape)
        self.bind("<Configure>", self._on_configure)

    # ── utility methods ────────────────────────────────────────────
    def _proj_short(self) -> str:
        """Short project display string."""
        p = str(self.project)
        home = str(Path.home())
        if p.startswith(home):
            p = "~" + p[len(home):]
        return p or "—"

    def _apply_chat_tags(self):
        """Configure text tags for speaker colouring."""
        self.chat.tag_config("user", foreground=self.ACCENT_ORANGE, font=("SF Pro Text", 12, "bold"),
                             spacing1=10, spacing3=2)
        self.chat.tag_config("corvi", foreground=self.ACCENT_CYAN, font=("SF Pro Text", 12, "bold"),
                             spacing1=10, spacing3=2)
        self.chat.tag_config("system", foreground=self.TEXT_SECONDARY, font=self.FONT_BODY,
                             spacing1=12, spacing3=8)
        self.chat.tag_config("user_body", foreground=self.TEXT_PRIMARY, lmargin1=12, lmargin2=12,
                             rmargin=24, spacing3=10)
        self.chat.tag_config("corvi_body", foreground=self.TEXT_PRIMARY, lmargin1=12, lmargin2=12,
                             rmargin=24, spacing3=14)

    # ── input handling ────────────────────────────────────────────
    def _on_enter_pressed(self, event):
        """Handle Enter key press - send message."""
        # Check if Ctrl is down (bit 0x1)
        if event.state & 0x1:
            self._send_entry()
            return "break"
        # Plain Enter = send (Shift-Enter is handled separately)
        self._send_entry()
        return "break"

    def _on_shift_enter(self, event):
        """Shift+Enter inserts a newline into the entry widget."""
        self.entry.insert(tk.INSERT, "\n")
        return "break"

    def _on_entry_focus_in(self, event):
        """Hide placeholder hint on focus."""
        self.hint_label.place_forget()

    def _on_entry_focus_out(self, event):
        """Show placeholder hint when focus leaves and entry is empty."""
        if not self.entry.get().strip():
            self.hint_label.place(
                x=6, y=self.entry.winfo_reqheight() + 6,
                width=self.entry.winfo_reqwidth(), height=18)

    def _send_entry(self):
        """Send the current entry text to the model."""
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        self.hint_label.place_forget()
        self._append_user(text)
        self.status.configure(text="Corvi is thinking…")
        threading.Thread(target=self._process_entry, args=(text,), daemon=True).start()

    def _new_task(self):
        """Start a clean Codex-style task without closing the app."""
        self.chat.configure(state="normal")
        self.chat.delete("1.0", tk.END)
        self.chat.configure(state="disabled")
        self._append_system("New task started. What would you like to build?")
        self.entry.focus_set()

    # ── model interaction ─────────────────────────────────────────
    def _process_entry(self, prompt: str):
        """Call the kit backend and pump results back into the UI."""
        try:
            selected = kit.choose_model(self.cfg, prompt, self.models) if self.model.get() == "auto" else self.model.get()
            cfg = kit.Cfg(self.cfg.base_url, self.cfg.api_key, selected)
            parts = []
            kit.stream_chat(cfg, [{"role": "user", "content": prompt}], parts.append, use_tools=False)
            text = "".join(parts) or "(The model returned no text.)"
        except Exception as exc:
            text = f"Error: {str(exc)[:200]}"

        self.after(0, self._append_corvi, text)
        self.after(0, lambda: self.status.configure(text="Ready"))

    # ── transcript append ─────────────────────────────────────────
    def _append_user(self, text: str):
        """Append a user message to the chat display."""
        self.chat.configure(state="normal")
        self.chat.insert(tk.END, "You\n", "user")
        self.chat.insert(tk.END, f"{text}\n", "user_body")
        self.chat.configure(state="disabled")
        self.chat.see(tk.END)

    def _append_corvi(self, text: str):
        """Append Corvi's response to the chat display."""
        self.chat.configure(state="normal")
        self.chat.insert(tk.END, "Corvi\n", "corvi")
        self.chat.insert(tk.END, f"{text}\n", "corvi_body")
        self.chat.configure(state="disabled")
        self.chat.see(tk.END)

    def _append_system(self, text: str):
        """Append a system message (greyed-out)."""
        self.chat.configure(state="normal")
        self.chat.insert(tk.END, "System\n", "system")
        self.chat.insert(tk.END, f"{text}\n\n", "system")
        self.chat.configure(state="disabled")
        self.chat.see(tk.END)

    # ── slash-command-style quick actions ─────────────────────────
    def _do_explain_project(self):
        """Explain the current project."""
        prompt = "Explain this project and its important files."
        self._send_entry_with_prompt(prompt)

    def _do_find_bugs(self):
        """Find bugs in the current project."""
        prompt = "Inspect the current project for likely bugs and suggest fixes."
        self._send_entry_with_prompt(prompt)

    def _send_entry_with_prompt(self, prompt: str):
        """Send a generated prompt to the model and clear entry."""
        self.entry.delete(0, tk.END)
        self.hint_label.place_forget()
        self._append_user(prompt)
        self.status.configure(text="Corvi is thinking…")
        threading.Thread(target=self._process_entry, args=(prompt,), daemon=True).start()

    def _do_view_session(self):
        """Show session/snapshot management."""
        self._append_system("Session listing not implemented in this demo.")

    def _show_achievements(self):
        """Show unlocked achievements."""
        achieved = self.achievements.summary()
        lines = ["🏆 Achievements"]
        if not achieved:
            lines.append("No achievements yet.\nStart coding to unlock them!")
        else:
            for key, title, desc, unlocked in achieved:
                if unlocked:
                    lines.append(f"• {title}")
                    lines.append(f"  {desc}")
        msg = "\n".join(lines)
        messagebox.showinfo("Achievements", msg)

    # ── misc event handlers ───────────────────────────────────────
    def _on_escape(self, event):
        """Escape key – confirm exit."""
        if messagebox.askyesno("Quit Corvi", "Are you sure you want to quit?"):
            self.quit()
        else:
            self.lift()

    def _on_configure(self, event):
        """Handle window resize – keep hint positioned."""
        if not self.entry.winfo_exists():
            return
        try:
            self.hint_label.place_configure(
                x=6, y=self.entry.winfo_reqheight() + 6,
                width=self.entry.winfo_reqwidth(), height=18)
        except Exception:
            pass

    def _refresh_models(self):
        """Fetch available Ollama models in a background thread."""
        def _work():
            try:
                models = kit.list_models(self.cfg)
            except Exception as exc:
                models = []
                error = str(exc)
            else:
                error = ""
            def _done():
                self.models = models
                if models:
                    self.model["values"] = ["auto"] + models
                    cur = self.model.get()
                    if cur not in models and cur != "auto":
                        self.model.set("auto")
                    self.status.configure(text=f"{len(models)} model(s) available")
                else:
                    self.status.configure(text=f"Ollama unavailable: {error}")
            self.after(0, _done)

        threading.Thread(target=_work, daemon=True).start()

    def _choose_project(self):
        """Allow the user to pick a project directory."""
        chosen = filedialog.askdirectory(initialdir=str(self.project))
        if chosen:
            self.project = Path(chosen)
            self.nav_project.configure(text=self._proj_short())
            self._append_system(f"Project changed to {self.project}")

    def main(self):
        """Start the Tkinter main loop."""
        self.mainloop()


def main():
    app = CorviApp()
    app.main()


if __name__ == "__main__":
    main()
