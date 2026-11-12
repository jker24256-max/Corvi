import tempfile
import unittest
from pathlib import Path

from corvi_ext import load_plugin_hooks, load_skills
from corvi_state import StateStore
from opencode_compat import PermissionSet, load_markdown_commands


class CompatibilityTests(unittest.TestCase):
    def test_permission_aliases_and_specificity(self):
        rules = PermissionSet({"*": "ask", "read": "allow", "edit": "deny"})
        self.assertEqual(rules.resolve("read_file"), "allow")
        self.assertEqual(rules.resolve("edit_file"), "deny")

    def test_project_extensions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".opencode/commands").mkdir(parents=True)
            (root / ".opencode/skills/demo").mkdir(parents=True)
            (root / ".opencode/plugins").mkdir(parents=True)
            (root / ".opencode/plugins/demo.py").write_text("def on_event(event, payload):\n    return None\n")
            (root / ".opencode/commands/review.md").write_text("Review the project")
            (root / ".opencode/skills/demo/SKILL.md").write_text("Use focused checks")
            self.assertEqual(load_markdown_commands(root)["review"], "Review the project")
            self.assertEqual(load_skills(root)[0].name, "demo")
            self.assertEqual(len(load_plugin_hooks(root)), 1)

    def test_session_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = StateStore(root)
            store.save_session("demo", [{"role": "user", "content": "hi"}], "llama3.2:3b")
            data = store.load_session("demo")
            self.assertEqual(data["model"], "llama3.2:3b")
            self.assertEqual(data["messages"][0]["content"], "hi")
            store.fork_session("demo", "branch")
            self.assertIn("branch", store.list_sessions())

    def test_snapshot_and_undo(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "note.txt"
            target.write_text("before")
            store = StateStore(root)
            store.snapshot(root)
            target.write_text("after")
            restored = store.undo(root)
            self.assertIsNotNone(restored)
            self.assertEqual(target.read_text(), "before")


if __name__ == "__main__":
    unittest.main()
