"""Dependency-free smoke/e2e checks for Corvi's local HTTP surface."""
from __future__ import annotations

import json
import subprocess
import time
import urllib.request
import urllib.parse
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


def request(url, method, payload):
    raw = json.dumps(payload).encode(); req = urllib.request.Request(url, data=raw, method=method, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read())


def stream_request(url, payload):
    raw = json.dumps(payload).encode(); req = urllib.request.Request(url, data=raw, method="POST", headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, [json.loads(line) for line in r.read().decode().splitlines() if line]


def main():
    proc = subprocess.Popen(["python3", "corvi_webapp.py", "--serve", "--port", "8877"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                status, html = get("http://127.0.0.1:8877/"); break
            except Exception:
                time.sleep(.15)
        else: raise AssertionError("local server did not start")
        assert status == 200 and b"Ready when you are" in html
        status, data = get("http://127.0.0.1:8877/api/models")
        assert status == 200 and "models" in json.loads(data)
        status, data = get("http://127.0.0.1:8877/api/settings/permissions")
        assert status == 200 and "permissions" in json.loads(data)
        status, data = get("http://127.0.0.1:8877/api/integrations")
        integrations = json.loads(data)
        assert status == 200 and all(k in integrations for k in ("mcp", "skills", "plugins"))
        status, data = request("http://127.0.0.1:8877/api/integrations/reload", "POST", {})
        assert status == 200 and data["ok"] is True
        status, events = stream_request("http://127.0.0.1:8877/api/command/stream", {"command":"printf 'hello\\n'"})
        assert status == 200 and events[0]["type"] == "start" and events[1]["text"] == "hello\n" and events[-1]["exit_code"] == 0
        try:
            request("http://127.0.0.1:8877/api/integrations/mcp/not-configured", "POST", {"enabled":False})
            raise AssertionError("unknown MCP server was accepted")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        from corvi_ext import mcp_servers
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "opencode.json").write_text('{invalid', encoding="utf-8")
            assert mcp_servers(root) == {}
        status, data = request("http://127.0.0.1:8877/api/settings/permissions", "POST", {"permissions":{"edit_file":"ask"}})
        assert status == 200 and data["permissions"]["edit_file"] == "ask"
        status, raw = get("http://127.0.0.1:8877/api/workspace")
        data = json.loads(raw)
        assert status == 200 and data["path"] == str(ROOT.resolve())
        status, raw = get("http://127.0.0.1:8877/api/workspaces")
        assert status == 200 and "workspaces" in json.loads(raw)
        status, data = request("http://127.0.0.1:8877/api/settings/permissions", "POST", {"permissions":{"edit_file":"deny","write_file":"ask","run_bash":"allow","mcp":"ask"}})
        assert status == 200 and data["permissions"]["edit_file"] == "deny" and data["permissions"]["run_bash"] == "allow"
        status, data = get("http://127.0.0.1:8877/api/tasks")
        assert status == 200 and "tasks" in json.loads(data)
        from corvi_store import Store
        store = Store(ROOT); task = store.create_task(ROOT, "Review fixture"); run = store.start_run(task["id"], "auto")
        status, data = request("http://127.0.0.1:8877/api/tasks/" + task["id"], "POST", {"title":"Renamed fixture", "pinned":1})
        assert status == 200 and data["ok"] is True
        status, raw = get("http://127.0.0.1:8877/api/tasks/search?q=Renamed")
        assert status == 200 and json.loads(raw)["tasks"][0]["title"] == "Renamed fixture"
        status, data = request("http://127.0.0.1:8877/api/tasks/" + task["id"], "POST", {"status":"archived"})
        assert status == 200 and data["ok"] is True
        status, raw = get("http://127.0.0.1:8877/api/tasks")
        assert all(x["id"] != task["id"] for x in json.loads(raw)["tasks"])
        task = store.create_task(ROOT, "Review fixture")
        run = store.start_run(task["id"], "auto")
        fixture = ROOT / "e2e" / ".approval_fixture.txt"; fixture.write_text("old\n", encoding="utf-8")
        approval = store.create_approval(run, "edit_file", str(fixture), "Update approval fixture", {"path":str(fixture), "old_string":"old\n", "new_string":"new\n"})
        status, raw = get("http://127.0.0.1:8877/api/review?task_id=" + urllib.parse.quote(task["id"]))
        data = json.loads(raw)
        assert status == 200 and data["approvals"] and data["approvals"][0]["id"] == approval and "diff" in data["approvals"][0]
        status, data = request("http://127.0.0.1:8877/api/review/" + approval, "POST", {"decision":"approved"})
        assert status == 200 and data["ok"] is True and fixture.read_text(encoding="utf-8") == "new\n"
        retry = store.create_approval(run, "edit_file", str(fixture), "Retry approval fixture", {"path":str(fixture), "old_string":"new\n", "new_string":"done\n"})
        status, data = request("http://127.0.0.1:8877/api/review/" + retry, "POST", {"decision":"retry", "feedback":"Try again"})
        assert status == 200 and data["status"] == "pending" and data["approval_id"]
        status, data = request("http://127.0.0.1:8877/api/review/" + data["approval_id"], "POST", {"decision":"denied", "feedback":"Stop"})
        assert status == 200 and data["status"] == "blocked" and fixture.read_text(encoding="utf-8") == "new\n"
        fixture.unlink()
        status, data = get("http://127.0.0.1:8877/assets/corvi-crow-poses.png")
        assert status == 200 and data.startswith(b"\x89PNG")
        store.add_artifact(task["id"], "source", "Test source", "https://example.com/source")
        store.add_artifact(task["id"], "file", "Generated file", "sample.py")
        status, raw = get("http://127.0.0.1:8877/api/panels?task_id=" + urllib.parse.quote(task["id"]))
        panels = json.loads(raw)
        assert status == 200 and panels["sources"][0]["path_or_url"] == "https://example.com/source" and panels["outputs"][0]["title"] == "Generated file"
        status, raw = get("http://127.0.0.1:8877/api/tasks/" + urllib.parse.quote(task["id"]))
        restored = json.loads(raw)
        assert status == 200 and "activities" in restored and "messages" in restored
        print("F01 shell/models: PASS")
        print("F02 recent tasks endpoint: PASS")
        print("F03 review approval and diff endpoint: PASS")
        print("F05 pet asset endpoint: PASS")
        print("F06 panels and task restoration: PASS")
    finally:
        proc.terminate(); proc.wait(timeout=5)


if __name__ == "__main__": main()
