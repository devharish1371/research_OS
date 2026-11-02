#!/usr/bin/env python3
"""Dependency-free project ledger for Claude Code sessions (Python >=3.9).

One canonical state file, an append-only hash-chained journal, a SessionStart greeting
and a Stop reminder to record a handoff. No network, no transcripts, no credentials.
Hashes detect accidental edits and establish file identity; they do not prove a claim.
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

OPS = Path(__file__).resolve().parent
ROOT = OPS.parent
STATE = OPS / "state.json"
JOURNAL = OPS / "logs/events.jsonl"
SNAPSHOTS = OPS / "logs/snapshots"
LOCAL = OPS / ".local"
TASK_STATUS = {"todo", "in_progress", "blocked", "done", "deferred"}
CLAIM_STATUS = {"verified", "reported", "hypothesis", "proposed", "disputed", "unknown", "withdrawn"}
DECISION_SOURCES = {"user", "assistant_proposal", "external"}
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", ".local", "logs", "dist", "build", ".next"}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def check_text(value):
    """Heuristic guard: never record secrets or essays in the ledger."""
    if re.search(r"(?i)(password|passwd|otp|api.?key|secret|token)\s*[:=]\s*\S+", value) \
            or "PRIVATE KEY-----" in value or re.search(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}", value):
        raise ValueError("Possible credential rejected; never record secrets. Link an artifact instead.")
    if len(value) > 4000:
        raise ValueError("Keep ledger prose under 4,000 characters; link a detailed file.")


def evidence(paths):
    out = []
    for p in paths or []:
        lp = (ROOT / p).resolve()
        if not lp.is_relative_to(ROOT) or not lp.is_file():
            raise ValueError(f"Evidence must be an existing file inside the project: {p}")
        out.append({"path": str(lp.relative_to(ROOT)), "sha256": file_hash(lp)})
    return out


@contextlib.contextmanager
def locked():
    LOCAL.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (LOCAL / "state.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def journal_errors(state):
    if not JOURNAL.exists():
        return [] if not state.get("handoff") else ["journal missing"]
    rows = [json.loads(x) for x in JOURNAL.read_text().splitlines() if x.strip()]
    prev = "0" * 64
    for row in rows:
        body = {k: v for k, v in row.items() if k != "hash"}
        if row.get("previous") != prev or digest(body) != row.get("hash"):
            return [f"journal chain broken at event {row.get('id')}"]
        prev = row["hash"]
    if rows and rows[-1]["state_sha256"] != digest(state):
        return ["state.json differs from the last journal event (edited directly or interrupted write); inspect logs/snapshots"]
    return []


def validate(state):
    errors, ids = [], set()
    for group in ("tasks", "claims", "decisions"):
        for rec in state.get(group, []):
            if rec["id"] in ids:
                errors.append(f"duplicate id {rec['id']}")
            ids.add(rec["id"])
    done = {t["id"] for t in state["tasks"] if t["status"] == "done"}
    for t in state["tasks"]:
        if t["status"] not in TASK_STATUS:
            errors.append(f"{t['id']}: bad status")
        for d in t.get("depends_on", []):
            if d not in {x["id"] for x in state["tasks"]}:
                errors.append(f"{t['id']}: unknown dependency {d}")
        if t["status"] == "done" and not all(d in done for d in t.get("depends_on", [])):
            errors.append(f"{t['id']}: done but dependencies are not done")
    for c in state["claims"]:
        if c["status"] not in CLAIM_STATUS:
            errors.append(f"{c['id']}: bad claim status")
        if c["status"] == "verified" and not c.get("evidence"):
            errors.append(f"{c['id']}: verified claim needs evidence")
    return errors


def commit(state, kind, summary, refs=()):
    """Caller holds the lock. Journal first, then atomic state replace, so interruption is detectable."""
    check_text(summary)
    old = read_json(STATE) if STATE.exists() else None
    if old is not None:
        problems = journal_errors(old)
        if problems:
            raise ValueError("; ".join(problems))
    state["updated_at"] = now()
    problems = validate(state)
    if problems:
        raise ValueError("; ".join(problems))
    if old is not None:
        atomic_json(SNAPSHOTS / (digest(old) + ".json"), old)
    previous = "0" * 64
    if JOURNAL.exists() and JOURNAL.read_text().strip():
        previous = json.loads(JOURNAL.read_text().splitlines()[-1])["hash"]
    row = {"id": str(uuid.uuid4()), "at": now(), "kind": kind, "summary": summary,
           "evidence": list(refs), "previous": previous, "state_sha256": digest(state)}
    row["hash"] = digest(row)
    atomic_json(SNAPSHOTS / (digest(state) + ".json"), state)
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    atomic_json(STATE, state)


def load():
    if not STATE.exists():
        sys.exit("No state yet. Run: ./projectctl init --name NAME --goal 'one sentence'")
    return read_json(STATE)


def find(state, group, rid):
    for rec in state[group]:
        if rec["id"] == rid:
            return rec
    raise ValueError(f"No {group[:-1]} with id {rid}")


def evidence_drift(state):
    drift = []
    for group in ("tasks", "claims", "decisions"):
        for rec in state.get(group, []):
            for ref in rec.get("evidence", []):
                p = ROOT / ref["path"]
                if not p.is_file() or file_hash(p) != ref["sha256"]:
                    drift.append((rec["id"], ref["path"]))
    return drift


def next_tasks(state, limit=4):
    done = {t["id"] for t in state["tasks"] if t["status"] == "done"}
    ready = [t for t in state["tasks"] if t["status"] in {"in_progress", "todo"} and all(d in done for d in t.get("depends_on", []))]
    ready.sort(key=lambda t: t["status"] != "in_progress")
    return ready[:limit]


def status_text(state):
    h = state["handoff"]
    lines = [f"Project: {state['project']['name']} — {state['project']['goal']}",
             f"State saved: {state['updated_at']}", "Last activity: " + h["summary"], "Next: " + h["next_action"]]
    blocked = [t for t in state["tasks"] if t["status"] == "blocked"]
    if blocked:
        lines.append("Blocked: " + "; ".join(f"{t['id']} ({t.get('note', t['title'])[:80]})" for t in blocked))
    drift = evidence_drift(state)
    if drift:
        lines.append(f"EVIDENCE DRIFT ({len(drift)} refs; review before trusting dependent claims): " + "; ".join(sorted({p for _, p in drift})))
    disputed = [c["id"] for c in state["claims"] if c["status"] in {"disputed", "unknown"}]
    if disputed:
        lines.append("Open claims (disputed/unknown): " + ", ".join(disputed))
    lines.extend(f"{t['id']} [{t['status']}]: {t['title']}" for t in next_tasks(state))
    return "\n".join(lines)


def fingerprint():
    """Bounded hash of small project files, to notice work done without a handoff."""
    files = {}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git")]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                if p.stat().st_size < (1 << 20) and p != STATE:
                    files[str(p.relative_to(ROOT))] = file_hash(p)
            except OSError:
                pass
            if len(files) > 5000:
                return digest(files)
    return digest(files)


def hook(event):
    payload = json.load(sys.stdin)
    sid = hashlib.sha256(str(payload.get("session_id", "unknown")).encode()).hexdigest()[:24]
    marker = LOCAL / "sessions" / (sid + ".json")
    if not STATE.exists():
        if event == "SessionStart":
            print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext":
                "No project ledger yet. Ask the user for the project name and one-sentence goal, then run ./projectctl init --name NAME --goal GOAL and fill the placeholders in CLAUDE.md."}}))
        return
    state = read_json(STATE)
    if event == "SessionStart":
        if not (payload.get("source") in {"compact", "resume"} and marker.exists()):
            atomic_json(marker, {"at": now(), "fingerprint": fingerprint(), "handoff": digest(state["handoff"])})
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext":
            status_text(state) + "\nGreet the user briefly with last activity and next action; read only task-relevant files. Save progress with ./projectctl handoff before finishing."}}))
    elif event == "Stop":
        if payload.get("stop_hook_active"):
            return  # one reminder at most; never trap the session in a loop
        errors = validate(state) + journal_errors(state)
        prior = read_json(marker) if marker.exists() else {}
        changed = prior and prior.get("fingerprint") != fingerprint() and prior.get("handoff") == digest(state["handoff"])
        if errors or changed:
            print(json.dumps({"decision": "block", "reason": "Handoff check: " + ("; ".join(errors[:3]) if errors else
                "project files changed without an updated handoff. Run ./projectctl handoff with the real outcome, evidence and next action; do not invent completed work.")}))
        else:
            atomic_json(marker, {"at": now(), "fingerprint": fingerprint(), "handoff": digest(state["handoff"])})
    elif event == "SessionEnd":
        atomic_json(LOCAL / "last_session.json", {"ended_at": now(), "session_id_hash": sid, "state_sha256": digest(state)})


def main():
    ap = argparse.ArgumentParser(prog="projectctl", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--name", required=True); p.add_argument("--goal", required=True)
    sub.add_parser("status"); sub.add_parser("verify")
    p = sub.add_parser("task", help="task add ID TITLE | task set ID STATUS")
    p.add_argument("action", choices=["add", "set"]); p.add_argument("id"); p.add_argument("arg")
    p.add_argument("--depends", default=""); p.add_argument("--acceptance", default="")
    p.add_argument("--note", default=""); p.add_argument("--evidence", action="append")
    p = sub.add_parser("claim", help="Add or revise a claim with an explicit epistemic status")
    p.add_argument("id"); p.add_argument("status", choices=sorted(CLAIM_STATUS))
    p.add_argument("--text"); p.add_argument("--scope", default=""); p.add_argument("--evidence", action="append")
    p = sub.add_parser("decide", help="Record a decision with reasoning and who made it")
    p.add_argument("id"); p.add_argument("--question", required=True); p.add_argument("--choice", required=True)
    p.add_argument("--source", required=True, choices=sorted(DECISION_SOURCES)); p.add_argument("--why", required=True)
    p = sub.add_parser("note"); p.add_argument("--summary", required=True); p.add_argument("--evidence", action="append")
    p = sub.add_parser("handoff"); p.add_argument("--summary", required=True); p.add_argument("--next", required=True); p.add_argument("--evidence", action="append")
    p = sub.add_parser("hook"); p.add_argument("event", choices=["SessionStart", "Stop", "SessionEnd"])
    a = ap.parse_args()

    try:
        if a.cmd == "hook":
            return hook(a.event)
        if a.cmd == "init":
            with locked():
                if STATE.exists():
                    sys.exit("Already initialised; refusing to overwrite state.json")
                state = {"schema_version": 1, "updated_at": now(), "project": {"name": a.name, "goal": a.goal},
                         "handoff": {"summary": "Project initialised; no work recorded yet.", "next_action": "Define the first tasks with ./projectctl task add.", "at": now()},
                         "tasks": [], "claims": [], "decisions": []}
                commit(state, "init", f"Initialised project {a.name}")
            return print("Initialised.")
        state = load()
        if a.cmd == "status":
            return print(status_text(state))
        if a.cmd == "verify":
            problems = validate(state) + journal_errors(state)
            drift = evidence_drift(state)
            for p in problems:
                print("ERROR:", p)
            for rid, path in drift:
                print(f"DRIFT: {rid} cites changed/missing {path}")
            print("OK" if not problems else f"{len(problems)} problem(s)")
            return sys.exit(1 if problems else 0)
        with locked():
            state = load()
            if a.cmd == "task":
                if a.action == "add":
                    if any(t["id"] == a.id for t in state["tasks"]):
                        raise ValueError(f"Task {a.id} exists")
                    check_text(a.arg + a.acceptance)
                    state["tasks"].append({"id": a.id, "title": a.arg, "status": "todo", "acceptance": a.acceptance,
                                           "depends_on": [d for d in a.depends.split(",") if d]})
                    commit(state, "task_add", f"Task {a.id}: {a.arg}")
                else:
                    if a.arg not in TASK_STATUS:
                        raise ValueError(f"Status must be one of {sorted(TASK_STATUS)}")
                    t = find(state, "tasks", a.id)
                    if a.arg == "done" and not a.evidence:
                        raise ValueError("A task is done only with --evidence showing its acceptance criterion is met")
                    t["status"] = a.arg
                    if a.note:
                        check_text(a.note)
                        t["note"] = a.note
                    if a.evidence:
                        t["evidence"] = evidence(a.evidence)
                    commit(state, "task_set", f"Task {a.id} -> {a.arg}", t.get("evidence", []))
            elif a.cmd == "claim":
                rec = next((c for c in state["claims"] if c["id"] == a.id), None)
                if rec is None:
                    if not a.text:
                        raise ValueError("New claims need --text")
                    rec = {"id": a.id}
                    state["claims"].append(rec)
                check_text((a.text or "") + a.scope)
                rec.update({"status": a.status, "text": a.text or rec["text"], "scope": a.scope or rec.get("scope", ""),
                            "evidence": evidence(a.evidence) or rec.get("evidence", []), "updated": now()})
                commit(state, "claim", f"Claim {a.id} [{a.status}]", rec["evidence"])
            elif a.cmd == "decide":
                check_text(a.question + a.choice + a.why)
                state["decisions"].append({"id": a.id, "date": now(), "question": a.question, "choice": a.choice, "source": a.source, "why": a.why})
                commit(state, "decision", f"Decision {a.id} ({a.source}): {a.choice[:80]}")
            elif a.cmd == "note":
                commit(state, "note", a.summary, evidence(a.evidence))
            elif a.cmd == "handoff":
                refs = evidence(a.evidence)
                check_text(a.summary + a.next)
                state["handoff"] = {"summary": a.summary, "next_action": a.next, "at": now()}
                commit(state, "handoff", a.summary, refs)
            print("Recorded.")
    except ValueError as exc:
        sys.exit(f"Error: {exc}")


if __name__ == "__main__":
    main()
