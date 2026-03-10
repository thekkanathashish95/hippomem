# Architecture Overview

This document is a map of the hippomem codebase for contributors. It describes the major components, their responsibilities, and how they connect.

---

## Package layout

```
hippomem/
├── service.py          — MemoryService: the public API (decode/encode/consolidate/retrieve)
├── config.py           — MemoryConfig: all tunable parameters
├── cli.py              — CLI entry point (hippomem serve)
├── client.py           — HippoMemClient: HTTP client for daemon mode
│
├── decoder/            — decode() path
│   ├── synthesizer.py  — ContextSynthesizer: C1→C2→C3 retrieval cascade
│   ├── llm_ops.py      — DecoderLLMOps: continuation check and synthesis LLM calls
│   ├── schemas.py      — DecodeResult, ContinuationResult, SynthesisResponse
│   ├── local_scan.py   — LocalScanRanker: C2 scoring against active/dormant engrams
│   ├── long_term.py    — LongTermRetriever: C3 FAISS + BM25 + graph expansion
│   ├── scoring.py      — score_engram_with_breakdown(): composite scoring
│   └── context_builder.py — conversation window formatting
│
├── encoder/            — encode() path
│   └── updater.py      — MemoryEncoder: extract, create/update engrams, decay, entity/self ops
│
├── consolidator/       — consolidate() path
│   ├── service.py      — ConsolidationService: decay, demotion scoring
│   ├── llm_ops.py      — ConsolidationLLMOps: entity enrichment, persona synthesis
│   └── background.py   — BackgroundConsolidationTask: asyncio periodic task
│
├── retrieve/           — retrieve() path
│   ├── service.py      — RetrieveService: direct search API (hybrid/FAISS/BM25)
│   └── schemas.py      — RetrieveResult, RetrievedEpisode
│
├── memory/             — memory type logic
│   ├── episodic/       — episode extraction, update, drift detection (LLM ops + schemas)
│   ├── entity/         — entity extraction, profile management, reinforcement
│   └── self/           — self-trait extraction, persona generation (extractor, llm_ops, service)
│
├── infra/              — shared infrastructure
│   ├── llm.py          — LLMService: HTTP client for OpenAI-compatible APIs (retries, backoff)
│   ├── embeddings.py   — EmbeddingService: text-embedding-3-small via same API endpoint
│   ├── call_collector.py — LLMCallCollector: captures all LLM calls within one operation
│   ├── bm25.py         — BM25Retriever: per-user keyword search with TTL-cached index
│   ├── vector/
│   │   ├── faiss_service.py — FAISSService: per-user FAISS index load/search/write
│   │   └── edges.py    — vector-side edge weight helpers
│   └── graph/
│       ├── queries.py  — graph traversal (expansion, clustering neighbors)
│       └── edges.py    — edge weight constants and update helpers
│
├── models/             — SQLAlchemy ORM models
│   ├── engram.py       — Engram: all memory content (episodes, entities, personas, summaries)
│   ├── engram_link.py  — EngramLink: typed weighted graph edges between engrams
│   ├── working_state.py — WorkingState: per-user/session active + dormant engram UUID lists
│   ├── trace.py        — Trace: ephemeral pre-memory weak traces (FIFO, fixed capacity)
│   ├── self_trait.py   — SelfTrait: durable user identity signals accumulated over time
│   ├── llm_interaction.py — LLMInteraction + LLMCallLog: per-operation and per-call LLM traces
│   ├── turn_status.py  — TurnStatus: real-time decode/encode phase tracking (SSE, polling)
│   ├── conversation_turn.py — ConversationTurn: raw user/assistant pairs with memory context
│   └── conversation_turn_engram.py — ConversationTurnEngram: which engrams were decoded/encoded per turn
│
├── schemas/            — shared Pydantic schemas (WorkingStateData, etc.)
├── prompts/            — YAML prompt templates (decoder.yaml, encoder.yaml, consolidator.yaml)
├── db/                 — engine + session factory (SQLite WAL mode enabled)
└── server/             — FastAPI app (daemon mode) + Studio UI static files
```

---

## The four public operations

### decode(user_id, message, ...)

Runs before the LLM call. Returns a `DecodeResult` with a synthesized context string to inject into the system prompt. Executes in a thread pool via `run_in_executor` to keep the caller's event loop free.

Internally runs a **three-level cascade** (C1 → C2 → C3):

- **C1 — continuation check**: asks the LLM whether the current message continues the active topic. If confidence exceeds `continuation_threshold`, returns the current working memory context immediately without search.
- **C2 — local scan**: scores active + dormant engrams against the current message. If the best score exceeds `local_scan_threshold`, synthesizes and returns without global search.
- **C3 — full search**: runs FAISS vector search + BM25 keyword search (merged via RRF), optionally expands results via graph edges, then synthesizes context from the combined results. Also injects linked entity profiles and self-trait persona snapshot if those features are enabled.

Most turns resolve at C1 or C2, keeping latency and cost low. On any failure (DB, FAISS, LLM), decode degrades gracefully to an empty context string and never raises to the caller.

### encode(user_id, user_message, assistant_response, decode_result=...)

Runs after the LLM responds. Updates memory based on what was said. Fully awaited — not fire-and-forget.

Uses a **four-tier fallback** to link each encode to its paired decode:
- **Tier 1**: `decode_result` passed by caller (preferred)
- **Tier 2**: in-process `_last_decode_cache` lookup by `(user_id, session_id)`
- **Tier 3**: DB query for the most recent decode `LLMInteraction` row within a time threshold
- **Tier 4**: unlinked encode (cold-start path)

Steps after linking:
1. Check whether the turn warrants a new engram or updates an existing one
2. Detect topic drift (if the conversation has shifted, create a new engram rather than updating the old one)
3. Extract facts and write to the appropriate engram
4. Update graph edges between related engrams
5. Run entity extraction if enabled
6. Run self-trait extraction if enabled
7. Save raw `ConversationTurn` + `ConversationTurnEngram` linkage rows

### consolidate(user_id)

Maintenance cycle. Run periodically (once per session or on a schedule), not on every turn.

Steps (each wrapped in individual try/except; failures are logged, not raised):
1. **Decay + demotion** — apply relevance score decay to active engrams; demote engrams that fall below the threshold from active → dormant → evicted
2. **Entity enrichment** — if entity extraction is enabled, enrich entity profiles with an LLM summary pass
3. **Stale trait pruning** — remove self-traits with low confidence or no recent observations
4. **Persona synthesis** — if self memory is enabled, generate or update the persona `Engram` from accumulated `SelfTrait` rows

### retrieve(user_id, query, mode="hybrid", top_k=5)

Direct search API. Returns raw `RetrieveResult` with structured episodes, linked entity profiles, and graph-connected neighbors. Independent of the decode/encode lifecycle — use this when you want programmatic access to memory rather than synthesized LLM context.

Unlike `decode()`, `retrieve()` propagates exceptions to the caller rather than degrading silently.

---

## Data model

### Engram
The central table. Every memory — episode, entity, persona, summary — is an `Engram` row with a `kind` discriminator (`episode`, `entity`, `persona`, `summary`). Episodes hold a `core_intent` (topic sentence) and `updates` (fact bullets). Entity engrams use `core_intent` as the canonical name. Persona engrams hold a `summary_text` narrative.

### EngramLink
Typed, weighted graph edges between engrams. Link kinds: `similarity` (FAISS cosine co-embedding), `retrieval` (co-surfaced in synthesis), `temporal` (predecessor/successor), `triadic` (closing a triangle), and `mention` (episode → entity, directional, zero weight).

### WorkingState
Per-user/session active and dormant engram UUID lists, serialized as JSON. This avoids a join-heavy query on every decode — a single row load gives the full working memory state.

### Trace
Ephemeral pre-memory weak traces. FIFO fixed-capacity per `(user_id, session_id)`. A trace is a summarized snippet of a turn that wasn't strong enough to become a full engram yet. Promoted to an `Engram` on a subsequent relevant turn.

### LLMInteraction + LLMCallLog
LLM operation traces surfaced in the Inspector tab. `LLMInteraction` is one row per top-level operation (decode, encode, consolidate), storing aggregated token counts, cost, and latency. `LLMCallLog` is one row per individual LLM API call, storing the full prompt, raw response, and per-call metrics.

### SelfTrait
Durable user identity signals accumulated across turns. One row per `(user_id, category, key)` — for example `(user_id, "preference", "response_format")`. Tracks confidence score, evidence count, and whether the trait is currently active.

### TurnStatus
Real-time decode/encode phase tracking. Written by the server layer for SSE progress events and polling fallback in the Studio Chat tab.

### ConversationTurn + ConversationTurnEngram
Raw conversation pair storage. `ConversationTurn` holds one user/assistant message pair per `encode()` call, with the memory context injected into that turn. `ConversationTurnEngram` links each turn to the engrams that were decoded (recalled) and encoded (written) during it.

---

## Key design decisions

- **`MemoryConfig` is the single source of truth** for all algorithm parameters. Submodules import constants from `config.py` rather than defining their own.
- **`LLMCallCollector` is a context variable**. All LLM calls within a single decode/encode/consolidate operation are captured automatically without explicit passing. This is how the Inspector gets full per-operation traces.
- **`EmbeddingService` is passed directly to `MemoryEncoder`**, not through LLM ops classes — embeddings are infrastructure, not LLM logic.
- **`WorkingState.load()` / `.persist()`** are the only places that touch the working state ORM record. Nothing else writes to it directly.
- **Background consolidation is opt-in**. The default is explicit `consolidate()` calls, which are easier to reason about in most application contexts.
- **Prompts are YAML files** under `hippomem/prompts/`, not hardcoded strings. This makes them easy to inspect and modify without touching Python code.
- **decode() degrades silently; retrieve() does not**. `decode()` always returns a usable (possibly empty) result so a caller's chat turn never fails due to a memory error. `retrieve()` is a direct search API and propagates exceptions because the caller has opted in to raw results.
