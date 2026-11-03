#!/usr/bin/env python3
"""Reproducible local synthetic benchmark; no models, network, or credentials."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "template/project_ops"))
import ledger
import memory


def measure(fn, repeats=20):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    ordered = sorted(samples)
    return {"p50_ms": round(statistics.median(samples), 3), "p95_ms": round(ordered[math.ceil(len(ordered) * .95) - 1], 3), "n": len(samples), "samples_ms": [round(x, 3) for x in samples]}


def main():
    result = {"measured_at": ledger.now(), "python": sys.version, "platform": platform.platform(),
              "method": "Synthetic local fixtures. Function timings are warm in-process unless CLI is named. Token counts and model task success are not measured. tracemalloc is Python allocations, not RSS.",
              "source_sha256": {p.name: ledger.file_hash(p) for p in (REPO / "template/project_ops").glob("*.py")}}
    with tempfile.TemporaryDirectory(prefix="research-os-benchmark-") as temp:
        store = ledger.Store(Path(temp))
        with store.locked():
            store.init("Benchmark", "Synthetic scale check")
        base = store.load()
        context_rows, validation_rows = [], []
        for n in (10, 100, 1000, 10000):
            state = copy.deepcopy(base)
            state["tasks"] = [ledger.revised({"id": f"T{i}", "title": "Blocked experiment", "status": "blocked", "note": "x" * 80, "depends_on": [], "acceptance": "Check fixture"}) for i in range(n)]
            output = memory.packet(store, state)
            context_rows.append({"blocked_tasks": n, "output_bytes": len(output.encode()), **measure(lambda: memory.packet(store, state))})
        for n in (100, 1000, 5000):
            state = copy.deepcopy(base)
            state["tasks"] = [ledger.revised({"id": f"T{i}", "title": "Task", "status": "todo", "depends_on": [f"T{i-1}"] if i else [], "acceptance": "Check fixture"}) for i in range(n)]
            validation_rows.append({"tasks": n, **measure(lambda: ledger.validate(state), repeats=7)})
        result["context_growth"] = context_rows
        result["dependency_validation"] = validation_rows
        state = copy.deepcopy(base)
        state["notes"] = [ledger.revised({"id": f"N{i}", "text": f"Experiment marker{i} dataset calibration outcome", "scope": "benchmark"}) for i in range(10000)]
        idx = memory.Index(store)
        try:
            idx.sync(state)
            result["fts_query_10k_records"] = measure(lambda: idx.search("marker7777"))
            result["retrieval_with_projection_sync_10k"] = measure(lambda: memory.retrieve(store, state, "marker7777"), repeats=10)
            assert idx.search("marker7777")[0]["id"] == "N7777"
        finally:
            idx.close()
        result["indexed_record_count"] = 10001
    with tempfile.TemporaryDirectory(prefix="research-os-write-bench-") as temp:
        store = ledger.Store(Path(temp))
        with store.locked():
            store.init("Audit fixture", "Synthetic audit")
            state = store.load()
            storage = []
            for i in range(1, 201):
                old = copy.deepcopy(state)
                state["tasks"].append(ledger.revised({"id": f"T{i}", "title": "Synthetic task " + "x" * 100, "status": "todo", "depends_on": [], "acceptance": "Check fixture"}))
                store.commit(state, old, "task_add", f"Synthetic task T{i}")
                if i in (25, 50, 100, 200):
                    checkpoints = list(store.checkpoints.glob("*.json"))
                    storage.append({"tasks": i, "state_bytes": store.state_path.stat().st_size, "checkpoint_count": len(checkpoints), "checkpoint_bytes": sum(p.stat().st_size for p in checkpoints), "journal_bytes": store.journal.stat().st_size})
            assert ledger.digest(store.replay()[0]) == ledger.digest(state)
            result["storage_growth"] = storage
    with tempfile.TemporaryDirectory(prefix="research-os-replay-bench-") as temp:
        store = ledger.Store(Path(temp))
        with store.locked():
            store.init("Replay", "Allocation check")
        state = store.load()
        first = next(store.events())
        results = []
        for n in (1000, 10000):
            previous = first["hash"]
            with store.journal.open("w") as stream:
                stream.write(ledger.canonical(first) + "\n")
                for i in range(2, n + 1):
                    state["version"] = i
                    state["updated_at"] = "2026-11-03T00:00:00+00:00"
                    row = {"schema_version": 2, "id": str(i), "seq": i, "at": state["updated_at"], "kind": "note", "summary": "Synthetic journal allocation fixture", "changes": [], "previous": previous, "state_sha256": ledger.digest(state)}
                    row["hash"] = ledger.digest(row)
                    previous = row["hash"]
                    stream.write(ledger.canonical(row) + "\n")
            tracemalloc.start()
            store.replay()
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            results.append({"events": n, "journal_bytes": store.journal.stat().st_size, "peak_traced_python_allocation_bytes_not_rss": peak})
        result["journal_replay_allocations"] = results
    out = REPO / "research/v2_results.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(out)


if __name__ == "__main__":
    main()
