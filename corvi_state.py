"""Small, filesystem-backed sessions and snapshots for Corvi."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path


class StateStore:
    def __init__(self, root: Path):
        self.root = root / ".corvi"
        self.sessions = self.root / "sessions"
        self.snapshots = self.root / "snapshots"
        self.sessions.mkdir(parents=True, exist_ok=True)
        self.snapshots.mkdir(parents=True, exist_ok=True)

    def save_session(self, name: str, messages: list[dict], model: str) -> Path:
        path = self.sessions / f"{name or 'default'}.json"
        path.write_text(json.dumps({"model": model, "messages": messages}, indent=2), encoding="utf-8")
        return path

    def load_session(self, name: str) -> dict:
        path = self.sessions / f"{name or 'default'}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def list_sessions(self) -> list[str]:
        return sorted(path.stem for path in self.sessions.glob("*.json"))

    def fork_session(self, source: str, target: str) -> Path:
        data = self.load_session(source)
        return self.save_session(target, data.get("messages", []), data.get("model", "auto"))

    def list_snapshots(self) -> list[str]:
        return sorted(path.name for path in self.snapshots.iterdir() if path.is_dir())

    def snapshot(self, root: Path) -> Path:
        target = self.snapshots / str(int(time.time() * 1000))
        target.mkdir(parents=True)
        for path in root.iterdir():
            if path.name in {".corvi", ".git", "node_modules", "__pycache__"}:
                continue
            dest = target / path.name
            if path.is_dir():
                shutil.copytree(path, dest, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"))
            else:
                shutil.copy2(path, dest)
        return target

    def undo(self, root: Path) -> Path | None:
        snapshots = sorted((p for p in self.snapshots.iterdir() if p.is_dir()), key=lambda p: p.name)
        if not snapshots:
            return None
        source = snapshots[-1]
        for path in root.iterdir():
            if path.name in {".corvi", ".git", "node_modules", "__pycache__"}:
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        for path in source.iterdir():
            dest = root / path.name
            if path.is_dir():
                shutil.copytree(path, dest)
            else:
                shutil.copy2(path, dest)
        return source
