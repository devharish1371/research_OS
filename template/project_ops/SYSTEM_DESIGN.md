# Memory architecture and limits

The event journal is the v2 authority. Its first event contains initial state; subsequent events contain complete changed records and state digests. `state.json` is a generated current-state export. The SQLite database is a rebuildable search projection. Primary artifacts still determine whether recorded claims are correct.

## Write and recovery

The CLI takes one local lock for consistent reads and writes. It validates schema, IDs, task dependency cycles, acceptance/evidence requirements, record revisions, attribution and evidence paths. Writes append/fsync the event before atomic export replacement. An interrupted export is detected; explicit `recover` backs up the previous export and replays the validated journal. Partial or malformed journals are never silently truncated.

Automatic checkpoints occur at state versions 1, 100, 200, 400, 800 and so on. Full verification streams events, reconstructs state and checks checkpoint anchors. Manual checkpoints are optional. The export is still rewritten each mutation, so write work grows with current state. Checkpoints currently support audit/recovery inspection; replay starts at genesis rather than skipping historical integrity checks.

Fast loads cache a verified journal signature using filesystem identity, size and nanosecond mtime/ctime. They compare the export's digest and validate its schema. This detects ordinary edits but is not a cryptographic audit of unchanged historical bytes. The cache is local metadata, not an external trust anchor. Full verification bypasses it. Hash chaining is not proof against someone rewriting the entire history and caches.

## Retrieval and context

SQLite FTS5 indexes current records, with exact IDs prioritized. Structured kind/scope/validity filters supplement lexical search. A lexical fallback supports SQLite builds without FTS5. The index only selects candidates: returned content comes from validated canonical records. Index updates change only modified rows, but synchronize against the current state digest; very large ledgers still incur state processing costs.

`search --as-of` reconstructs a recording-time view; `--valid-at` filters applicability independently. Missing bounds remain unknown. Historical queries are slower because they replay history. Current tombstones suppress historical search too; explicit audit interfaces preserve revisions.

The context compiler pins user constraints, the requested task and the latest handoff. It adds relevant retrieved records, dependencies, ready work and limited blockers/conflicts, grouping related evidence before budget packing. Required entries cannot be silently truncated: overflow is reported. Optional text may be shortened and omissions counted. The budget is UTF-8 bytes, not model tokens. No embeddings, learned ranker or generative memory model runs in the core.

## Evidence and lifecycle

Every record type, including observations and handoffs, can retain evidence. Hashing deduplicates paths within one check and refuses references resolving outside the project. Routine status does not hash evidence. Full verification checks active records; archived, superseded or tombstoned records remain historical data. Selected-context verification checks only included records.

A revised claim cannot automatically inherit verified evidence for changed text/scope/metric/validity/attribution. Explicit new evidence is required. Numeric claims can carry structured measurement metadata. The tool enforces structure, not entailment or scientific validity.

Archival controls routine retrieval. Tombstones remove current and historical search results, not explicit audit access or physical storage. Journal, backup and Git retention make secure erasure a separate design problem. Secrets should never enter the ledger; the regex guard cannot guarantee complete detection.

## Hooks and collaboration

Hooks never read transcripts. SessionStart checks integrity and injects a bounded packet. Stop compares a bounded filesystem-metadata scan and ledger version to its session marker; it acknowledges saved handoffs during a no-loop retry so later turns remain detectable. Missing/incomplete scans mean uncertainty. PreCompact checkpoints saved state. SessionEnd writes only a minimal marker.

Metadata scanning includes large files and project log directories, skips symlinks and generated ledger logs, and stops at 10,000 files or 250 ms. This is a progress reminder, not a full content audit. Handoffs without an explicit session ID apply project-wide; use explicit attribution for concurrent sessions.

Local locking does not merge concurrent Git branches. Use separate branches and explicit reconciliation; never text-merge conflicting journals and assume the chain remains valid. Rebuild local indexes on each machine. Version guards reject stale record edits and operation IDs make retries idempotent.

## Migration

The v1 migration verifies the original journal, backs up state/events/snapshots byte-for-byte, imports current records, recovers handoff evidence and observations, and creates a v2 genesis. Original history remains in the backup rather than being assigned invented v2 revisions. Missing acceptance/scope are flagged for review; invalid legacy dependencies or corrupt history stop migration. Inspect `migrate --dry-run` first.

The installer tracks owned hashes, merges only its hook commands, preserves custom contracts, and backs up overwritten runtime files. Runtime updates and data migrations are separate operations.
