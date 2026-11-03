#!/usr/bin/env python3
"""Reproduce baseline observations in disposable projects, with no network or LLM.

Run from the repository: python3 research/audit_baseline.py
Outputs research/baseline_results.json. Does not edit the shipped template.
"""
import contextlib
import copy
import datetime
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc

REPO = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "09951bf9d4acdc4def9332d6b7ec86736c21b9b3"
BASELINE_SOURCE = subprocess.check_output(["git", "show", BASELINE_COMMIT + ":template/project_ops/projectctl.py"], cwd=REPO, text=True)


@contextlib.contextmanager
def project():
    with tempfile.TemporaryDirectory(prefix="research-os-audit-") as d:
        root = Path(d) / "project"
        (root / "project_ops").mkdir(parents=True)
        (root / "project_ops/projectctl.py").write_text(BASELINE_SOURCE)
        def ctl(*args, payload=None):
            return subprocess.run([sys.executable, str(root / "project_ops/projectctl.py"), *args],
                                  input=json.dumps(payload) if payload else None,
                                  capture_output=True, text=True, check=False)
        result = ctl("init", "--name", "Audit fixture", "--goal", "Synthetic audit")
        assert result.returncode == 0, result.stderr
        yield root, ctl


def module(root):
    spec = importlib.util.spec_from_file_location("audited_projectctl", root / "project_ops/projectctl.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def record(proc):
    return {"exit_code": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()}


def timed(fn, repeats=7):
    samples = []
    value = None
    for _ in range(repeats):
        start = time.perf_counter()
        value = fn()
        samples.append((time.perf_counter() - start) * 1000)
    return {"median_ms": round(statistics.median(samples), 3), "samples_ms": [round(t, 3) for t in samples]}, value


def main():
    result = {"measured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "commit": BASELINE_COMMIT,
              "python": sys.version, "platform": platform.platform(),
              "method": "Synthetic temporary projects; function timings are warm in-process; CLI observations use subprocesses. No model quality, API token usage or cold disk latency measured.",
              "observations": {}, "benchmarks": {}}
    obs = result["observations"]
    with project() as (root, ctl):
        ev = root / "evidence.txt"
        ev.write_text("original evidence")
        assert ctl("handoff", "--summary", "Recorded evidence", "--next", "Review", "--evidence", "evidence.txt").returncode == 0
        ev.write_text("changed evidence")
        obs["handoff_evidence_drift_ignored"] = record(ctl("verify"))
        assert ctl("claim", "C1", "verified", "--text", "Original claim", "--evidence", "evidence.txt").returncode == 0
        ev.write_text("changed again")
        obs["claim_drift_exits_zero"] = record(ctl("verify"))
        obs["changed_verified_claim_reuses_old_evidence"] = record(ctl("claim", "C1", "verified", "--text", "Entirely different assertion"))
        obs["self_dependency_accepted"] = record(ctl("task", "add", "SELF", "Cannot become ready", "--depends", "SELF"))
        assert ctl("task", "add", "EMPTY", "No acceptance criterion").returncode == 0
        obs["done_with_empty_acceptance"] = record(ctl("task", "set", "EMPTY", "done", "--evidence", "evidence.txt"))
    with project() as (root, ctl):
        (root / "project_ops/logs/events.jsonl").write_text("")
        obs["empty_journal_passes_verify"] = record(ctl("verify"))
    with project() as (root, ctl):
        state_path = root / "project_ops/state.json"
        state = json.loads(state_path.read_text())
        state["handoff"]["next_action"] = "DIRECTLY EDITED CONTENT"
        state_path.write_text(json.dumps(state))
        obs["status_serves_unverified_state"] = record(ctl("status"))
        obs["verify_catches_same_state_edit"] = record(ctl("verify"))
    with project() as (root, ctl):
        p = {"session_id": "audit"}
        assert ctl("hook", "SessionStart", payload=p).returncode == 0
        (root / "work.txt").write_text("first change")
        first = ctl("hook", "Stop", payload=p)
        assert ctl("handoff", "--summary", "First change recorded", "--next", "Continue").returncode == 0
        ctl("hook", "Stop", payload={**p, "stop_hook_active": True})
        (root / "work.txt").write_text("second change without another handoff")
        obs["second_turn_after_block_misses_handoff"] = {"first_stop": record(first), "second_stop": record(ctl("hook", "Stop", payload=p))}
    with project() as (root, ctl):
        mod = module(root)
        large = root / "large.bin"
        large.write_bytes(b"a" * (1 << 20))
        before = mod.fingerprint()
        large.write_bytes(b"b" * (1 << 20))
        obs["one_mib_edit_missed"] = mod.fingerprint() == before
        external = root.parent / "outside.txt"
        external.write_text("synthetic external fixture")
        (root / "external-link").symlink_to(external)
        before = mod.fingerprint()
        external.write_text("external fixture changed")
        obs["fingerprint_reads_external_file_symlink"] = mod.fingerprint() != before
        s = mod.load()
        s["tasks"] = [{"id": "X", "status": "done", "title": "x", "depends_on": []}]
        obs["validator_accepts_done_without_evidence"] = mod.validate(s)
        ev = root / "shared.txt"
        ev.write_text("shared evidence")
        ref = {"path": "shared.txt", "sha256": mod.file_hash(ev)}
        s["tasks"] = []
        s["claims"] = [{"id": str(i), "status": "reported", "text": "x", "evidence": [ref]} for i in range(100)]
        calls = []
        original = mod.file_hash
        def counting(path):
            calls.append(str(path))
            return original(path)
        mod.file_hash = counting
        mod.evidence_drift(s)
        obs["hash_calls_for_100_refs_to_one_file"] = len(calls)
    with project() as (root, ctl):
        mod = module(root)
        base = mod.load()
        rows = []
        for n in (10, 100, 1000, 10000):
            s = copy.deepcopy(base)
            s["tasks"] = [{"id": f"T{i}", "title": "Blocked experiment", "status": "blocked", "note": "x" * 80, "depends_on": []} for i in range(n)]
            timing, output = timed(lambda: mod.status_text(s))
            rows.append({"blocked_tasks": n, "characters": len(output), "utf8_bytes": len(output.encode()),
                         "rough_tokens_chars_div_4_not_tokenized": round(len(output) / 4), **timing})
        result["benchmarks"]["status_growth"] = rows
        validation = []
        for n in (100, 1000, 5000):
            s = copy.deepcopy(base)
            s["tasks"] = [{"id": f"T{i}", "title": "Task", "status": "todo", "depends_on": [f"T{i-1}"] if i else []} for i in range(n)]
            timing, errors = timed(lambda: mod.validate(s), repeats=3)
            assert not errors
            validation.append({"tasks": n, **timing})
        result["benchmarks"]["dependency_validation"] = validation
    with project() as (root, ctl):
        mod = module(root)
        s = mod.load()
        rows = []
        for i in range(1, 201):
            s["tasks"].append({"id": f"T{i}", "title": "Synthetic task " + "x" * 100, "status": "todo", "depends_on": [], "acceptance": "Check fixture"})
            start = time.perf_counter()
            with mod.locked():
                mod.commit(s, "task_add", f"Synthetic task T{i}")
            elapsed = (time.perf_counter() - start) * 1000
            if i in (25, 50, 100, 200):
                snaps = list(mod.SNAPSHOTS.glob("*.json"))
                rows.append({"tasks": i, "state_bytes": mod.STATE.stat().st_size, "snapshot_count": len(snaps),
                             "snapshot_bytes": sum(p.stat().st_size for p in snaps), "journal_bytes": mod.JOURNAL.stat().st_size,
                             "single_commit_ms_not_distribution": round(elapsed, 3)})
        result["benchmarks"]["snapshot_growth"] = rows
    with project() as (root, ctl):
        mod = module(root)
        s = mod.load()
        rows = []
        for n in (1000, 10000):
            previous = "0" * 64
            with mod.JOURNAL.open("w") as stream:
                for i in range(n):
                    event = {"id": str(i), "at": "2026-11-03T00:00:00Z", "kind": "note",
                             "summary": "Synthetic journal allocation fixture", "evidence": [],
                             "previous": previous, "state_sha256": mod.digest(s)}
                    event["hash"] = mod.digest(event)
                    previous = event["hash"]
                    stream.write(json.dumps(event) + "\n")
            # One instrumented measurement: allocation tracing changes timing.
            tracemalloc.start()
            start = time.perf_counter()
            errors = mod.journal_errors(s)
            elapsed = (time.perf_counter() - start) * 1000
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            assert not errors
            rows.append({"events": n, "journal_bytes": mod.JOURNAL.stat().st_size,
                         "peak_traced_python_allocation_bytes_not_rss": peak,
                         "single_instrumented_ms": round(elapsed, 3)})
        result["benchmarks"]["journal_python_allocation"] = rows
    target = REPO / "research/baseline_results.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
