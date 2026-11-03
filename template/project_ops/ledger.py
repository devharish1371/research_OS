"""Validated, replayable local ledger. Stdlib only; source text is always data."""
import contextlib
import copy
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

GROUPS = ("tasks", "claims", "decisions", "notes", "memories")
TASK_STATUS = {"todo", "in_progress", "blocked", "done", "deferred"}
CLAIM_STATUS = {"verified", "reported", "hypothesis", "proposed", "disputed", "unknown", "withdrawn"}
SOURCES = {"user", "assistant_proposal", "external", "tool_observation"}
RELATIONS = {"supersedes", "contradicts", "depends_on", "supported_by", "related_to"}
LIFECYCLES = {"active", "archived", "superseded", "tombstoned"}
ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,95}$")
HEX = re.compile(r"^[a-f0-9]{64}$")


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(obj):
    return hashlib.sha256(canonical(obj).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read {path.name}: {exc}") from exc


def sync_dir(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def check_text(value):
    if not isinstance(value, str):
        raise ValueError("Text fields must be strings")
    if re.search(r"(?i)(password|passwd|otp|api.?key|secret|token)\s*[:=]\s*\S+", value) or "PRIVATE KEY-----" in value or re.search(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}", value):
        raise ValueError("Possible credential rejected; never record secrets")
    if len(value) > 4000:
        raise ValueError("Keep each text field under 4,000 characters; link an artifact")


def check_strings(obj):
    if isinstance(obj, str):
        check_text(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            check_strings(value)
    elif isinstance(obj, list):
        for value in obj:
            check_strings(value)


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid ISO date/time: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def records(state):
    for group in GROUPS:
        for record in state.get(group, []):
            yield group, record
    if state.get("handoff"):
        yield "handoff", state["handoff"]


def find(state, rid):
    for group, rec in records(state):
        if rec["id"] == rid:
            return group, rec
    raise ValueError(f"No record with id {rid}")


def revised(rec, old=None):
    rec["revision"] = old.get("revision", 0) + 1 if old else 1
    rec["updated_at"] = now()
    rec.setdefault("created_at", rec["updated_at"])
    rec.setdefault("lifecycle", "active")
    rec.setdefault("source", "assistant_proposal")
    rec.setdefault("evidence", [])
    rec.setdefault("links", [])
    return rec


def validate(state):
    """All write paths use the same invariants; checks are linear in records/edges."""
    try:
        if not isinstance(state, dict) or state.get("schema_version") != 2:
            raise ValueError("Unsupported schema; run migrate --dry-run for a v1 ledger")
        if not isinstance(state.get("version"), int) or state["version"] < 1:
            raise ValueError("Invalid state version")
        if not isinstance(state.get("project"), dict):
            raise ValueError("Missing project")
        for key in ("id", "name", "goal"):
            if not isinstance(state["project"].get(key), str) or not state["project"][key].strip():
                raise ValueError(f"Missing project {key}")
        for group in GROUPS:
            if not isinstance(state.get(group), list):
                raise ValueError(f"Missing record list: {group}")
        if not isinstance(state.get("handoff"), dict):
            raise ValueError("Missing handoff")
        for key in ("summary", "next_action"):
            if not isinstance(state["handoff"].get(key), str):
                raise ValueError(f"Missing handoff {key}")
        check_strings(state)
        ids = {}
        for group, rec in records(state):
            if not isinstance(rec, dict) or not ID.fullmatch(rec.get("id", "")):
                raise ValueError("Invalid record id")
            if rec["id"] in ids:
                raise ValueError(f"Duplicate id {rec['id']}")
            ids[rec["id"]] = rec
            if not isinstance(rec.get("revision"), int) or rec["revision"] < 1:
                raise ValueError(f"{rec['id']}: invalid revision")
            if rec.get("source") not in SOURCES or rec.get("lifecycle") not in LIFECYCLES:
                raise ValueError(f"{rec['id']}: invalid source/lifecycle")
            timestamp(rec["created_at"])
            timestamp(rec["updated_at"])
            for key in ("valid_from", "valid_to"):
                if rec.get(key):
                    timestamp(rec[key])
            if rec.get("valid_from") and rec.get("valid_to") and timestamp(rec["valid_from"]) >= timestamp(rec["valid_to"]):
                raise ValueError(f"{rec['id']}: invalid validity interval")
            if not isinstance(rec.get("evidence"), list) or not isinstance(rec.get("links"), list):
                raise ValueError(f"{rec['id']}: invalid evidence/links")
            for ref in rec["evidence"]:
                path = Path(ref["path"])
                if path.is_absolute() or ".." in path.parts or not HEX.fullmatch(ref.get("sha256", "")):
                    raise ValueError(f"{rec['id']}: invalid evidence reference")
            if group == "memories" and rec.get("kind") == "constraint" and rec["source"] != "user":
                raise ValueError(f"{rec['id']}: constraints require direct user attribution")
            if group == "tasks":
                if rec.get("status") not in TASK_STATUS or not isinstance(rec.get("depends_on"), list):
                    raise ValueError(f"{rec['id']}: invalid task")
                if rec["status"] == "done" and (not rec.get("evidence") or not rec.get("acceptance", "").strip()):
                    raise ValueError(f"{rec['id']}: done needs acceptance and evidence")
            if group == "claims":
                if rec.get("status") not in CLAIM_STATUS or not rec.get("text", "").strip():
                    raise ValueError(f"{rec['id']}: invalid claim")
                if rec["status"] == "verified" and (not rec["evidence"] or not rec.get("scope", "").strip()):
                    raise ValueError(f"{rec['id']}: verified needs evidence and scope")
                metric = rec.get("metric")
                if metric and (not isinstance(metric.get("denominator"), (int, float)) or not math.isfinite(metric["denominator"]) or metric["denominator"] <= 0 or not metric.get("protocol") or not metric.get("unit") or not isinstance(metric.get("value"), (int, float)) or not math.isfinite(metric["value"])):
                    raise ValueError(f"{rec['id']}: metric needs value, positive denominator, unit and protocol")
        tasks = {t["id"]: t for t in state["tasks"]}
        indegree = {key: 0 for key in tasks}
        children = {key: [] for key in tasks}
        for tid, task in tasks.items():
            for dep in set(task["depends_on"]):
                if dep not in tasks:
                    raise ValueError(f"{tid}: unknown dependency {dep}")
                if task["status"] == "done" and tasks[dep]["status"] != "done":
                    raise ValueError(f"{tid}: dependency {dep} is not done")
                indegree[tid] += 1
                children[dep].append(tid)
        ready = [key for key, degree in indegree.items() if degree == 0]
        visited = 0
        while ready:
            key = ready.pop()
            visited += 1
            for child in children[key]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if visited != len(tasks):
            raise ValueError("Task dependencies contain a cycle")
        for rid, rec in ids.items():
            for link in rec["links"]:
                if link.get("relation") not in RELATIONS or link.get("id") not in ids or link["id"] == rid:
                    raise ValueError(f"{rid}: invalid relationship")
        return []
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return [str(exc)]


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.ops = self.root / "project_ops"
        self.state_path = self.ops / "state.json"
        self.journal = self.ops / "logs/events.jsonl"
        self.local = self.ops / ".local"
        self.checkpoints = self.ops / "logs/checkpoints"
        for path in (self.ops, self.state_path, self.journal, self.local, self.checkpoints):
            if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                raise ValueError("Ledger storage paths must stay inside the project without symlink aliases")

    @contextlib.contextmanager
    def locked(self):
        self.local.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.local / "state.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def evidence(self, paths):
        refs, seen = [], set()
        for name in paths or []:
            path = (self.root / name).resolve()
            if not path.is_relative_to(self.root) or not path.is_file():
                raise ValueError(f"Evidence must be a file inside the project: {name}")
            rel = str(path.relative_to(self.root))
            if rel not in seen:
                refs.append({"path": rel, "sha256": file_hash(path), "observed_at": now()})
                seen.add(rel)
        return refs

    def drift(self, state, selected=None):
        hashes, drift = {}, []
        for _, rec in records(state):
            if selected is not None and rec["id"] not in selected:
                continue
            if rec.get("lifecycle") in {"archived", "superseded", "tombstoned"}:
                continue
            for ref in rec.get("evidence", []):
                name = ref["path"]
                if name not in hashes:
                    path = (self.root / name).resolve()
                    try:
                        hashes[name] = file_hash(path) if path.is_relative_to(self.root) and path.is_file() else None
                    except OSError:
                        hashes[name] = None
                if hashes[name] != ref["sha256"]:
                    drift.append({"id": rec["id"], "path": name})
        return drift

    def events(self):
        if not self.journal.exists() or self.journal.stat().st_size == 0:
            raise ValueError("Journal missing or empty; inspect backups before recovery")
        previous, seq = "0" * 64, 0
        with self.journal.open(encoding="utf-8") as stream:
            for line in stream:
                seq += 1
                try:
                    if not line.endswith("\n"):
                        raise ValueError("partial final line")
                    row = json.loads(line)
                    body = {k: v for k, v in row.items() if k != "hash"}
                    if row.get("previous") != previous or digest(body) != row.get("hash"):
                        raise ValueError("hash chain mismatch")
                    if row.get("schema_version") == 2 and row.get("seq") != seq:
                        raise ValueError("sequence mismatch")
                except (ValueError, TypeError, AttributeError) as exc:
                    raise ValueError(f"Journal broken at line {seq}: {exc}") from exc
                previous = row["hash"]
                yield row

    def replay(self, as_of=None):
        state, maps, last = None, {}, None
        cutoff = timestamp(as_of) if as_of else None
        for row in self.events():
            if row.get("schema_version") != 2:
                raise ValueError("Legacy journal: run migrate --dry-run")
            if cutoff and timestamp(row["at"]) > cutoff:
                continue
            if state is None:
                if "initial" not in row:
                    raise ValueError("Journal has no initial state")
                state = copy.deepcopy(row["initial"])
                maps = {group: {r["id"]: r for r in state[group]} for group in GROUPS}
            else:
                for change in row["changes"]:
                    group = change["group"]
                    if group == "handoff":
                        state["handoff"] = change["record"]
                    elif group in GROUPS:
                        maps[group][change["record"]["id"]] = change["record"]
                    else:
                        raise ValueError("Unknown event group")
                state["version"] = row["seq"]
                state["updated_at"] = row["at"]
            last = row
        if state is None:
            raise ValueError("No state at requested time")
        for group in GROUPS:
            state[group] = list(maps[group].values())
        if digest(state) != last["state_sha256"]:
            raise ValueError("Replay digest mismatch")
        problems = validate(state)
        if problems:
            raise ValueError("; ".join(problems))
        return state, last

    def signature(self):
        stat = self.journal.stat()
        return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]

    def remember_verified(self, state, row):
        atomic_json(self.local / "verified.json", {"journal_stat": self.signature(), "state_sha256": digest(state), "last": {"hash": row["hash"], "seq": row["seq"]}})

    def load(self, full=False):
        if not self.state_path.exists():
            raise ValueError("No state; run init, or recover if a journal exists")
        state = read_json(self.state_path)
        if state.get("schema_version") == 1:
            raise ValueError("v1 ledger detected; run migrate --dry-run, then migrate")
        problems = validate(state)
        if problems:
            raise ValueError("; ".join(problems))
        cache = self.local / "verified.json"
        if not full and cache.exists() and self.journal.exists():
            try:
                cached = read_json(cache)
                if cached["journal_stat"] == self.signature() and cached["state_sha256"] == digest(state):
                    return state
            except (ValueError, KeyError):
                pass
        restored, row = self.replay()
        if digest(restored) != digest(state):
            raise ValueError("state.json differs from committed journal; inspect history, then recover explicitly")
        self.remember_verified(state, row)
        return state

    def init(self, name, goal):
        if self.state_path.exists() or self.journal.exists():
            raise ValueError("Already initialized or recoverable history exists")
        state = {"schema_version": 2, "version": 1, "updated_at": now(),
                 "project": {"id": str(uuid.uuid4()), "name": name, "goal": goal},
                 "handoff": revised({"id": "HANDOFF", "summary": "Project initialized; no work recorded yet.", "next_action": "Define the first task with acceptance criteria."}),
                 **{group: [] for group in GROUPS}}
        self.commit(state, None, "init", "Initialized project")
        return state

    def prior_operation(self, operation_id, request_hash):
        if not operation_id or not self.journal.exists():
            return None
        for row in self.events():
            if row.get("operation_id") == operation_id:
                if row.get("request_sha256") != request_hash:
                    raise ValueError("Operation ID already used for a different request")
                return row["seq"]
        return None

    def commit(self, state, old, kind, summary, operation_id=None, request_hash=None):
        check_text(summary)
        check_text(operation_id or "")
        stamp = now()
        state["version"] = old["version"] + 1 if old else 1
        state["updated_at"] = stamp
        problems = validate(state)
        if problems:
            raise ValueError("; ".join(problems))
        previous = "0" * 64
        if old:
            current = self.load()
            if digest(current) != digest(old):
                raise ValueError("State revision conflict; reload before committing")
            if state["project"] != old["project"]:
                raise ValueError("Project identity cannot change through a record operation")
            before = {rec["id"]: (group, rec) for group, rec in records(old)}
            after = {rec["id"]: (group, rec) for group, rec in records(state)}
            if before.keys() - after.keys():
                raise ValueError("Records cannot be deleted from history; use lifecycle operations")
            for rid, (group, rec) in after.items():
                if rid in before:
                    old_group, old_rec = before[rid]
                    if group != old_group or (rec != old_rec and rec["revision"] != old_rec["revision"] + 1):
                        raise ValueError(f"{rid}: invalid record revision transition")
                elif rec["revision"] != 1:
                    raise ValueError(f"{rid}: new records start at revision 1")
            previous = read_json(self.local / "verified.json")["last"]["hash"]
        changes = []
        if old:
            prior = {r["id"]: r for _, r in records(old)}
            for group, rec in records(state):
                if rec != prior.get(rec["id"]):
                    changes.append({"group": group, "record": rec})
        row = {"schema_version": 2, "id": str(uuid.uuid4()), "seq": state["version"], "at": stamp,
               "kind": kind, "summary": summary, "previous": previous, "state_sha256": digest(state),
               "changes": changes, "operation_id": operation_id, "request_sha256": request_hash}
        if old is None:
            row["initial"] = state
        row["hash"] = digest(row)
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.journal.open("a", encoding="utf-8") as stream:
            stream.write(canonical(row) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        sync_dir(self.journal.parent)
        # A crash from this point is recovered by replay; never discard the event.
        atomic_json(self.state_path, state)
        self.remember_verified(state, row)
        step = state["version"] // 100
        if state["version"] == 1 or (state["version"] % 100 == 0 and step > 0 and step & (step - 1) == 0):
            self.checkpoint(state, row["hash"])
        return row

    def checkpoint(self, state, head=None):
        if head is None:
            self.load(full=True)
            head = read_json(self.local / "verified.json")["last"]["hash"]
        value = {"schema_version": 2, "event_hash": head, "state_sha256": digest(state), "state": state}
        path = self.checkpoints / f"{state['version']:012d}-{digest(state)}.json"
        if not path.exists():
            atomic_json(path, value)
        return path

    def verify_checkpoints(self):
        checkpoints = {}
        for path in self.checkpoints.glob("*.json"):
            value = read_json(path)
            if value.get("state_sha256") != digest(value.get("state")):
                raise ValueError(f"Checkpoint digest mismatch: {path.name}")
            seq = value["state"]["version"]
            checkpoints.setdefault(seq, []).append((path, value))
        for row in self.events():
            for path, value in checkpoints.pop(row["seq"], []):
                if value.get("event_hash") != row["hash"] or value["state_sha256"] != row["state_sha256"]:
                    raise ValueError(f"Checkpoint is not anchored to journal: {path.name}")
        if checkpoints:
            raise ValueError("Checkpoint references a missing journal event")

    def recover(self):
        state, row = self.replay()
        if self.state_path.exists():
            backup = self.ops / "logs/recovery" / (str(uuid.uuid4()) + ".json")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.state_path, backup)
        atomic_json(self.state_path, state)
        self.remember_verified(state, row)
        return state

    def history(self, rid):
        out = []
        for row in self.events():
            candidates = list(records(row["initial"])) if "initial" in row else [(c["group"], c["record"]) for c in row.get("changes", [])]
            for _, rec in candidates:
                if rec["id"] == rid:
                    out.append({"at": row["at"], "event": row["seq"], "record": rec})
        return out

    def migrate(self, dry_run=False):
        old = read_json(self.state_path)
        if old.get("schema_version") != 1:
            raise ValueError("Migration requires schema v1")
        rows = list(self.events())
        if rows[-1].get("state_sha256") != digest(old):
            raise ValueError("v1 state/journal mismatch; migration refused")
        backup = self.ops / "logs/legacy-v1" / digest(old)
        state = copy.deepcopy(old)
        state.update(schema_version=2, version=1)
        state["project"]["id"] = str(uuid.uuid4())
        for group in GROUPS:
            state.setdefault(group, [])
        used = {r["id"] for group in GROUPS for r in state[group]}
        handoff_id = "HANDOFF"
        while handoff_id in used:
            handoff_id += "_"
        state["handoff"]["id"] = handoff_id
        for _, rec in records(state):
            if rec.get("status") == "done" and not rec.get("acceptance"):
                rec["acceptance"] = "Legacy v1: acceptance not recorded; review required."
                rec["review_required"] = True
            if rec.get("status") == "verified" and not rec.get("scope"):
                rec["scope"] = "Legacy v1: scope not recorded; review required."
                rec["review_required"] = True
            rec.setdefault("created_at", rec.get("updated", rec.get("date", rec.get("at", old["updated_at"]))))
            revised(rec)
        # Handoff refs are in v1 events, not in the handoff object.
        last_handoff = next((r for r in reversed(rows) if r["kind"] == "handoff"), None)
        if last_handoff:
            state["handoff"]["evidence"] = last_handoff.get("evidence", [])
        for i, row in enumerate(rows):
            if row["kind"] == "note":
                rid = f"LEGACY-NOTE-{i}"
                while rid in used or rid == handoff_id:
                    rid += "_"
                used.add(rid)
                state["notes"].append(revised({"id": rid, "text": row["summary"], "created_at": row["at"], "evidence": row.get("evidence", [])}))
        problems = validate(state)
        if problems:
            raise ValueError("v1 needs review before migration: " + "; ".join(problems))
        report = {"from": 1, "to": 2, "records": sum(1 for _ in records(state)), "backup": str(backup), "review_required": [r["id"] for _, r in records(state) if r.get("review_required")], "drift": self.drift(state), "legacy_history": "Preserved byte-for-byte in backup; v2 revisions begin at import."}
        if dry_run:
            return report
        if backup.exists():
            raise ValueError("Backup already exists; inspect interrupted migration before retry")
        backup.mkdir(parents=True)
        shutil.copy2(self.state_path, backup / "state.json")
        shutil.copy2(self.journal, backup / "events.jsonl")
        snapshots = self.ops / "logs/snapshots"
        if snapshots.exists():
            if snapshots.is_symlink() or not snapshots.resolve().is_relative_to(self.root):
                raise ValueError("Legacy snapshots must stay inside the project")
            shutil.copytree(snapshots, backup / "snapshots", symlinks=True)
        # Build a complete new journal in staging before atomically switching it.
        with tempfile.TemporaryDirectory(dir=self.local, prefix="migration-") as temp:
            staging = Store(Path(temp))
            staging.commit(state, None, "migrate", "Imported v1; original history preserved")
            os.replace(staging.journal, self.journal)
            sync_dir(self.journal.parent)
        atomic_json(self.state_path, state)
        restored, row = self.replay()
        self.remember_verified(restored, row)
        self.checkpoint(restored, row["hash"])
        return report
