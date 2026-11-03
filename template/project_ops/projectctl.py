#!/usr/bin/env python3
"""Local evidence-aware project memory. No network, model calls, or transcript reads."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid

from ledger import (Store, CLAIM_STATUS, TASK_STATUS, SOURCES, RELATIONS, atomic_json,
                    digest, find, now, read_json, records, revised, timestamp, validate)
from memory import Index, bounded_json, fingerprint, packet, retrieve

ROOT = Path(__file__).resolve().parent.parent


def render(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def bounds(value):
    number = int(value)
    if not 1 <= number <= 50:
        raise argparse.ArgumentTypeError("limit must be between 1 and 50")
    return number


def parser():
    ap = argparse.ArgumentParser(prog="projectctl", description=__doc__)
    ap.add_argument("--operation-id", help="idempotency key for a mutation; place before subcommand")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--name", required=True); p.add_argument("--goal", required=True)
    for name in ("status", "context"):
        p = sub.add_parser(name)
        p.add_argument("--max-bytes", type=int, default=None)
        p.add_argument("--budget-tokens", type=int, help="estimate only: translates to 4 UTF-8 bytes/token; no exact tokenizer")
        p.add_argument("--task"); p.add_argument("--query"); p.add_argument("--check-evidence", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("--mode", choices=["full", "quick"], default="full"); p.add_argument("--json", action="store_true")
    p.add_argument("--warn-only", action="store_true", help="compatibility: drift is a warning, not exit 2")
    p = sub.add_parser("show"); p.add_argument("id"); p.add_argument("--revision", type=int); p.add_argument("--json", action="store_true"); p.add_argument("--full", action="store_true", help="allow an explicitly unbounded record export")
    p = sub.add_parser("history"); p.add_argument("id"); p.add_argument("--limit", type=bounds, default=10); p.add_argument("--json", action="store_true")
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("--limit", type=bounds, default=8)
    p.add_argument("--scope"); p.add_argument("--kind"); p.add_argument("--as-of", help="recording-time snapshot (ISO date/time)")
    p.add_argument("--valid-at", help="filter validity intervals; independent of recording time")
    p.add_argument("--include-archived", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("index"); p.add_argument("action", choices=["rebuild"])
    sub.add_parser("checkpoint"); sub.add_parser("recover"); sub.add_parser("doctor")
    p = sub.add_parser("migrate"); p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("task")
    p.add_argument("action", choices=["add", "set"]); p.add_argument("id"); p.add_argument("arg")
    p.add_argument("--depends", default=""); p.add_argument("--acceptance"); p.add_argument("--note")
    metadata(p)
    p = sub.add_parser("claim"); p.add_argument("id"); p.add_argument("status", choices=sorted(CLAIM_STATUS))
    p.add_argument("--text"); p.add_argument("--scope"); p.add_argument("--metric"); p.add_argument("--value", type=float)
    p.add_argument("--denominator", type=float); p.add_argument("--unit"); p.add_argument("--protocol")
    metadata(p)
    p = sub.add_parser("decide"); p.add_argument("id"); p.add_argument("--question", required=True)
    p.add_argument("--choice", required=True); p.add_argument("--why", required=True)
    metadata(p, source_required=True)
    p = sub.add_parser("note"); p.add_argument("--id"); p.add_argument("--summary", required=True); metadata(p)
    p = sub.add_parser("handoff"); p.add_argument("--summary", required=True); p.add_argument("--next", required=True)
    p.add_argument("--session-id", help="optional explicit session attribution")
    metadata(p)
    p = sub.add_parser("remember"); p.add_argument("id"); p.add_argument("text")
    p.add_argument("--kind", choices=["observation", "procedure", "constraint", "source"], default="observation")
    p.add_argument("--scope", default=""); metadata(p)
    for name in ("archive", "restore", "forget"):
        p = sub.add_parser(name); p.add_argument("id"); p.add_argument("--reason", required=True)
        p.add_argument("--expect-revision", type=int)
    p = sub.add_parser("hook"); p.add_argument("event", choices=["SessionStart", "Stop", "SessionEnd", "PreCompact"])
    return ap


def metadata(p, source_required=False):
    p.add_argument("--evidence", action="append")
    p.add_argument("--source", choices=sorted(SOURCES), required=source_required)
    p.add_argument("--expect-revision", type=int)
    p.add_argument("--valid-from"); p.add_argument("--valid-to")
    p.add_argument("--link", action="append", help="RELATION:ID; relations: " + ", ".join(sorted(RELATIONS)))


def apply_metadata(rec, old, args, store):
    if args.expect_revision is not None and (old is None or old["revision"] != args.expect_revision):
        raise ValueError("Revision conflict; read the current record before retrying")
    if args.source:
        rec["source"] = args.source
    if args.evidence:
        rec["evidence"] = store.evidence(args.evidence)
    for attr in ("valid_from", "valid_to"):
        value = getattr(args, attr)
        if value is not None:
            timestamp(value)
            rec[attr] = value
    if args.link:
        links = []
        for value in args.link:
            relation, separator, rid = value.partition(":")
            if not separator or relation not in RELATIONS:
                raise ValueError("Links must be RELATION:ID")
            links.append({"relation": relation, "id": rid})
        rec["links"] = links
    return revised(rec, old)


def mutation(store, state, args):
    cmd = args.cmd
    if cmd == "task":
        if args.action == "add":
            if any(r["id"] == args.id for _, r in records(state)):
                raise ValueError(f"ID {args.id} already exists")
            if not args.acceptance or not args.acceptance.strip():
                raise ValueError("New tasks require a nonempty --acceptance criterion")
            rec = {"id": args.id, "title": args.arg, "status": "todo", "acceptance": args.acceptance,
                   "depends_on": [x.strip() for x in args.depends.split(",") if x.strip()]}
            state["tasks"].append(apply_metadata(rec, None, args, store))
        else:
            group, rec = find(state, args.id)
            if group != "tasks" or args.arg not in TASK_STATUS:
                raise ValueError("Task ID/status invalid")
            old = copy.deepcopy(rec)
            if args.arg == "done" and not args.evidence:
                raise ValueError("Done requires freshly supplied --evidence")
            rec["status"] = args.arg
            if args.note is not None:
                rec["note"] = args.note
            if args.acceptance is not None:
                rec["acceptance"] = args.acceptance
            apply_metadata(rec, old, args, store)
    elif cmd == "claim":
        try:
            group, rec = find(state, args.id)
            if group != "claims":
                raise ValueError("ID belongs to a different record kind")
            old = copy.deepcopy(rec)
        except ValueError as exc:
            if not str(exc).startswith("No record"):
                raise
            if not args.text:
                raise ValueError("New claims require --text")
            rec, old = {"id": args.id}, None
            state["claims"].append(rec)
        changed = old is not None and ((args.text is not None and args.text != old["text"]) or (args.scope is not None and args.scope != old.get("scope")) or args.metric is not None or (args.source is not None and args.source != old.get("source")) or any(getattr(args, key) is not None and getattr(args, key) != old.get(key) for key in ("valid_from", "valid_to")))
        if changed:
            rec["evidence"] = []
            rec.pop("metric", None)
        if args.status == "verified" and (changed or old is None or old["status"] != "verified") and not args.evidence:
            raise ValueError("New/revised verification requires explicit --evidence and --scope")
        rec["status"] = args.status
        if args.text is not None:
            rec["text"] = args.text
        if args.scope is not None:
            rec["scope"] = args.scope
        if any(getattr(args, k) is not None for k in ("metric", "value", "denominator", "unit", "protocol")):
            if any(getattr(args, k) is None for k in ("metric", "value", "denominator", "unit", "protocol")):
                raise ValueError("Numeric claims need --metric --value --denominator --unit --protocol together")
            rec["metric"] = {"name": args.metric, "value": args.value, "denominator": args.denominator, "unit": args.unit, "protocol": args.protocol}
        apply_metadata(rec, old, args, store)
        if rec["status"] == "verified" and store.drift(state, {rec["id"]}):
            raise ValueError("Verified evidence is stale; review it and explicitly supply evidence")
    elif cmd == "decide":
        rec = {"id": args.id, "question": args.question, "choice": args.choice, "why": args.why}
        state["decisions"].append(apply_metadata(rec, None, args, store))
    elif cmd == "note":
        rec = {"id": args.id or "N-" + uuid.uuid4().hex[:12], "text": args.summary}
        state["notes"].append(apply_metadata(rec, None, args, store))
    elif cmd == "handoff":
        old = copy.deepcopy(state["handoff"])
        rec = {"id": old["id"], "created_at": old["created_at"], "summary": args.summary, "next_action": args.next}
        if args.session_id:
            rec["session_id_hash"] = hashlib.sha256(args.session_id.encode()).hexdigest()[:24]
        state["handoff"] = apply_metadata(rec, old, args, store)
    elif cmd == "remember":
        try:
            group, rec = find(state, args.id)
            if group != "memories":
                raise ValueError("ID belongs to a different record kind")
            old = copy.deepcopy(rec)
        except ValueError as exc:
            if not str(exc).startswith("No record"):
                raise
            rec, old = {"id": args.id}, None
            state["memories"].append(rec)
        if old and args.text != old.get("text"):
            rec["evidence"] = []
        rec.update(text=args.text, kind=args.kind, scope=args.scope)
        apply_metadata(rec, old, args, store)
    elif cmd in {"archive", "restore", "forget"}:
        group, rec = find(state, args.id)
        if group == "handoff":
            raise ValueError("Replace the active handoff with handoff; it cannot be archived")
        old = copy.deepcopy(rec)
        if args.expect_revision is not None and old["revision"] != args.expect_revision:
            raise ValueError("Revision conflict")
        rec["lifecycle"] = {"archive": "archived", "restore": "active", "forget": "tombstoned"}[cmd]
        rec["lifecycle_reason"] = args.reason
        revised(rec, old)
    else:
        raise ValueError("Unknown mutation")


def hook(store, event):
    payload = json.load(sys.stdin)
    sid = hashlib.sha256(str(payload.get("session_id", "unknown")).encode()).hexdigest()[:24]
    marker = store.local / "sessions" / (sid + ".json")
    if not store.state_path.exists():
        if event == "SessionStart":
            render({"hookSpecificOutput": {"hookEventName": event, "additionalContext": "No project ledger. Run projectctl init with the project name and goal."}})
        return
    with store.locked():
        try:
            state = store.load()
        except (ValueError, OSError) as exc:
            message = "Project memory integrity error: " + str(exc)[:600] + ". Do not rely on saved claims; run projectctl verify."
            if event == "SessionStart":
                render({"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}})
            elif event == "Stop" and not payload.get("stop_hook_active"):
                render({"decision": "block", "reason": message})
            return
        if event == "PreCompact":
            store.checkpoint(state)
            return
        if event == "SessionEnd":
            atomic_json(store.local / "last_session.json", {"at": now(), "session_id_hash": sid, "version": state["version"]})
            return
        scan = fingerprint(store)
        current = {"at": now(), "fingerprint": scan, "handoff_revision": state["handoff"]["revision"], "version": state["version"]}
        if event == "SessionStart":
            if not (payload.get("source") in {"compact", "resume"} and marker.exists()):
                atomic_json(marker, current)
            context = packet(store, state, budget=4800)
            render({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}})
            return
        prior = read_json(marker) if marker.exists() else None
        handoff_changed = prior and prior["handoff_revision"] != current["handoff_revision"]
        owner = state["handoff"].get("session_id_hash")
        own_handoff = handoff_changed and (owner is None or owner == sid)
        changed = prior is None or prior["fingerprint"]["digest"] != scan["digest"] or prior["version"] != state["version"]
        uncertain = not scan["complete"] or (prior and not prior["fingerprint"].get("complete"))
        if payload.get("stop_hook_active"):
            # Acknowledge the handoff even on the no-loop retry; otherwise the next turn is missed.
            if own_handoff:
                atomic_json(marker, current)
            return
        if (changed or uncertain) and not own_handoff:
            render({"decision": "block", "reason": "Project work changed or the change scan was incomplete. Save an accurate projectctl handoff with evidence and next action; no invented progress."})
        else:
            atomic_json(marker, current)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        store = Store(ROOT)
        if args.cmd == "hook":
            hook(store, args.event)
            return 0
        with store.locked():
            if args.cmd == "init":
                store.init(args.name, args.goal)
                print("Initialized schema v2.")
                return 0
            if args.cmd == "migrate":
                render(store.migrate(args.dry_run)); return 0
            if args.cmd == "recover":
                state = store.recover(); print(f"Recovered committed state version {state['version']}; prior export backed up."); return 0
            if args.cmd == "doctor":
                db = sqlite3.connect(":memory:")
                try:
                    db.execute("CREATE VIRTUAL TABLE probe USING fts5(body)"); fts = True
                except sqlite3.OperationalError:
                    fts = False
                finally:
                    db.close()
                settings = store.root / ".claude/settings.json"
                render({"python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version, "fts5": fts,
                        "state_exists": store.state_path.exists(), "schema": read_json(store.state_path).get("schema_version") if store.state_path.exists() else None,
                        "settings_exists": settings.exists(), "network_required": False,
                        "integrity": "run verify", "change_detection": "bounded filesystem metadata, not a content audit"})
                return 0
            if args.cmd == "verify":
                try:
                    state = store.load(full=args.mode == "full")
                    if args.mode == "full":
                        store.verify_checkpoints()
                    drift = store.drift(state) if args.mode == "full" else []
                    result = {"integrity": "ok", "freshness": "stale" if drift else ("ok" if args.mode == "full" else "not_checked"),
                              "coverage": "all-active-records" if args.mode == "full" else "journal-metadata-and-state",
                              "drift": drift, "version": state["version"]}
                    code = 2 if drift and not args.warn_only else (3 if args.mode == "quick" else 0)
                except (ValueError, OSError) as exc:
                    result, code = {"integrity": "error", "error": str(exc)}, 1
                if args.json:
                    render(result)
                else:
                    print(result.get("error", result["integrity"].upper() + " | freshness=" + result.get("freshness", "unknown")))
                    for ref in result.get("drift", []):
                        print(f"DRIFT: {ref['id']} cites {ref['path']}")
                return code
            state = store.load()
            if args.cmd in {"status", "context"}:
                if args.budget_tokens is not None and args.budget_tokens <= 0:
                    raise ValueError("budget-tokens must be positive")
                budget = args.max_bytes if args.max_bytes is not None else (args.budget_tokens * 4 if args.budget_tokens else (4800 if args.cmd == "status" else 12000))
                text = packet(store, state, budget, args.task, args.query, args.check_evidence)
                sys.stdout.write(text + ("\n" if len(text.encode("utf-8")) < budget else "")); return 0
            if args.cmd == "show":
                if args.revision is not None:
                    rec = next((r["record"] for r in store.history(args.id) if r["record"]["revision"] == args.revision), None)
                    if rec is None:
                        raise ValueError("No such record revision")
                else:
                    _, rec = find(state, args.id)
                size = len((json.dumps(rec, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
                if size > 16000 and not args.full:
                    render({"id": args.id, "error": "Record exceeds 16000-byte read budget", "bytes": size, "next": "Use show ID --full for explicit expansion"})
                    return 3
                render(rec); return 0
            if args.cmd == "history":
                history = store.history(args.id)
                if not history:
                    raise ValueError("No record history")
                print(bounded_json(history[-args.limit:])); return 0
            if args.cmd == "search":
                tombstones = {r["id"] for _, r in records(state) if r["lifecycle"] == "tombstoned"}
                if args.as_of:
                    state, _ = store.replay(args.as_of)
                hits = retrieve(store, state, args.query, limit=args.limit, scope=args.scope, kind=args.kind, valid_at=args.valid_at, include_archived=args.include_archived, transient=bool(args.as_of))
                print(bounded_json([r for r in hits if r["id"] not in tombstones])); return 0
            if args.cmd == "index":
                # Rebuild a disposable index via a fresh file; never alter authoritative events.
                if (store.local / "index.sqlite").exists():
                    (store.local / "index.sqlite").unlink()
                index = Index(store)
                try:
                    index.sync(state, force=True)
                    print("Index rebuilt (FTS5)." if index.fts else "Index rebuilt (lexical fallback).")
                finally:
                    index.close()
                return 0
            if args.cmd == "checkpoint":
                print(store.checkpoint(state)); return 0
            request_hash = digest({k: v for k, v in vars(args).items() if k != "operation_id"})
            prior = store.prior_operation(args.operation_id, request_hash)
            if prior:
                print(f"Already recorded at version {prior}."); return 0
            old = copy.deepcopy(state)
            mutation(store, state, args)
            store.commit(state, old, args.cmd, f"{args.cmd}: {getattr(args, 'id', None) or state['handoff']['id']}", args.operation_id, request_hash)
            print(f"Recorded version {state['version']}.")
            return 0
    except (ValueError, OSError, sqlite3.DatabaseError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
