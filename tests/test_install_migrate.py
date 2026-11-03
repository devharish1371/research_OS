import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "template/project_ops"))
from ledger import Store, atomic_json, digest


class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project with spaces"

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, *args, code=0):
        p = subprocess.run([sys.executable, str(REPO / "install.py"), str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        return p

    def ctl(self, *args, code=0):
        p = subprocess.run([sys.executable, str(self.root / "project_ops/projectctl.py"), *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        return p

    def v1(self):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "ev.txt").write_text("evidence")
        store = Store(self.root)
        from ledger import file_hash
        ref = {"path": "ev.txt", "sha256": file_hash(self.root / "ev.txt")}
        state = {"schema_version": 1, "updated_at": "2026-01-01T00:00:00+00:00", "project": {"name": "Legacy", "goal": "Preserve history"}, "tasks": [{"id": "T1", "title": "Old task", "status": "done", "acceptance": "", "depends_on": [], "evidence": [ref]}], "claims": [], "decisions": [], "handoff": {"summary": "legacy", "next_action": "review", "at": "2026-01-01T00:00:00+00:00"}}
        rows, previous = [], "0" * 64
        for i, kind in enumerate(("init", "note", "handoff")):
            row = {"id": str(i), "at": state["updated_at"], "kind": kind, "summary": "legacy observation" if kind == "note" else "legacy", "evidence": [ref] if kind != "init" else [], "previous": previous, "state_sha256": digest(state)}
            row["hash"] = digest(row)
            previous = row["hash"]
            rows.append(row)
        atomic_json(store.state_path, state)
        store.journal.parent.mkdir(parents=True, exist_ok=True)
        store.journal.write_text("".join(json.dumps(r) + "\n" for r in rows))
        atomic_json(store.ops / "logs/snapshots" / (digest(state) + ".json"), state)
        return store.state_path.read_bytes(), store.journal.read_bytes()

    def test_fresh_install_repeat_and_dry_run(self):
        self.install("--dry-run")
        self.assertFalse(self.root.exists())
        self.install("--name", "Named project", "--goal", "Named goal")
        self.ctl("doctor")
        self.ctl("verify")
        before = (self.root / "CLAUDE.md").read_bytes()
        self.install()
        self.assertEqual((self.root / "CLAUDE.md").read_bytes(), before)
        settings = json.loads((self.root / ".claude/settings.json").read_text())
        self.assertEqual(len(settings["hooks"]["Stop"]), 1)
        self.assertEqual(len(settings["hooks"]), 4)

    def test_merge_settings_preserve_contract(self):
        (self.root / ".claude").mkdir(parents=True)
        original = {"env": {"KEEP": "yes"}, "permissions": {"allow": ["Read"]}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo existing"}]}]}}
        atomic_json(self.root / ".claude/settings.json", original)
        (self.root / "CLAUDE.md").write_text("My custom contract")
        self.install("--force")
        installed = json.loads((self.root / ".claude/settings.json").read_text())
        self.assertEqual(installed["env"], original["env"])
        self.assertEqual(installed["permissions"], original["permissions"])
        self.assertEqual(len(installed["hooks"]["Stop"]), 2)
        self.assertEqual((self.root / "CLAUDE.md").read_text(), "My custom contract")
        self.assertTrue((self.root / "CLAUDE.research_OS.md").exists())
        self.install()
        self.assertEqual(len(json.loads((self.root / ".claude/settings.json").read_text())["hooks"]["Stop"]), 2)

    def test_runtime_conflict_backup_and_preflight(self):
        self.install()
        runtime = self.root / "project_ops/memory.py"
        runtime.write_text("# custom code\n")
        self.install(code=1)
        self.assertEqual(runtime.read_text(), "# custom code\n")
        self.install("--force")
        backups = list((self.root / "project_ops/.local/install-backups").glob("*/project_ops/memory.py"))
        self.assertTrue(any(p.read_text() == "# custom code\n" for p in backups))

    def test_invalid_settings_no_partial_install(self):
        (self.root / ".claude").mkdir(parents=True)
        (self.root / ".claude/settings.json").write_text("not json")
        self.install(code=1)
        self.assertFalse((self.root / "projectctl").exists())

    def test_symlink_metadata_refused_before_write(self):
        self.root.mkdir()
        outside = self.root.parent / "outside"
        outside.write_text("leave alone")
        (self.root / ".gitignore").symlink_to(outside)
        self.install(code=1)
        self.assertEqual(outside.read_text(), "leave alone")
        self.assertFalse((self.root / "projectctl").exists())

    def test_v1_migration_preserves_history_and_recovers_refs(self):
        original_state, original_journal = self.v1()
        self.install()
        self.ctl("status", code=1)
        report = json.loads(self.ctl("migrate", "--dry-run").stdout)
        self.assertEqual((self.root / "project_ops/state.json").read_bytes(), original_state)
        self.assertFalse(Path(report["backup"]).exists())
        self.ctl("migrate")
        backup = Path(report["backup"])
        self.assertEqual((backup / "state.json").read_bytes(), original_state)
        self.assertEqual((backup / "events.jsonl").read_bytes(), original_journal)
        state = Store(self.root).load(full=True)
        self.assertEqual(state["schema_version"], 2)
        self.assertTrue(state["tasks"][0]["review_required"])
        self.assertEqual(len(state["handoff"]["evidence"]), 1)
        self.assertEqual(len(state["notes"]), 1)
        self.assertEqual(json.loads(self.ctl("search", "observation").stdout)["items"][0]["text"], "legacy observation")
        self.ctl("verify")
        (self.root / "ev.txt").write_text("changed")
        self.ctl("verify", code=2)

    def test_migration_refuses_corruption(self):
        self.v1()
        self.install()
        (self.root / "project_ops/logs/events.jsonl").write_text("")
        self.ctl("migrate", code=1)
        self.assertEqual(json.loads((self.root / "project_ops/state.json").read_text())["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
