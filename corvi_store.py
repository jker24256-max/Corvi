"""Small local SQLite store for Corvi tasks and messages."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = Path(__file__).resolve().parent / "replica" / "schema.sql"


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root=None):
        root = Path(root or Path.cwd())
        state = root / ".corvi"
        state.mkdir(parents=True, exist_ok=True)
        self.path = state / "corvi.db"
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA.read_text())
        try: self.db.execute("ALTER TABLE approvals ADD COLUMN arguments_json TEXT NOT NULL DEFAULT '{}'")
        except sqlite3.OperationalError: pass
        self.db.commit()

    def workspace(self, path):
        path = str(Path(path).resolve()); row = self.db.execute("SELECT * FROM workspaces WHERE path=?", (path,)).fetchone()
        if row: return dict(row)
        item = (str(uuid.uuid4()), Path(path).name or "Workspace", path, now(), now())
        self.db.execute("INSERT INTO workspaces(id,name,path,created_at,updated_at) VALUES(?,?,?,?,?)", item); self.db.commit()
        return dict(self.db.execute("SELECT * FROM workspaces WHERE id=?", (item[0],)).fetchone())

    def workspaces(self):
        return [dict(x) for x in self.db.execute("SELECT * FROM workspaces ORDER BY updated_at DESC").fetchall()]

    def create_task(self, workspace_path, title, model="auto"):
        ws = self.workspace(workspace_path); task_id = str(uuid.uuid4()); stamp = now()
        self.db.execute("INSERT INTO tasks(id,workspace_id,title,selected_model,created_at,updated_at) VALUES(?,?,?,?,?,?)", (task_id, ws["id"], title[:120], model, stamp, stamp))
        self.db.commit(); return dict(self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def recent(self, workspace_path, limit=20):
        ws = self.workspace(workspace_path)
        return [dict(x) for x in self.db.execute("SELECT * FROM tasks WHERE workspace_id=? AND status!='archived' ORDER BY pinned DESC, updated_at DESC LIMIT ?", (ws["id"], limit)).fetchall()]

    def search_tasks(self, workspace_path, query):
        ws = self.workspace(workspace_path); q = f"%{query}%"
        return [dict(x) for x in self.db.execute("SELECT * FROM tasks WHERE workspace_id=? AND status!='archived' AND title LIKE ? ORDER BY pinned DESC, updated_at DESC", (ws['id'], q)).fetchall()]

    def update_task(self, task_id, **fields):
        allowed = {k:v for k,v in fields.items() if k in {'title','status','pinned'}}
        if not allowed: return
        self.db.execute("UPDATE tasks SET "+", ".join(k+"=?" for k in allowed)+", updated_at=? WHERE id=?", (*allowed.values(), now(), task_id)); self.db.commit()

    def add_message(self, task_id, role, content, model=None):
        stamp = now(); self.db.execute("INSERT INTO messages(id,task_id,role,content,model,created_at) VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()), task_id, role, content, model, stamp)); self.db.execute("UPDATE tasks SET updated_at=? WHERE id=?", (stamp, task_id)); self.db.commit()

    def messages(self, task_id):
        return [dict(x) for x in self.db.execute("SELECT * FROM messages WHERE task_id=? ORDER BY created_at", (task_id,)).fetchall()]

    def start_run(self, task_id, model="auto"):
        run_id = str(uuid.uuid4()); stamp = now()
        self.db.execute("INSERT INTO agent_runs(id,task_id,status,model,started_at) VALUES(?,?,?,?,?)", (run_id, task_id, "running", model, stamp))
        self.db.execute("UPDATE tasks SET status='running', updated_at=? WHERE id=?", (stamp, task_id)); self.db.commit()
        return run_id

    def finish_run(self, run_id, task_id, status="ready", error=None):
        stamp = now(); self.db.execute("UPDATE agent_runs SET status=?, finished_at=?, error=? WHERE id=?", (status, stamp, error, run_id)); self.db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, stamp, task_id)); self.db.commit()

    def add_activity(self, run_id, kind, title, detail="", status="success"):
        item_id = str(uuid.uuid4()); self.db.execute("INSERT INTO activity_items(id,run_id,kind,title,detail,status,created_at) VALUES(?,?,?,?,?,?,?)", (item_id, run_id, kind, title, detail, status, now())); self.db.commit(); return item_id

    def activities(self, task_id):
        return [dict(x) for x in self.db.execute("SELECT a.* FROM activity_items a JOIN agent_runs r ON r.id=a.run_id WHERE r.task_id=? ORDER BY a.created_at", (task_id,)).fetchall()]

    def approvals(self, task_id):
        return [dict(x) for x in self.db.execute("SELECT a.* FROM approvals a JOIN agent_runs r ON r.id=a.run_id WHERE r.task_id=? ORDER BY a.created_at DESC", (task_id,)).fetchall()]

    def approval(self, approval_id):
        row = self.db.execute("SELECT a.*, r.task_id, r.id AS run_id FROM approvals a JOIN agent_runs r ON r.id=a.run_id WHERE a.id=?", (approval_id,)).fetchone()
        return dict(row) if row else None

    def decide_approval(self, approval_id, decision, feedback=""):
        self.db.execute("UPDATE approvals SET decision=?, feedback=?, decided_at=? WHERE id=?", (decision, feedback, now(), approval_id)); self.db.commit()

    def create_approval(self, run_id, action_type, target, summary, arguments=None):
        approval_id = str(uuid.uuid4()); self.db.execute("INSERT INTO approvals(id,run_id,action_type,target,summary,arguments_json,created_at) VALUES(?,?,?,?,?,?,?)", (approval_id, run_id, action_type, target, summary, json.dumps(arguments or {}), now())); self.db.commit(); return approval_id

    def retry_approval(self, approval_id, feedback=""):
        item = self.approval(approval_id)
        if not item: return None
        self.decide_approval(approval_id, "denied", feedback)
        return self.create_approval(item["run_id"], item["action_type"], item["target"], item["summary"], json.loads(item.get("arguments_json") or "{}"))

    def artifacts(self, task_id):
        return [dict(x) for x in self.db.execute("SELECT * FROM artifacts WHERE task_id=? ORDER BY created_at DESC", (task_id,)).fetchall()]

    def add_artifact(self, task_id, kind, title, path_or_url):
        item_id = str(uuid.uuid4()); self.db.execute("INSERT INTO artifacts(id,task_id,kind,title,path_or_url,created_at) VALUES(?,?,?,?,?,?)", (item_id, task_id, kind, title, path_or_url, now())); self.db.commit(); return item_id
