#!/bin/sh
# Install the Claude project kit into a folder.
# Usage: ./install.sh [TARGET_DIR] [--name "Project Name"] [--goal "One sentence goal"] [--force]
# Existing files are never overwritten unless --force; CLAUDE.md and .gitignore are merged/kept.
set -eu
kit=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
target=.; name=""; goal=""; force=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --name) name=$2; shift 2;; --goal) goal=$2; shift 2;; --force) force=1; shift;;
    -h|--help) sed -n 2,4p "$0"; exit 0;; *) target=$1; shift;;
  esac
done
mkdir -p "$target"; target=$(CDPATH= cd -- "$target" && pwd)
[ -n "$name" ] || name=$(basename "$target")
[ -n "$goal" ] || goal="(set the one-sentence goal)"
command -v python3 >/dev/null || { echo "python3 required" >&2; exit 1; }

copy() { # src rel
  dest="$target/$2"
  if [ -e "$dest" ] && [ "$force" -eq 0 ]; then echo "keep   $2 (exists)"; return; fi
  mkdir -p "$(dirname "$dest")"; cp -p "$1" "$dest"; echo "write  $2"
}
( cd "$kit/template" && find . -type f ! -name gitignore.append ! -name '*.pyc' ! -path '*/__pycache__/*' ! -path '*/project_ops/.local/*' ! -name state.json ! -path '*/project_ops/logs/*' | sed 's|^\./||' ) |
while IFS= read -r rel; do copy "$kit/template/$rel" "$rel"; done

# Fill CLAUDE.md placeholders only if we just wrote it from the template.
if grep -q '{{PROJECT_NAME}}' "$target/CLAUDE.md" 2>/dev/null; then
  NAME=$name GOAL=$goal python3 - "$target/CLAUDE.md" <<'PY'
import os, sys
p = sys.argv[1]; s = open(p).read()
open(p, "w").write(s.replace("{{PROJECT_NAME}}", os.environ["NAME"]).replace("{{PROJECT_GOAL}}", os.environ["GOAL"]))
PY
fi
touch "$target/.gitignore"
grep -q 'project_ops/.local/' "$target/.gitignore" || { cat "$kit/template/gitignore.append" >> "$target/.gitignore"; echo "update .gitignore"; }
chmod +x "$target/projectctl" "$target/start-project"
if [ ! -f "$target/project_ops/state.json" ]; then ( cd "$target" && ./projectctl init --name "$name" --goal "$goal" ); fi
echo; echo "Installed in $target. Next: edit CLAUDE.md 'Project facts', run ./projectctl status, then ./start-project"
