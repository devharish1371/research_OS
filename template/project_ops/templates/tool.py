#!/usr/bin/env python3
"""One-line purpose of this tool.

Read-only unless a flag says otherwise. Writes results under results/, never secrets.
Usage: ./tools/mytool INPUT [--out results/name.json]
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # project root when this file lives in tools/


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input")
    ap.add_argument("--out", default="results/mytool.json")
    a = ap.parse_args()
    src = (ROOT / a.input).resolve()
    if not src.is_relative_to(ROOT) or not src.is_file():
        raise SystemExit(f"Input must be a file inside the project: {a.input}")
    result = {
        "tool": "mytool", "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "input": str(src.relative_to(ROOT)), "input_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        "denominator": None,   # state exactly what was counted
        "metric": None,
        "protocol": "docs/protocol.md#section",
    }
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {a.out}")  # then: ./projectctl task set ID done --evidence {a.out}


if __name__ == "__main__":
    main()
