import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2]


class Ctl(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(TEMPLATE, self.tmp / "p", ignore=shutil.ignore_patterns("state.json", "logs", ".local", "__pycache__"))
        self.root = self.tmp / "p"
        self.run_ctl("init", "--name", "T", "--goal", "g")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_ctl(self, *args, stdin=None, ok=True):
        r = subprocess.run([sys.executable, str(self.root / "project_ops/projectctl.py"), *args], input=stdin, capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_done_requires_evidence_and_dependencies(self):
        self.run_ctl("task", "add", "A", "first")
        self.run_ctl("task", "add", "B", "second", "--depends", "A")
        (self.root / "ev.txt").write_text("x")
        self.assertNotEqual(self.run_ctl("task", "set", "A", "done", ok=False).returncode, 0)
        self.assertNotEqual(self.run_ctl("task", "set", "B", "done", "--evidence", "ev.txt", ok=False).returncode, 0)
        self.run_ctl("task", "set", "A", "done", "--evidence", "ev.txt")
        self.run_ctl("task", "set", "B", "done", "--evidence", "ev.txt")
        self.run_ctl("verify")

    def test_verified_claim_needs_evidence(self):
        self.assertNotEqual(self.run_ctl("claim", "C1", "verified", "--text", "t", ok=False).returncode, 0)
        self.run_ctl("claim", "C1", "hypothesis", "--text", "t")

    def test_secret_rejected(self):
        self.assertNotEqual(self.run_ctl("note", "--summary", "password=hunter2", ok=False).returncode, 0)

    def test_direct_edit_detected(self):
        p = self.root / "project_ops/state.json"
        s = json.loads(p.read_text()); s["handoff"]["summary"] = "tampered"; p.write_text(json.dumps(s))
        self.assertNotEqual(self.run_ctl("verify", ok=False).returncode, 0)

    def test_evidence_drift_reported(self):
        (self.root / "ev.txt").write_text("one")
        self.run_ctl("handoff", "--summary", "s", "--next", "n", "--evidence", "ev.txt")
        self.run_ctl("task", "add", "A", "t")
        self.run_ctl("claim", "C", "reported", "--text", "t", "--evidence", "ev.txt")
        (self.root / "ev.txt").write_text("two")
        self.assertIn("DRIFT", self.run_ctl("verify").stdout)

    def test_hooks(self):
        out = self.run_ctl("hook", "SessionStart", stdin=json.dumps({"session_id": "s1"})).stdout
        self.assertIn("Last activity", json.loads(out)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.run_ctl("hook", "Stop", stdin=json.dumps({"session_id": "s1"})).stdout.strip(), "")
        (self.root / "work.py").write_text("print(1)")
        blocked = json.loads(self.run_ctl("hook", "Stop", stdin=json.dumps({"session_id": "s1"})).stdout)
        self.assertEqual(blocked["decision"], "block")
        self.assertEqual(self.run_ctl("hook", "Stop", stdin=json.dumps({"session_id": "s1", "stop_hook_active": True})).stdout.strip(), "")
        self.run_ctl("handoff", "--summary", "did work", "--next", "next")
        self.assertEqual(self.run_ctl("hook", "Stop", stdin=json.dumps({"session_id": "s1"})).stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
