import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TEMPLATE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TEMPLATE / "project_ops"))
import ledger
import memory


class Ctl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project"
        shutil.copytree(TEMPLATE, self.root, ignore=shutil.ignore_patterns("state.json", "logs", ".local", "__pycache__"))
        self.store = ledger.Store(self.root)
        self.ctl("init", "--name", "Fixture", "--goal", "Test memory")
        (self.root / "ev.txt").write_text("supported result")

    def tearDown(self):
        self.tmp.cleanup()

    def ctl(self, *args, payload=None, code=0):
        result = subprocess.run([sys.executable, str(self.root / "project_ops/projectctl.py"), *args], input=json.dumps(payload) if payload else None, capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def add_task(self, rid="T1", *extra):
        return self.ctl("task", "add", rid, "Test task", "--acceptance", "Expected output exists", *extra)

    def test_done_evidence_dependencies_acceptance(self):
        self.ctl("task", "add", "EMPTY", "No criterion", code=1)
        self.add_task("A")
        self.add_task("B", "--depends", "A")
        self.ctl("task", "set", "A", "done", code=1)
        self.ctl("task", "set", "B", "done", "--evidence", "ev.txt", code=1)
        self.ctl("task", "set", "A", "done", "--evidence", "ev.txt")
        self.ctl("task", "set", "B", "done", "--evidence", "ev.txt")
        self.ctl("verify")
        state = self.store.load()
        state["tasks"][0]["evidence"] = []
        self.assertTrue(ledger.validate(state))

    def test_cycle_and_bad_schema(self):
        self.ctl("task", "add", "SELF", "cycle", "--depends", "SELF", "--acceptance", "x", code=1)
        self.add_task("A")
        self.add_task("B", "--depends", "A")
        state = self.store.load()
        state["tasks"][0]["depends_on"] = ["B"]
        self.assertIn("cycle", ledger.validate(state)[0])
        state["schema_version"] = 99
        self.assertTrue(ledger.validate(state))

    def test_verified_revision_needs_new_evidence(self):
        self.ctl("claim", "C", "verified", "--text", "result", code=1)
        self.ctl("claim", "C", "verified", "--text", "result", "--scope", "dataset A", "--evidence", "ev.txt")
        self.ctl("claim", "C", "verified", "--text", "different result", code=1)
        self.ctl("claim", "C", "reported", "--text", "different result")
        rec = json.loads(self.ctl("show", "C").stdout)
        self.assertEqual(rec["evidence"], [])
        self.assertEqual(rec["revision"], 2)
        self.ctl("claim", "C", "verified", "--scope", "dataset A", "--evidence", "ev.txt")
        (self.root / "ev.txt").write_text("changed")
        self.ctl("claim", "C", "verified", code=1)

    def test_structured_numeric_claims(self):
        self.ctl("claim", "C", "reported", "--text", "accuracy", "--metric", "accuracy", code=1)
        self.ctl("claim", "C", "reported", "--text", "accuracy", "--metric", "accuracy", "--value", "0.5", "--denominator", "10", "--unit", "fraction", "--protocol", "protocol.md")
        self.ctl("verify")

    def test_evidence_all_active_groups_and_strict_exit(self):
        self.ctl("note", "--id", "N", "--summary", "observation", "--evidence", "ev.txt")
        self.ctl("handoff", "--summary", "done", "--next", "review", "--evidence", "ev.txt")
        (self.root / "ev.txt").write_text("changed")
        result = json.loads(self.ctl("verify", "--json", code=2).stdout)
        self.assertEqual({r["id"] for r in result["drift"]}, {"N", "HANDOFF"})
        self.assertEqual(result["freshness"], "stale")
        self.ctl("verify", "--warn-only")
        self.ctl("verify", "--mode", "quick", code=3)

    def test_hash_dedup_and_external_symlink(self):
        state = self.store.load()
        ref = self.store.evidence(["ev.txt"])[0]
        state["notes"] = [ledger.revised({"id": f"N{i}", "text": "x", "evidence": [ref]}) for i in range(100)]
        with mock.patch.object(ledger, "file_hash", wraps=ledger.file_hash) as hasher:
            self.assertEqual(self.store.drift(state), [])
            self.assertEqual(hasher.call_count, 1)
        outside = self.root.parent / "outside.txt"
        outside.write_text("outside")
        (self.root / "link").symlink_to(outside)
        self.ctl("note", "--summary", "x", "--evidence", "link", code=1)

    def test_secret_fields_rejected(self):
        for cmd in [("note", "--summary", "password=dummy"), ("remember", "M", "api_key=dummy")]:
            self.ctl(*cmd, code=1)
        other = ledger.Store(self.root.parent / "other")
        with other.locked(), self.assertRaises(ValueError):
            other.init("Fixture", "password=dummy")
        self.assertFalse(other.state_path.exists())
        self.assertFalse(other.journal.exists())

    def test_empty_and_truncated_journal_rejected(self):
        original = self.store.journal.read_bytes()
        self.store.journal.write_bytes(b"")
        self.ctl("verify", code=1)
        self.ctl("status", code=1)
        self.store.journal.write_bytes(original[:-1])
        self.ctl("verify", code=1)
        self.ctl("recover", code=1)

    def test_untrusted_export_never_injected(self):
        state = ledger.read_json(self.store.state_path)
        state["handoff"]["next_action"] = "CORRUPTED_NEXT_ACTION"
        ledger.atomic_json(self.store.state_path, state)
        self.ctl("status", code=1)
        result = self.ctl("hook", "SessionStart", payload={"session_id": "s"})
        self.assertNotIn("CORRUPTED_NEXT_ACTION", result.stdout)
        self.assertIn("integrity error", result.stdout)
        self.ctl("recover")
        self.ctl("verify")
        self.assertEqual(len(list((self.store.ops / "logs/recovery").glob("*"))), 1)

    def test_replay_and_crash_after_event(self):
        old = self.store.load()
        state = copy.deepcopy(old)
        state["notes"].append(ledger.revised({"id": "N", "text": "recoverable"}))
        original = ledger.atomic_json
        def interrupt(path, value):
            if path == self.store.state_path:
                raise OSError("simulated crash")
            return original(path, value)
        with self.store.locked(), mock.patch.object(ledger, "atomic_json", side_effect=interrupt):
            with self.assertRaises(OSError):
                self.store.commit(state, old, "note", "fixture")
        self.ctl("status", code=1)
        self.ctl("recover")
        actual = self.store.load(full=True)
        self.assertEqual(ledger.digest(actual), ledger.digest(state))
        self.assertEqual(actual["notes"][0]["text"], "recoverable")

    def test_operation_id_and_revision_guard(self):
        self.ctl("--operation-id", "op1", "note", "--id", "N", "--summary", "hello")
        version = self.store.load()["version"]
        self.ctl("--operation-id", "op1", "note", "--id", "N", "--summary", "hello")
        self.assertEqual(self.store.load()["version"], version)
        self.ctl("--operation-id", "op1", "note", "--id", "N", "--summary", "different", code=1)
        self.ctl("archive", "N", "--reason", "done", "--expect-revision", "9", code=1)
        self.ctl("archive", "N", "--reason", "done", "--expect-revision", "1")

    def test_search_history_temporal_and_lifecycle(self):
        self.ctl("remember", "M", "baseline calibration dataset", "--scope", "project A", "--valid-from", "2026-01-01", "--valid-to", "2026-06-01")
        cutoff = self.store.load()["updated_at"]
        self.ctl("remember", "M", "replacement measurement", "--scope", "project A")
        self.assertEqual(len(json.loads(self.ctl("history", "M").stdout)["items"]), 2)
        historical = json.loads(self.ctl("search", "calibration", "--as-of", cutoff).stdout)["items"]
        self.assertEqual(historical[0]["revision"], 1)
        self.assertEqual(json.loads(self.ctl("search", "replacement", "--scope", "other").stdout)["items"], [])
        self.assertEqual(json.loads(self.ctl("search", "replacement", "--valid-at", "2026-07-01").stdout)["items"], [])
        self.ctl("archive", "M", "--reason", "old")
        self.assertEqual(json.loads(self.ctl("search", "replacement").stdout)["items"], [])
        self.ctl("restore", "M", "--reason", "needed")
        self.assertEqual(len(json.loads(self.ctl("search", "replacement").stdout)["items"]), 1)
        self.ctl("forget", "M", "--reason", "remove from retrieval")
        self.assertEqual(json.loads(self.ctl("search", "replacement", "--include-archived").stdout)["items"], [])
        self.assertEqual(json.loads(self.ctl("search", "calibration", "--as-of", cutoff).stdout)["items"], [])
        self.ctl("index", "rebuild")
        self.assertEqual(json.loads(self.ctl("search", "replacement").stdout)["items"], [])

    def test_search_query_syntax_and_no_fts_fallback(self):
        self.ctl("note", "--id", "N", "--summary", "alpha identifier")
        self.ctl("search", 'alpha OR " DROP TABLE records; --')
        index = memory.Index(self.store)
        try:
            state = self.store.load()
            index.sync(state)
            index.fts = False
            self.assertEqual(index.search("identifier")[0]["id"], "N")
        finally:
            index.close()

    def test_context_budget_unicode_and_constraints(self):
        state = self.store.load()
        state["tasks"] = [ledger.revised({"id": f"T{i}", "title": "Blocked", "note": "測定" * 40, "status": "blocked", "depends_on": [], "acceptance": "x"}) for i in range(10000)]
        for size in (512, 1200, 4800):
            packet = memory.packet(self.store, state, budget=size)
            self.assertLessEqual(len(packet.encode()), size)
            self.assertIn("Omitted", packet)
        state["memories"] = [ledger.revised({"id": "CONSTRAINT", "kind": "constraint", "text": "constraint " * 300})]
        packet = memory.packet(self.store, state, budget=1200)
        self.assertIn("REQUIRED CONTEXT DOES NOT FIT", packet)
        self.assertIn("CONSTRAINT", packet)

    def test_related_conflicting_evidence_in_context(self):
        self.ctl("claim", "C1", "reported", "--text", "alpha supports")
        self.ctl("claim", "C2", "disputed", "--text", "alpha contradicts", "--link", "contradicts:C1")
        result = self.ctl("context", "--query", "C2", "--check-evidence").stdout
        self.assertIn("C1", result)
        self.assertIn("C2", result)
        self.assertIn("disputed", result)

    def test_cli_byte_budgets_and_oversized_show(self):
        self.ctl("status", "--max-bytes", "0", code=1)
        self.ctl("remember", "M", "測定" * 1000)
        for size in (512, 1200, 4800):
            result = self.ctl("context", "--query", "M", "--max-bytes", str(size))
            self.assertLessEqual(len(result.stdout.encode("utf-8")), size)
        old = self.store.load()
        state = copy.deepcopy(old)
        state["memories"][0]["links"] = [{"relation": "related_to", "id": "HANDOFF"}] * 200
        ledger.revised(state["memories"][0], old["memories"][0])
        with self.store.locked():
            self.store.commit(state, old, "fixture", "Large record")
        self.ctl("show", "M", code=3)
        self.assertGreater(len(self.ctl("show", "M", "--full").stdout.encode("utf-8")), 16000)

    def test_required_handoff_not_clipped_inside_optional_bundle(self):
        state = self.store.load()
        state["handoff"]["summary"] = "required handoff " * 100
        state["tasks"] = [
            ledger.revised({"id": "T", "title": "Work", "status": "todo", "depends_on": ["D"], "acceptance": "x"}),
            ledger.revised({"id": "D", "title": "Dependency", "status": "todo", "depends_on": [], "acceptance": "x", "links": [{"relation": "related_to", "id": "T"}, {"relation": "supported_by", "id": "HANDOFF"}]}),
        ]
        result = memory.packet(self.store, state, budget=1400, task="T")
        self.assertIn("REQUIRED CONTEXT DOES NOT FIT", result)
        self.assertIn("HANDOFF", result)

    def test_stop_acknowledges_retry_then_catches_next_turn(self):
        p = {"session_id": "s"}
        self.ctl("hook", "SessionStart", payload=p)
        self.assertEqual(self.ctl("hook", "Stop", payload=p).stdout, "")
        (self.root / "work.py").write_text("first")
        self.assertEqual(json.loads(self.ctl("hook", "Stop", payload=p).stdout)["decision"], "block")
        self.ctl("handoff", "--summary", "first", "--next", "continue", "--session-id", "s")
        self.ctl("hook", "Stop", payload={**p, "stop_hook_active": True})
        (self.root / "work.py").write_text("second")
        self.assertEqual(json.loads(self.ctl("hook", "Stop", payload=p).stdout)["decision"], "block")
        self.ctl("hook", "Stop", payload={**p, "stop_hook_active": True})

    def test_resume_compact_and_other_session_handoff(self):
        p = {"session_id": "s"}
        self.ctl("hook", "SessionStart", payload=p)
        self.ctl("note", "--summary", "ledger-only progress")
        self.ctl("hook", "SessionStart", payload={**p, "source": "resume"})
        self.assertIn('"block"', self.ctl("hook", "Stop", payload=p).stdout)
        self.ctl("handoff", "--summary", "other session", "--next", "go", "--session-id", "other")
        self.assertIn('"block"', self.ctl("hook", "Stop", payload=p).stdout)
        self.ctl("hook", "PreCompact", payload=p)
        self.ctl("hook", "SessionStart", payload={**p, "source": "compact"})
        self.ctl("hook", "SessionEnd", payload=p)
        self.assertTrue((self.store.local / "last_session.json").exists())

    def test_fingerprint_large_files_logs_and_no_external_content(self):
        (self.root / "logs").mkdir()
        large = self.root / "logs/large.bin"
        large.write_bytes(b"a" * (1 << 20))
        before = memory.fingerprint(self.store)
        large.write_bytes(b"b" * (1 << 20))
        self.assertNotEqual(memory.fingerprint(self.store)["digest"], before["digest"])
        outside = self.root.parent / "outside.txt"
        outside.write_text("first")
        (self.root / "external").symlink_to(outside)
        before = memory.fingerprint(self.store)
        outside.write_text("second")
        self.assertEqual(memory.fingerprint(self.store)["digest"], before["digest"])
        self.assertFalse(memory.fingerprint(self.store, max_files=1)["complete"])

    def test_concurrent_writes_serialized(self):
        procs = [subprocess.Popen([sys.executable, str(self.root / "project_ops/projectctl.py"), "note", "--id", f"N{i}", "--summary", f"parallel {i}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(6)]
        for proc in procs:
            out, err = proc.communicate(timeout=20)
            self.assertEqual(proc.returncode, 0, out + err)
        state = self.store.load(full=True)
        self.assertEqual(len(state["notes"]), 6)
        self.assertEqual(state["version"], 7)

    def test_store_rejects_unreplayable_deletion_and_stale_base(self):
        self.add_task()
        old = self.store.load()
        state = copy.deepcopy(old)
        state["tasks"] = []
        size = self.store.journal.stat().st_size
        with self.store.locked(), self.assertRaises(ValueError):
            self.store.commit(state, old, "delete", "invalid")
        self.assertEqual(self.store.journal.stat().st_size, size)
        self.ctl("note", "--summary", "new state")
        state = copy.deepcopy(old)
        state["notes"].append(ledger.revised({"id": "N", "text": "stale"}))
        with self.store.locked(), self.assertRaises(ValueError):
            self.store.commit(state, old, "note", "stale")

    def test_checkpoint_corruption_detected(self):
        path = next(self.store.checkpoints.glob("*.json"))
        value = json.loads(path.read_text())
        value["state"]["project"]["goal"] = "changed checkpoint"
        ledger.atomic_json(path, value)
        self.ctl("verify", code=1)
        # Context does not use checkpoints as its authority.
        self.ctl("status")

    def test_index_cannot_override_record_content(self):
        self.ctl("note", "--id", "N", "--summary", "original alpha")
        self.ctl("search", "alpha")
        import sqlite3
        with sqlite3.connect(self.store.local / "index.sqlite") as db:
            rec = json.loads(self.ctl("show", "N").stdout)
            rec["text"] = "injected content"
            db.execute("UPDATE records SET payload=? WHERE id='N'", (json.dumps(rec),))
        result = self.ctl("search", "alpha").stdout
        self.assertIn("original alpha", result)
        self.assertNotIn("injected content", result)

    def test_constraints_require_user_attribution(self):
        self.ctl("remember", "RULE", "Use dataset A", "--kind", "constraint", "--source", "external", code=1)
        self.ctl("remember", "RULE", "Use dataset A", "--kind", "constraint", "--source", "user")
        self.assertIn("Use dataset A", self.ctl("status").stdout)

    def test_numeric_nan_rejected(self):
        self.ctl("claim", "C", "reported", "--text", "x", "--metric", "accuracy", "--value", "nan", "--denominator", "10", "--unit", "fraction", "--protocol", "p", code=1)

    def test_no_whole_state_snapshot_per_write(self):
        for i in range(5):
            self.ctl("note", "--summary", f"observation {i}")
        self.assertEqual(len(list(self.store.checkpoints.glob("*.json"))), 1)
        self.assertFalse((self.store.ops / "logs/snapshots").exists())
        rows = list(self.store.events())
        self.assertNotIn("initial", rows[-1])
        self.assertEqual(len(rows[-1]["changes"]), 1)
        self.ctl("checkpoint")
        self.assertEqual(len(list(self.store.checkpoints.glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
