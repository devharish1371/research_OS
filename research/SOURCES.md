# Primary-source register

Accessed 3 November 2026, Asia/Kolkata. This is the source set used for a targeted review, not an exhaustive literature bibliography. Reading depth is explicit: an abstract establishes the authors' contribution/claims, not independent validation; method checks cover selected relevant sections, not every experiment. Current documentation and repository pages can change, so implementation should pin versions.

| Source | Reading depth | Use and limitation |
|---|---|---|
| [research_OS baseline](https://github.com/devharish1371/research_OS/tree/09951bf9d4acdc4def9332d6b7ec86736c21b9b3) | Full README, runtime, installer, contract, hooks, skills, tests, design/extension docs; local audit | Direct evidence for repository findings. Six original tests pass; additional audit results are preserved locally. |
| [MemGPT, 2023/2024](https://arxiv.org/abs/2310.08560) | Primary abstract/version metadata | Hierarchical memory and virtual context. Foundational design, not a current leaderboard winner claim. |
| [Lost in the Middle, 2023](https://arxiv.org/abs/2307.03172) | Primary abstract | Positional sensitivity in evaluated models; historical evidence, not a numerical prediction for 2026 models. |
| [LongMemEval, ICLR 2025](https://arxiv.org/abs/2410.10813) | Primary abstract and benchmark description | Extraction, updates, temporal reasoning, multi-session reasoning, abstention. Conversational evaluation needs project-task supplements. |
| [LoCoMo, 2024](https://arxiv.org/abs/2402.17753) | Primary abstract and benchmark description | Long conversational memory; not sufficient to validate reliable experiment execution. |
| [Mem2ActBench, 2026](https://arxiv.org/abs/2601.19935) | Primary abstract; ACL publication search corroboration | Active application of memory to tool use. Motivation for testing task completion and argument grounding. |
| [Mem0, 2025](https://arxiv.org/abs/2504.19413) | Primary abstract and reported evaluation scope | Extract/consolidate/retrieve and graph variant. Cost/speed claims remain author-reported against specified baselines. |
| [Zep, 2025](https://arxiv.org/abs/2501.13956) | Primary abstract | Temporal knowledge graph design. No direct benchmark reproduction in this review. |
| [Graphiti repository](https://github.com/getzep/graphiti) | README architecture and requirements sections | Current graph backend/provider dependencies; more operational components than the stdlib core. |
| [A-Mem, NeurIPS 2025](https://arxiv.org/abs/2502.12110) | Primary abstract/version metadata | Structured linked notes and memory evolution. Scientific conflicts still require explicit preservation. |
| [HippoRAG 2, 2025](https://arxiv.org/abs/2502.14802) | Primary abstract | Associative and graph retrieval. Worth testing on corpus-level multi-hop questions, not assumed necessary for a small ledger. |
| [SimpleMem v3, January 2026](https://arxiv.org/html/2601.02553v3) | Abstract and selected architecture/method sections | Structured compression, online synthesis, intent-aware retrieval. Compression claims are task-dependent. |
| [SimpleMem repository](https://github.com/aiming-lab/SimpleMem) | Current README, evolution/multimodal notes and requirements | Current package is broader than the January paper. Its model/API/runtime requirements matter to adoption. |
| [Hindsight, December 2025](https://arxiv.org/abs/2512.12818) | Primary abstract | Facts, experiences, summaries and beliefs; retain/recall/reflect. Published results are not this project's results. |
| [Hindsight repository](https://github.com/vectorize-io/hindsight) | Current installation/integration sections | Server and embedded deployment options; optional comparison adapter rather than an assumed best default. |
| [AgentMemRec, 26 October 2026](https://arxiv.org/html/2610.34673v1) | Abstract, selection formulation, experimental setup and training/cost caveats | Recent preprint. Learned ranking and evidence-set completeness are promising; subset, development labels and cost boundaries limit headline generalization. |
| [ACE, October 2025](https://arxiv.org/html/2510.04618v1) | Abstract, motivation and method overview | Incremental playbook adaptation; supports source-linked procedure learning rather than repeated monolithic rewriting. |
| [Memory-R1, 2025](https://arxiv.org/abs/2508.19828) | Primary abstract | RL-trained memory operations; later-stage research direction requiring training/evaluation infrastructure. |
| [Hindsight Memory-PRM, August 2026](https://arxiv.org/abs/2608.29605) | Primary abstract | Utility learning from auditable traces/interventions. Distinct work from the Hindsight framework; not evaluated locally. |
| [RLM, revised May 2026](https://arxiv.org/abs/2512.24601) | Primary abstract/version metadata | Programmatic decomposition of large external context. An analysis strategy rather than a persistence/reconciliation solution. |
| [MemOS, revised December 2025](https://arxiv.org/abs/2507.03724) | Primary abstract/version metadata | Provenance/versioning and memory lifecycle across several substrates; broader scope than this repository. |
| [Memory mechanisms survey, March 2026](https://arxiv.org/abs/2603.07670) | Primary abstract/taxonomy | Used to cross-check topic coverage, not as evidence of a specific engine's performance. |
| [LLMLingua-2, 2024](https://arxiv.org/abs/2403.12968) | Primary abstract | Learned extractive compression; evaluate exact-value retention and end-to-end latency before adoption. |
| [MINJA, 2025](https://arxiv.org/abs/2503.03704) | Primary abstract/threat-model description | Demonstrated memory poisoning through interactions; motivates provenance and source/instruction separation. |
| [PagedAttention, 2023](https://arxiv.org/abs/2309.06180) | Primary abstract | KV-cache allocation/serving efficiency; outside a hosted Claude wrapper's direct control. |
| [Titans, 2025](https://arxiv.org/abs/2501.00663) | Primary abstract | Model-level neural memory; requires a model/training-serving change rather than a project-memory plugin. |
| [Anthropic context engineering, September 2025](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents) | Relevant retrieval, compaction and structured-note sections | Primary engineering guidance; not a controlled experiment on this project. |
| [Anthropic Contextual Retrieval, September 2024](https://www.anthropic.com/research/contextual-retrieval) | Method and evaluation overview | Contextual chunking and hybrid search; avoid transferring its percentage gains to this project. |
| [Anthropic long-running harnesses, November 2025](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) | Problem, artifact and progress-management sections | Supports explicit resumable state and verified incremental progress. |
| [Anthropic code execution with MCP, November 2025](https://www.anthropic.com/research/code-execution-with-mcp) | Tool-cost and execution discussion | Reducing schema/result tokens and filtering data before model ingestion. |
| [Claude Code memory docs](https://code.claude.com/docs/en/memory) | Relevant instruction loading/auto-memory sections | Native memory ownership and context overhead; version-sensitive behavior. |
| [Claude Code hooks docs](https://code.claude.com/docs/en/hooks) | Relevant session/Stop/compaction reference sections | Hook contracts and version-sensitive integration; no live Claude session was used to verify the proposed adapter. |
| [Claude Code skills docs](https://code.claude.com/docs/en/skills) | Loading and discovery metadata sections | Body loading differs from discovery overhead. |
| [Claude Code caching docs](https://code.claude.com/docs/en/prompt-caching) | Cache organization and invalidation sections | Cache cost differs from context size; root instructions and conversation updates behave differently. |
| [Letta filesystem evaluation, August 2025](https://www.letta.com/blog/benchmarking-ai-agent-memory/) | Experiment and filesystem-method sections | A useful simple baseline; includes semantic search, and is a vendor-authored study. |
| [SQLite FTS5](https://www.sqlite.org/fts5.html) | Feature/availability and ranking reference | Local lexical retrieval implementation; runtime availability was additionally checked locally. |
| [SQLite WAL](https://www.sqlite.org/wal.html) | Concurrency and deployment constraints | Reader/writer concurrency with one writer; unsuitable as a live shared network-filesystem database. |

Secondary articles and community posts surfaced during discovery were not used to substantiate technical recommendations. No vendor leaderboard was treated as a controlled, universal ranking.
