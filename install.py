#!/usr/bin/env python3
"""Idempotent, manifest-aware installation; never silently replace user hooks."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

KIT = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def merged_settings(old, supplied):
    if not isinstance(old, dict):
        raise ValueError("Existing settings must be an object")
    result = json.loads(json.dumps(old))
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Existing settings.hooks must be an object")
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            raise ValueError(f"Existing hooks.{event} must be a list")
        kept = []
        for entry in entries:
            remaining = [h for h in entry.get("hooks", []) if "/project_ops/projectctl.py" not in h.get("command", "")]
            if remaining or not entry.get("hooks"):
                kept.append({**entry, "hooks": remaining} if entry.get("hooks") else entry)
        hooks[event] = kept
    for event, entries in supplied["hooks"].items():
        hooks.setdefault(event, []).extend(entries)
    return result


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".install-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", nargs="?", default=".")
    ap.add_argument("--name"); ap.add_argument("--goal")
    ap.add_argument("--force", action="store_true", help="replace conflicting runtime files with backups; preserve customized CLAUDE.md")
    ap.add_argument("--dry-run", action="store_true", help="show file action plan without writing")
    ap.add_argument("--migrate", action="store_true", help="migrate an existing v1 ledger with a durable history backup")
    a = ap.parse_args()
    if sys.version_info < (3, 9):
        ap.error("Python 3.9+ required")
    target = Path(a.target).expanduser().resolve()
    saved_state = target / "project_ops/state.json"
    project = json.loads(saved_state.read_text()).get("project", {}) if saved_state.exists() else {}
    name = a.name or project.get("name") or target.name
    goal = a.goal or project.get("goal") or "(set the one-sentence goal)"
    for protected in (target / ".gitignore", target / "project_ops/.local/install-manifest.json"):
        if protected.is_symlink() or not protected.resolve().is_relative_to(target):
            raise ValueError(f"Refusing symlink installation metadata: {protected.name}")
    manifest_path = target / "project_ops/.local/install-manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": {}}
    backup = target / "project_ops/.local/install-backups" / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    plans, conflicts = [], []
    for source in sorted((KIT / "template").rglob("*")):
        if not source.is_file() or source.is_symlink():
            continue
        rel = source.relative_to(KIT / "template")
        if any(x in {"__pycache__", ".local", "logs"} for x in rel.parts) or source.name in {"state.json", "gitignore.append"}:
            continue
        dest = target / rel
        # Never follow an existing project symlink outside its root.
        if dest.is_symlink() or not dest.resolve().is_relative_to(target):
            raise ValueError(f"Refusing symlink destination: {rel}")
        data = source.read_bytes()
        if str(rel) == "CLAUDE.md":
            data = data.decode().replace("{{PROJECT_NAME}}", name).replace("{{PROJECT_GOAL}}", goal).encode()
        if str(rel) == ".claude/settings.json" and dest.exists():
            old = json.loads(dest.read_text())
            data = (json.dumps(merged_settings(old, json.loads(data)), indent=2) + "\n").encode()
        current = dest.read_bytes() if dest.exists() else None
        if current == data:
            action = "unchanged"
        elif current is None:
            action = "create"
        elif str(rel) == ".claude/settings.json":
            action = "merge"
        elif sha(current) == manifest.get("files", {}).get(str(rel)):
            action = "update"
        elif str(rel) == "CLAUDE.md":
            action = "keep-custom"
        elif a.force:
            action = "replace-with-backup"
        else:
            action = "conflict"
            conflicts.append(str(rel))
        plans.append((rel, data, action))
    # Preflight before writing any files, including first-time v1 upgrades.
    for rel, _, action in plans:
        print(f"{action:20} {rel}")
    if conflicts:
        print("Runtime conflicts: review local edits, then use --force to replace with backups.", file=sys.stderr)
        return 1
    if a.dry_run:
        return 0
    target.mkdir(parents=True, exist_ok=True)
    owned = dict(manifest.get("files", {}))
    for rel, data, action in plans:
        dest = target / rel
        if action == "keep-custom":
            atomic(dest.with_name("CLAUDE.research_OS.md"), data)
            continue
        if action != "unchanged":
            if dest.exists():
                saved = backup / rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, saved)
            atomic(dest, data)
        owned[str(rel)] = sha(data)
    ignore = target / ".gitignore"
    if ignore.is_symlink() or not ignore.resolve().is_relative_to(target):
        raise ValueError("Refusing symlink .gitignore")
    previous = ignore.read_text() if ignore.exists() else ""
    additions = (KIT / "template/gitignore.append").read_text().splitlines()
    missing = [line for line in additions if line and not line.startswith("#") and line not in previous.splitlines()]
    if missing:
        atomic(ignore, (previous.rstrip("\n") + "\n\n# research_OS local runtime\n" + "\n".join(missing) + "\n").encode())
    for launcher in ("projectctl", "start-project"):
        (target / launcher).chmod(0o755)
    atomic(manifest_path, (json.dumps({"schema_version": 2, "files": owned}, indent=2) + "\n").encode())
    ctl = [sys.executable, str(target / "project_ops/projectctl.py")]
    state_path = target / "project_ops/state.json"
    if not state_path.exists():
        subprocess.run(ctl + ["init", "--name", name, "--goal", goal], check=True)
    elif json.loads(state_path.read_text()).get("schema_version") == 1:
        if a.migrate:
            subprocess.run(ctl + ["migrate"], check=True)
        else:
            print("Existing v1 state preserved. Run ./projectctl migrate --dry-run, then ./projectctl migrate.")
    print(f"Installed in {target}. Run ./projectctl doctor and ./projectctl status.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Install error: {exc}")
