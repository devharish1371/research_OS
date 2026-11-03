# Proposed research_OS v2 implementation

Status: **original target design; core subsequently implemented**. See [IMPLEMENTED.md](IMPLEMENTED.md) for the precise shipped scope, command differences, and deferred features. Date: 3 November 2026. Baseline: `09951bf9d4acdc4def9332d6b7ec86736c21b9b3`.

This specification implements the recommendation in the [research report](RESEARCH_REPORT.md). This is a design record, not the current CLI reference. Consult the repository README for supported commands and flags.

## Scope and defaults

Default deployment: one local project, Python standard-library core, existing Claude Code integration, no transcript reading, no background LLM, no network service, no automatic external messaging. Existing authorized work should continue without redundant approvals. A separate optional package may supply model tokenization, embeddings, reranking, or ingestion.

Expose one storage/validation API to CLI and hooks. Separate modules for models, event storage, evidence, retrieval, context rendering, hooks, and migrations; preserve the small `projectctl` launcher. Keep policy and data independent of harness-specific hook payloads.

## Authoritative storage and projections

```text
project_ops/
  config.json                       # versioned configuration, no credentials
  events/v2/000001.jsonl             # authoritative versioned record operations
  checkpoints/<digest>.json          # verified replay checkpoints
  evidence/manifest.jsonl            # immutable evidence metadata/references
  state.json                        # compatibility export, generated
  legacy/v1/                        # preserved original history during migration
  .local/
    index.sqlite                    # rebuildable record/FTS/link projection
    sessions/<session-id-hash>.json  # per-session acknowledged revisions
    freshness.sqlite                # file metadata and hash cache
    metrics.jsonl                   # bounded local operational measurements
```

The event stream is authoritative. SQLite and `state.json` are projections. Direct edits to projections are rejected or rebuilt from the validated stream; they cannot become silent changes to history. For removable private payloads, store a reference to a content object instead of plaintext in immutable events. That retention mode must be designed before promising hard deletion.

Initial implementation can retain v1 JSON as authority while adding a derived search index. The switch to authoritative v2 events happens only through an explicit migration. Do not run two independently writable authorities.

## Record schema

Common fields:

| Field | Meaning |
|---|---|
| `id`, `revision`, `schema_version` | Stable record identity, monotonic revision, validated schema |
| `kind` | task, claim, decision, observation, handoff, procedure, source |
| `project_id`, `scope` | Project namespace and explicit branch/worktree/entity applicability |
| `text`, `title` | Bounded human-readable content; arbitrary source text stays data |
| `epistemic_status` | verified, reported, hypothesis, proposed, disputed, unknown, withdrawn |
| `lifecycle` | active, superseded, archived, tombstoned; independent of epistemic status |
| `actor`, `source_kind`, `source_ref` | Attribution and origin; distinguish direct user input, tool observation, external document, assistant inference |
| `recorded_at`, `valid_from`, `valid_to` | When stored and when applicable; nullable validity must remain unknown |
| `evidence_ids` | Immutable evidence versions and exact source spans |
| `links` | Typed relationships to exact record revisions where appropriate |
| `last_reviewed_at`, `review_after` | Review scheduling without automatically changing truth status |

Specialized fields include task acceptance, dependencies and completion review; claim metric, value, unit, numerator/denominator, population, protocol and code/data version; decision alternatives and rationale; procedure applicability and validated outcomes. Do not require numeric fields for genuinely nonnumeric claims. Preserve unknown fields from future schema versions only in an explicit compatibility mode.

An illustrative claim (all values are fictional):

```json
{
  "schema_version": 2,
  "id": "C17",
  "revision": 2,
  "project_id": "example-project",
  "kind": "claim",
  "text": "Run R7 achieved 71.2% accuracy on split B.",
  "epistemic_status": "reported",
  "lifecycle": "active",
  "scope": {"dataset": "D1", "split": "B", "run": "R7"},
  "recorded_at": "2026-11-03T00:00:00+05:30",
  "valid_from": null,
  "valid_to": null,
  "source_kind": "tool_observation",
  "source_ref": "run:R7",
  "metric": {"name": "accuracy", "numerator": 3560, "denominator": 5000, "unit": "fraction"},
  "evidence_ids": ["E7"],
  "links": [{"relation": "supersedes", "id": "C17", "revision": 1}]
}
```

An evidence reference includes normalized project-relative path, content SHA-256, observed time, media type, source locator (line/page/table/JSON pointer), producing command or run ID when available, and code/protocol/data version. Do not store credentials in command records. A review status attaches to a specific claim revision and evidence set, not permanently to an ID.

Two records with different datasets or time scopes are not necessarily contradictions. Conflict detection should first check scope; speculative semantic conflict detection creates proposals rather than overwriting records.

## Writes, recovery, and integrity

Each operation carries `operation_id`, actor, timestamp, record ID, expected prior revision, new payload or deterministic patch, prior event hash, and resulting hash. Use deterministic serialization and a documented hash version. A full payload for the changed record is simpler to replay than an informal summary while avoiding snapshots of all records.

Write sequence:

1. Acquire the per-project write lock; read the committed revision and reject a stale expected revision.
2. Validate input, evidence scope, types, dependencies and status transitions. Redact or reject sensitive text before persistence.
3. Append and fsync the complete event. Handle partial writes explicitly; never silently accept a truncated tail.
4. Apply the event to SQLite in a transaction, storing the applied event ID/hash.
5. Atomically update generated exports/manifests if needed. Fsync parent directories where required for the intended crash-durability guarantee.
6. Release the lock and return the committed revision. A retry with the same operation ID is idempotent.

A crash after event commit but before index update is recovered by replaying the committed tail. Corrupt/truncated events stop recovery at the last verified boundary and produce an actionable diagnostic. Recovery policy for a partial trailing record must be explicit and preserve the original damaged bytes. Read commands use a consistent snapshot and advertise the applied revision.

Checkpoint after a configurable event count/byte threshold. Full verification checks the chain and checkpoint digest. Fast startup can use a previously verified prefix and validate the tail, but this does not detect arbitrary historical edits unless the prefix is rechecked or externally anchored. Publish that tradeoff. Tamper-evidence remains different from tamper-proof storage.

Snapshots must not be pruned until v2 replay equivalence, backup, and retention tests pass. Historical evidence may legitimately change or disappear: distinguish historical unavailability from current-claim staleness, and support immutable evidence versions for reproducible research.

## Proposed CLI

| Command | Purpose |
|---|---|
| `projectctl status --budget-tokens 1200` | Bounded working-state packet with omitted counts |
| `projectctl show C17 --revision 2 --json` | Exact bounded record lookup |
| `projectctl search "baseline split" --task T2 --limit 8` | Lexical/structured retrieval |
| `projectctl context --task T2 --query "resume ablation" --budget-tokens 3000` | Task-specific compiled context |
| `projectctl history C17 --limit 10` | Revision/provenance history |
| `projectctl search "split" --as-of 2026-10-01` | Historical applicability; recorded-at filtering is separate |
| `projectctl verify --mode full --json` | Full integrity and evidence audit |
| `projectctl verify --mode quick --json` | Bounded check with explicitly incomplete coverage |
| `projectctl index rebuild` | Rebuild disposable projections from validated history |
| `projectctl checkpoint` | Save a deterministic replay checkpoint |
| `projectctl archive T1 --reason "completed phase"` | Remove from routine retrieval, preserving history |
| `projectctl doctor` | Check installation, SQLite capabilities, schema and hook compatibility |
| `projectctl migrate --dry-run` | Produce migration changes and diagnostics before application |

Preserve existing task/claim/decision/handoff syntax where possible; add revision guards and structured input. Offer file/stdin input for long structured records without shell quoting issues. Return bounded errors with record IDs and remediation pointers.

Verification response example:

```json
{
  "integrity": "ok",
  "freshness": "stale",
  "coverage": "full-current-records",
  "stale_record_ids": ["C17"],
  "historical_unavailable_count": 0,
  "revision": 203,
  "next": "Review C17 against E7; do not automatically refresh its digest."
}
```

Define exits: 0 clean for the requested coverage, 1 integrity/schema/recovery error, 2 current-evidence drift, 3 incomplete check. Quick mode must not claim full freshness. Compatibility flags can retain warning-only behavior temporarily, but documentation and callers must agree.

## Context compiler

Treat rendering as deterministic software. Inputs are current task, query, project/scope, applicable time, budget, and indexed revision. Output contains provenance, state revision, critical constraints, task/acceptance, latest relevant handoff, selected evidence/claims, conflicts, next step, and omitted counts.

Selection rules:

- Pin active user constraints and unresolved integrity warnings before optional memories.
- Include the current task and necessary dependencies; do not merely take the first four inserted tasks.
- Keep opposing evidence together. A disputed record without its conflict marker is an invalid rendering.
- Prefer latest applicable revisions, but preserve older revisions for historical queries.
- Do not conflate assistant proposals with accepted user decisions.
- Group evidence required together before packing; top-k individually similar fragments can leave the answer unsupported.
- Deduplicate by record revision and source span, not only text similarity.
- Use per-field, per-list and total output limits, stable ordering, and explicit continuation handles.
- Show no-match/insufficient-evidence states. Do not fill the budget with unrelated content just because space remains.

Hard token compliance requires a tokenizer/count facility for the selected model. Without one, provide a hard byte limit and `token_count_kind=estimate`; do not present an estimate as a token cap. Maintain headroom for the user request, answer, and future tool calls.

Enforce the harness transport limit as well: current Claude Code replaces hook strings over 10,000 characters with a preview/file pointer. Keep the complete required startup packet below that cap even when its token count is small. See the [hook output contract](https://code.claude.com/docs/en/hooks#json-output).

Cache context by canonical revision, query, task, budget, tokenizer, and applicable scope. Invalidate on changed evidence or relevant constraints. A cache hit is never permission to ignore an expired source or a deletion tombstone.

## Retrieval and memory management

Index explicit records and selected source spans using FTS5 and structured columns. Preserve exact paths, IDs, technical terms, dates, units and dataset names. Chunk literature by semantic structure such as headings, paragraphs, tables and methods/results; identify tables and captions together. Avoid fixed-size chunks that separate a result from its denominator or protocol.

Optional semantic adapter: hash-keyed embedding cache, pinned embedding-model version, explicit dimensionality, bounded candidate generation, rank fusion, and optional small reranker. Re-embed only changed content. Include the embedding model and index version in evaluation output. Run background indexing with a work/time budget and leave the synchronous path usable when it fails.

Consolidation creates a derived summary with source IDs, source revisions and a generation version. Never recursively summarize only the prior summary when originals are available. Run on meaningful record changes or demand; count consolidation tokens in total cost. Procedures should include conditions and observed failures, not just advice.

Archival is reversible and controls retrieval priority; it is not deletion. Tombstoning removes records from candidate generation, cached packets, derived summaries and embeddings. Physical erasure additionally needs content-store/backups/Git policy and cannot be promised by tombstoning alone. Never erase evidence automatically because it was not recently retrieved.

## Hooks and installation

SessionStart: verify required integrity metadata, obtain a small packet, and create/reconcile a session marker. Avoid a full project-content crawl and avoid loading historical archives. Only greet on actual startup if desired; do not repeatedly greet during compaction recovery.

Stop: compare work revision and acknowledged handoff revision for this session. If a reminder retry has `stop_hook_active`, skip the second block but still reconcile safe marker bookkeeping. Handle failure-only sessions and ledger-only changes as well as source edits. Keep reminders bounded.

Compaction: checkpoint already-recorded state using supported, version-tested hook events. A hook must not invent missing progress or imply it inspected a transcript. User-requested capture from conversations requires a separately specified opt-in path.

SessionEnd: persist a minimal marker; correctness cannot depend on this hook firing during a crash.

Change detection: use Git's changed-path inventory where available, but remember that porcelain status alone cannot distinguish two content versions of the same already-dirty file. Track file metadata/content revisions for relevant paths and declared run outputs, with an allowlist, symlink checks, explicit ignored artifacts, and bounded traversal. Tool-event notifications can supplement it without storing commands/prompts. External edits and shell-created artifacts still need reconciliation.

Installer: identify owned files and hook entries in a manifest; merge JSON structurally, keep unrelated hooks/settings, back up changed owned content, provide a dry-run diff, check supported Python/SQLite/harness versions, and separate upgrade from first install. Put mutable local caches under ignored directories. Never embed absolute developer-machine paths in installed templates.

## Regression and evaluation gates

These tests are required because persistence and memory can fail silently:

| Area | Required cases |
|---|---|
| Evidence | Handoff-only/notes-only evidence, duplicate refs, file removed/changed, changed claim text with old evidence, escaping symlinks |
| Validation | Empty/truncated journal, unknown schema, missing fields, duplicate IDs, self/cyclic dependencies, done without acceptance/evidence |
| Recovery | Crash after every append/fsync/index/export stage; idempotent retries; full replay equals current export |
| Hooks | Multiple turns after a block, resume, compaction, missing marker, concurrent sessions, ledger-only progress |
| Budget | Very long single field; 10k blockers/claims; Unicode; oversized mandatory constraints; omission metadata |
| Retrieval | Exact technical identifiers; paraphrases; time ranges; superseded records; conflicting evidence; complete multi-evidence sets |
| Scope/lifecycle | Project/branch isolation; source-as-instruction injection; tombstone propagation; stale summaries/indexes |
| Installation | Existing settings/hooks/contract; repeat install; upgrade/downgrade rejection; paths containing spaces |

Measure cold and warm p50/p95 independently, with fixture size and hardware recorded. Track peak RSS and total storage separately from Python allocation peaks. Publish actual model token counts in end-to-end trials. Make quality/cost evaluation part of the release artifact, not a one-time marketing benchmark.

## Migration procedure

1. Validate v1 and classify existing drift. Stop on corruption; do not silently repair history.
2. Preserve a byte-identical v1 backup and record its manifest hashes.
3. Import current records; recover handoff/observation evidence from matching events. Reconstruct revision history from available snapshots, retaining ambiguity explicitly when exact attribution cannot be established.
4. Create the v2 genesis/import events with links to original IDs and snapshot hashes. Do not fabricate observation dates or metric definitions.
5. Build the SQLite projection and compatibility export; compare all migrated fields/evidence and count records/events.
6. Run replay, retrieval, and hook fixtures in a temporary installation.
7. Switch the installer/runtime to v2; retain a documented rollback path. Preserve any post-migration writes before rollback so they are not lost.

Before shipping, resolve privacy/retention requirements and whether multi-machine concurrent writing is needed. These affect the persistent format; they need not block the initial correctness and bounded-context work.
