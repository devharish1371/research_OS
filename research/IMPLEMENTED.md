# Shipped v2 scope

Date: 3 November 2026. This release implements the local deterministic core recommended by the research review. It makes no claim of universal state-of-the-art answer accuracy.

## Implemented

- Shared schema/evidence validation, acceptance enforcement, cycle checks, record revisions and stale-write guards.
- Evidence on observations and handoffs; explicit drift exit status; changed verified claims cannot silently reuse old evidence.
- Integrity-checked reads, streaming event replay, explicit recovery, idempotent mutation keys and checkpoint verification.
- Complete changed-record events and geometric checkpoints instead of a full-state snapshot for every write.
- SQLite FTS5 indexing, exact lookup, scope/kind filters, lexical fallback and rebuildable local projections.
- Search results use canonical record content even if a projection's stored payload is altered.
- Recording-time snapshots (`--as-of`) and separate applicability filtering (`--valid-at`).
- Versioned observations, procedures, explicitly user-attributed constraints and typed relationships.
- Deterministic context packing, related-evidence bundles, omission counts, and explicit required-context-overflow warnings.
- Archive/restore and tombstones; current tombstones also suppress historical search.
- Metadata-only bounded change detection, multi-turn Stop-marker repair, and checkpointing at compaction.
- Backup-preserving migration of v1 state, observations and handoff evidence.
- Manifest-aware installation, hook merging, custom-contract preservation, replacement backups and dry-run planning.
- Regression/integration suites and a Linux/macOS CI matrix.

## Deliberate differences from the target design

The authoritative journal remains at `project_ops/logs/events.jsonl`, rather than a segmented `events/v2/` tree. `state.json` is rewritten on each mutation; incremental database-only exports and segmented/checkpoint-accelerated replay remain future scaling work. Automatic checkpoints use geometrically spaced versions, not a fixed interval. Replay currently starts at genesis for full chain verification.

Context budgets enforce UTF-8 **bytes**. `--budget-tokens` is explicitly an estimate, not an exact tokenizer. Hooks use 4,800 bytes; ordinary context defaults to 12,000 bytes. Routine status does not hash evidence. `context --check-evidence` hashes selected references and full verification hashes all active references, deduplicating paths within the check.

The change detector scans metadata with time/file limits rather than maintaining a persistent OS watcher. Incomplete scans produce uncertainty. This avoids reading arbitrary file contents, but is not a proof that every possible file change was detected.

Scopes are explicit strings within one project. Local file locking and revision guards support serialized writers on one machine; multi-machine merges and branch-aware namespaces are not automated. Use explicit handoff session IDs for concurrent-session attribution; otherwise a handoff is project-wide.

V1 history is preserved in a byte-identical backup rather than being assigned invented v2 revisions. Migration flags missing acceptance/scope for review. Historical `show` and `history` remain accessible after tombstoning; physical erasure is not implemented.

No separate evidence manifest, automated secret scanner, source ingestion service, LLM extraction/consolidation, embeddings, graph backend, learned ranking, RL memory manager or model-serving optimization is installed. These require independent workload evaluation or a broader deployment choice.

## Measured results

The table below compares synthetic local fixtures. The baseline is the pinned original runtime; v2 fixture records contain additional revision/provenance metadata. This is an implementation comparison, not a model benchmark. See the raw JSON for exact environment, sample timings and v2 source hashes.

| Measurement | Original | v2 |
| --- | --- | --- |
| Status output, 10 blocked tasks | 1,074 bytes | 2,412 bytes |
| Status output, 100 blocked tasks | 8,994 bytes | 4,514 bytes |
| Status output, 1,000 blocked tasks | 89,094 bytes | 4,515 bytes |
| Status output, 10,000 blocked tasks | 899,094 bytes | 4,516 bytes |
| Validation p50, 100 tasks | 0.227 ms | 0.757 ms |
| Validation p50, 1,000 tasks | 20.794 ms | 7.528 ms |
| Validation p50, 5,000 tasks | 617.674 ms | 38.986 ms |
| Snapshot/checkpoint storage after 200 task additions | 5,107,579 bytes | 157,648 bytes |
| State + journal + snapshot/checkpoint storage, same run | 5,236,759 bytes | 430,563 bytes |
| Peak traced Python allocation, 10,000-event fixed-state fixture | 16,699,653 bytes | 26,299 bytes |
| FTS search p50 / p95, 10,000 tasks | Unavailable | 1.383 / 1.599 ms |
| Retrieval including projection sync p50 / p95, same index | Unavailable | 15.172 / 16.288 ms |

Sources: [baseline results](baseline_results.json), [v2 results](v2_results.json). The original status output was unbounded, but Claude hook handling can spill large output to a file; this is not a claim that all baseline bytes were injected into the model.

Warm in-process timings exclude Python CLI startup and model inference. Retrieval synchronization timing includes opening the local index and comparing the state digest. Journal allocation fixtures retain only small logical state while growing history; the streaming result does not imply constant memory for an ever-growing current state. `tracemalloc` measures Python allocations, not peak RSS. Counts based on byte size do not establish actual tokenizer savings.

The metadata scan has its own 250 ms budget. These measurements do not establish a p95 end-to-end Claude startup guarantee, cold-cache filesystem behavior, or end-to-end answer quality. Full-state export and schema validation remain proportional to current state size.

## Validation

Run both suites from the repository root:

```sh
python3 -m unittest discover -s template/project_ops/tests -v
python3 -m unittest discover -s tests -v
```

See [v2_tests.txt](v2_tests.txt) for the local run. Cases include journal truncation/empty history, checkpoint corruption, crash after committed event append, conflicting revisions, concurrent writes, migration backup identity, existing settings, multiple Stop turns, drift on handoff/notes, large and Unicode contexts, temporal search and tombstones.

The original plan's 120-scenario agent evaluation and fixed-model cost/quality comparisons remain future evaluation work. Passing these software tests does not replace those experiments. Optional retrieval engines should be introduced only after they beat this corrected local baseline on representative held-out tasks.
