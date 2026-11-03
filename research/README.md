# research_OS research and implementation artifacts

Date: 3 November 2026. Original baseline: `09951bf9d4acdc4def9332d6b7ec86736c21b9b3`.

- [Shipped v2 scope, measurements and limits](IMPLEMENTED.md)
- [Historical baseline research report](RESEARCH_REPORT.md)
- [Original target specification](IMPLEMENTATION_SPEC.md)
- [Primary sources and reading depth](SOURCES.md)
- [Baseline audit program](audit_baseline.py) and [results](baseline_results.json)
- [V2 benchmark program](../tools/benchmark_memory.py) and [results](v2_results.json)
- [Original test output](original_tests.txt) and [v2 test output](v2_tests.txt)

The original review was followed by the v2 implementation. The design specification includes experimental ideas and features not shipped; IMPLEMENTED.md and the main README describe the actual release.

```sh
python3 -m unittest discover -s template/project_ops/tests -v
python3 -m unittest discover -s tests -v
python3 tools/benchmark_memory.py
# Historical comparison; requires the original commit in Git history:
python3 research/audit_baseline.py
```

Both benchmarks use synthetic temporary projects and no model API. The baseline audit extracts the pinned original runtime with `git show`, so it remains reproducible after v2 changes. Rerunning either benchmark replaces its result JSON; latency varies by machine and load. The baseline audit documents accepted bad states, rather than asserting that those behaviors are desirable.

No live Claude end-to-end task-success benchmark, paid token-usage benchmark, or public model-memory leaderboard was reproduced. Local test results establish software invariants, not universal state-of-the-art model quality.
