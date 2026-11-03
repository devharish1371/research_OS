#!/bin/sh
# Safe, manifest-aware installer. Use --dry-run before upgrading customized projects.
set -eu
kit=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$kit/install.py" "$@"
