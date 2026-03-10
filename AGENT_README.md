# AGENT_README — hippomem Codebase Orientation

> **This file is for AI coding agents.** Read it first before starting any task. It gives you enough context to orient yourself, understand the system, and know where to look for anything. For deeper detail, follow the codeflow links in Section 11.

---

## 1. What is hippomem (product overview)

hippomem is a brain-inspired persistent memory layer for LLM chat applications. It sits between your chat application and your LLM: before every AI response, it retrieves relevant memories and injects them into the system prompt; after every turn, it encodes what happened into a structured memory store. Over time, it consolidates memories by decaying stale events, clustering related ones, and synthesizing stable user traits — mimicking how the human hippocampus transfers short-term experience into long-term knowledge.

The design is intentionally different from a fact store or RAG pipeline. hippomem models **selective forgetting**: memories decay if unused, get promoted and demoted based on relevance, and are organized as a weighted graph of episodic events — not a flat list of documents. The retrieval cascade (C1→C2→C3) mirrors biological memory: check if the current conversation is still in context, scan working memory, escalate to long-term semantic search only when needed.

The long-term vision is a **shared cross-app memory store**: one persistent memory layer that follows a user across multiple LLM applications. Current stage: **v0.2, functional, alpha-quality**.

---

## 2. Repository map

### Two repos

| Folder | GitHub remote | Purpose |
|--------|--------------|---------|
| `~/Documents/hippomem` | `hippomem_dev` | Dev working area — this repo, all active development |
| `~/Documents/hippomem-prod` | `hippomem` | Clean public snapshot — sync manually before publishing |

All development happens in `hippomem/`. Never assume `hippomem-prod/` is up to date.

### Package structure

```
hippomem/                       # installable Python package
├── service.py                  # MemoryService — public API (decode/encode/consolidate/retrieve)
├── config.py                   # MemoryConfig — all algorithm params + DEFAULT_EDGE_* constants
├── cli.py                      # argparse CLI (hippomem serve, hippomem studio, etc.)
├── client.py                   # HippoMemClient — HTTP client for daemon mode
├── inspector.py                # Inspector — traces and LLM call introspection
├── explorer.py                 # MemoryExplorer — programmatic memory browsing
├── sessions.py                 # Session ID helpers
│
├── decoder/                    # decode() path — C1→C2→C3 retrieval cascade
│   ├── synthesizer.py          # ContextSynthesizer — orchestrates the cascade
│   ├── llm_ops.py              # LLM calls: continuation check, synthesis
│   ├── schemas.py              # DecodeResult, ContinuationResult, SynthesisResponse
│   ├── local_scan.py           # C2 — working memory scan
│   ├── long_term.py            # C3 — FAISS + graph semantic search
│   ├── scoring.py              # Event scoring (semantic × relevance × recency)
│   └── context_builder.py     # Formats retrieved events into context string
│
├── encoder/                    # encode() path — memory update after each turn
│   ├── updater.py              # WorkingMemoryUpdater — main encode orchestrator
│   └── schemas.py              # Encoder-specific schemas
│
├── consolidator/               # consolidate() path — decay, clustering, background task
│   ├── service.py              # ConsolidationService — decay + demotion + clustering
│   ├── llm_ops.py              # ConsolidationLLMOps — cluster summary generation
│   └── background.py          # BackgroundConsolidationTask — asyncio periodic task
│
├── retrieve/                   # retrieve() path — direct memory search API
│   ├── service.py              # RetrieveService — hybrid/FAISS/BM25 search
│   └── schemas.py              # RetrieveRequest/Result schemas
│
├── memory/                     # Three memory type implementations
│   ├── episodic/               # Episodic: facts, events, preferences
│   │   ├── llm_ops.py          # Extraction, update, drift detection
│   │   └── schemas.py
│   ├── entity/                 # Entity: named people, pets, orgs
│   │   ├── llm_ops.py          # Entity extraction + disambiguation
│   │   └── schemas.py
│   ├── self/                   # Self/Persona: stable user traits
│   │   ├── service.py          # SelfMemoryService — trait accumulation + synthesis
│   │   ├── extractor.py        # Extracts traits from turns
│   │   ├── llm_ops.py
│   │   └── schemas.py
│   └── traces/                 # Conversation traces (pre-memory weak signals)
│       └── service.py
│
├── infra/                      # Shared infrastructure
│   ├── llm.py                  # LLMService — OpenAI-compatible HTTP client
│   ├── embeddings.py           # EmbeddingService — text-embedding-3-small
│   ├── bm25.py                 # BM25Retriever — TTL-cached keyword index
│   ├── call_collector.py       # LLMCallCollector — context var, auto-captures LLM calls
│   ├── graph/
│   │   ├── edges.py            # Edge weight calculation (imports from config.py)
│   │   └── queries.py          # Graph traversal + clustering helpers
│   └── vector/
│       ├── faiss_service.py    # FAISSService — per-user FAISS index wrapper
│       ├── embedding.py        # Vector embedding helpers
│       └── edges.py            # Vector-based edge weights
│
├── models/                     # SQLAlchemy ORM models
│   ├── engram.py               # Engram — central memory unit
│   ├── engram_link.py          # EngramLink — weighted typed graph edges
│   ├── working_state.py        # WorkingState — per-user active/dormant UUID lists
│   ├── trace.py                # Trace — ephemeral pre-memory weak traces
│   ├── self_trait.py           # SelfTrait — accumulated identity signals
│   ├── llm_interaction.py      # LLMInteraction + LLMCallLog — Inspector traces
│   ├── turn_status.py          # TurnStatus — real-time decode/encode phase tracking
│   ├── conversation_turn.py    # ConversationTurn — raw turn storage
│   └── conversation_turn_engram.py  # ConversationTurnEngram — turn↔engram associations
│
├── schemas/                    # Shared Pydantic schemas
│   └── working_state.py        # WorkingStateData
│
├── db/                         # Database setup
│   ├── session.py              # create_db_engine, create_session_factory, get_db_session
│   └── base.py                 # SQLAlchemy declarative base
│
├── prompts/                    # YAML prompt templates (not hardcoded strings)
│   ├── decoder.yaml            # C1/C2/C3 prompts
│   ├── encoder.yaml            # Event extraction, drift detection
│   ├── consolidator.yaml       # Clustering, summarization
│   ├── entity.yaml             # Entity extraction + disambiguation
│   └── self_encoder.yaml       # Self-trait extraction
│
└── server/                     # FastAPI daemon + Studio UI
    ├── app.py                  # FastAPI app — all routes
    ├── config_store.py         # Server config persistence
    └── static/                 # Pre-built React UI (source not in this repo)
```

### Documentation map

| Location | Audience | Contents |
|----------|----------|----------|
| `docs/guides/` | Public users | quickstart.md, configuration.md |
| `docs/components/` | Public users | memory-types.md, consolidation.md, studio-ui.md |
| `docs/contributing/` | Contributors | architecture.md |
| `docs/codeflows/` | AI agents / devs | Per-operation code traces (decode, encode, etc.) |
| `docs/whitepaper/` | Design reference | Design rationale, algorithm choices |

---

## 3. The four public operations

### `decode(user_id, message, session_id=None, conversation_history=[]) → DecodeResult`
Called **before** each LLM response. Retrieves relevant memories and returns a `DecodeResult` with a `.context` string to inject into the LLM system prompt. Internally runs a three-stage cascade: **C1** checks if the conversation is a continuation (LLM call, fast); **C2** scans working memory for a high-confidence local hit; **C3** escalates to FAISS + graph semantic search when C1/C2 don't resolve. `decode()` degrades silently — if retrieval fails, it returns empty context rather than raising.

- **Main module**: `hippomem/decoder/synthesizer.py` (`ContextSynthesizer`)
- **Codeflow**: `docs/codeflows/decode.md`

### `encode(user_id, user_message, assistant_response, decode_result=None) → None`
Called **after** each LLM response. Updates the memory store with what happened. Runs extraction, de-duplication, scoring, and working-memory promotion. Also handles entity extraction (people, pets, orgs → `EngramLink(kind=mention)`) and self-trait extraction (`SelfTrait` rows). Uses a 4-tier decode-link strategy to connect new memories to existing ones before persisting.

- **Main module**: `hippomem/encoder/updater.py` (`WorkingMemoryUpdater`)
- **Codeflow**: `docs/codeflows/encode.md`

### `consolidate(user_id) → None`
Called **periodically** (not every turn). Applies decay to all engrams, demotes low-strength memories from working state, clusters related episodic memories into summary engrams, enriches entities, and synthesizes a persona narrative from accumulated `SelfTrait` rows → `Engram(kind=persona)`. Can run as a background asyncio task when `enable_background_consolidation=True`.

- **Main module**: `hippomem/consolidator/service.py` (`ConsolidationService`)
- **Codeflow**: `docs/codeflows/consolidate.md`

### `retrieve(user_id, query, mode="hybrid", top_k=5) → RetrieveResult`
**Optional** direct search API — bypasses the C1/C2/C3 cascade and returns raw engram results. Supports `mode="hybrid"` (FAISS + BM25), `mode="semantic"` (FAISS only), or `mode="bm25"`. Results include per-episode enrichment. Unlike `decode()`, `retrieve()` propagates exceptions rather than degrading silently.

- **Main module**: `hippomem/retrieve/service.py` (`RetrieveService`)
- **Codeflow**: `docs/codeflows/retrieve.md`

---

## 4. Three memory types

**Episodic** — facts, events, preferences, and observations extracted from conversations. Stored as `Engram(kind="episode")` rows. The primary memory type; most encode operations produce episodic engrams.

**Entity** — named individuals (people, pets, organizations) encountered in conversations. Stored as `Engram(kind="entity")` with `EngramLink(kind="mention")` edges connecting entities to the episodes that mention them. Entity extraction runs during `encode()` via `memory/entity/llm_ops.py`.

**Self / Persona** — stable user identity signals accumulated across turns. Raw signals are stored as `SelfTrait` rows (incremental, additive). `consolidate()` periodically synthesizes them into a unified `Engram(kind="persona")` narrative that gets injected into decode context as background context about the user.

---

## 5. Data model (key tables)

| Table | Purpose |
|-------|---------|
| `Engram` | Central memory unit — episodes, entities, personas, summaries; has strength, embedding, kind |
| `EngramLink` | Weighted typed graph edges — kinds: similarity, temporal, retrieval-co-occurrence, triadic, mention |
| `WorkingState` | Per-user/session active + dormant engram UUID lists; single-row cache per user |
| `Trace` | Ephemeral pre-memory weak traces; FIFO buffer, evicted when at capacity |
| `SelfTrait` | Durable identity signals accumulated turn-by-turn (name, habits, preferences, etc.) |
| `LLMInteraction` | One Inspector trace record per operation (decode/encode/consolidate) |
| `LLMCallLog` | One record per individual LLM API call within an operation |
| `TurnStatus` | Real-time decode/encode phase tracking rows; polled via SSE by Studio Chat |
| `ConversationTurn` | Raw turn storage (user + assistant message pairs) |
| `ConversationTurnEngram` | Junction table: which engrams were active/created during which turn |

Full column specs and relationships: `docs/codeflows/models.md`

---

## 6. Infrastructure services

These shared services are wired in `MemoryService.setup()` and passed into subcomponents. Know they exist and where they live before adding any new LLM, embedding, or search logic.

| Service | File | Purpose |
|---------|------|---------|
| `LLMService` | `infra/llm.py` | OpenAI-compatible HTTP client with retries and exponential backoff |
| `EmbeddingService` | `infra/embeddings.py` | Embedding calls (text-embedding-3-small); same endpoint as LLM |
| `FAISSService` | `infra/vector/faiss_service.py` | Per-user FAISS index; lazy-loaded, persisted to disk |
| `BM25Retriever` | `infra/bm25.py` | TTL-cached per-user keyword index; rebuilt from engrams on cache miss |
| `LLMCallCollector` | `infra/call_collector.py` | Context variable; automatically captures all LLM calls within an operation without being passed explicitly |
| Graph queries | `infra/graph/queries.py` | Traversal helpers, clustering queries; used by consolidator and decoder |

---

## 7. Configuration

`MemoryConfig` in `hippomem/config.py` is the **single source of truth** for all algorithm parameters. It is a `@dataclass` with documented fields covering working memory capacity, decay rates, retrieval thresholds, edge weights, consolidation intervals, and feature flags.

Module-level constants (e.g., `DEFAULT_EDGE_SIMILARITY_ALPHA`, `DEFAULT_RETRIEVAL_SEMANTIC_WEIGHT`) at the top of `config.py` are imported by `infra/graph/edges.py` and `infra/vector/edges.py` to stay synchronized.

**Library mode**: instantiate `MemoryConfig()` and pass to `MemoryService(config=...)`.

**Daemon mode**: env vars from `.env` (copy from `.env.example`). The Studio Settings page can write overrides to `hippomem_config.json` (takes priority over `.env`; no restart needed).

**Prompts** are YAML files in `hippomem/prompts/` — never hardcoded strings. Add new prompts there.

Full parameter table: `docs/guides/configuration.md`

---

## 8. Key design decisions / conventions

These are conventions an agent must not accidentally violate:

- **`WorkingState.load()` and `.persist()`** are the only places that read/write the working state ORM record. Never bypass these methods.
- **`EmbeddingService` is passed directly to `WorkingMemoryUpdater`** — not through `LLMMemoryOperations` or any LLM ops class. Keep embedding calls separate from LLM call classes.
- **`LLMCallCollector` is a context variable** — it auto-captures all LLM calls within an operation. You never need to pass it manually; just ensure operations run within the context set up by `MemoryService`.
- **`decode()` degrades silently; `retrieve()` propagates exceptions.** This is intentional: memory retrieval should never break a chat application, but direct search failures should surface to the caller.
- **Background consolidation is opt-in.** `MemoryConfig.enable_background_consolidation` defaults to `False`. Don't enable it in tests.
- **Edge weight constants live in `config.py`** as `DEFAULT_EDGE_*` fields. Import from `config.py` — don't define weights locally in graph or vector modules.
- **Prompts are YAML, not f-strings.** All LLM prompt templates live in `hippomem/prompts/*.yaml`. Load via the prompt loader utility; don't embed prompt text in Python files.

---

## 9. Daemon server (`hippomem serve`)

The daemon exposes hippomem as a local HTTP service with the Studio UI.

- **FastAPI app**: `hippomem/server/app.py` — all routes defined here
- **Static UI**: `hippomem/server/static/` — pre-built React SPA (source not in this repo)
- **CLI entry**: `hippomem serve --port 8719 --host 127.0.0.1` (argparse in `hippomem/cli.py`)
- **Runtime config**: `.env` is the base; `hippomem_config.json` overrides (written by Settings tab)
- **Per-process state**: `_conversation_histories` dict keyed by `user_id`, held in server memory (not persisted across restarts)

**Key API groups:**
- `/api/decode`, `/api/encode` — main memory operations
- `/api/consolidate` — trigger consolidation
- `/api/retrieve` — direct search
- `/api/memory/*` — Memory Explorer (list, get, update, delete engrams)
- `/api/self` — Self traits and persona
- `/api/inspector` — LLMInteraction traces
- `/api/traces` — Ephemeral trace inspection
- `/api/config` (GET/PATCH) — Read/write runtime config
- `/api/health` — Health check

**SSE**: `TurnStatus` rows are written during decode/encode phases. Studio Chat polls them for real-time progress display.

Codeflow: `docs/codeflows/server.md`

---

## 10. Studio UI

The Studio is a React SPA served from `hippomem/server/static/`. The built assets are in this repo; the React source is not.

**7 pages:**
- **Dashboard** — memory stats overview
- **Chat** — send messages, stream SSE `TurnStatus` progress, see memory working in real time
- **Memory Explorer** — list/grid/graph views; D3 force-directed graph of engram relationships
- **Self** — view and manage self traits and persona narrative
- **Inspector (Traces)** — browse `LLMInteraction` + `LLMCallLog` records per operation
- **Settings** — edit config values; writes to `/api/config` PATCH (no restart needed)
- **Personas** — persona narrative history

**Global state**: `user_id` session context is shared across all pages.

**Chat flow**: user sends message → POST `/api/decode` → poll SSE `TurnStatus` → POST `/api/encode` → render response + memory updates.

Codeflow: `docs/codeflows/ui.md`

---

## 11. Codeflow navigation guide

**If you're working on X, start by reading Y:**

| Task | Read first |
|------|-----------|
| decode path (retrieval, C1/C2/C3 cascade) | `docs/codeflows/decode.md` |
| encode path (memory update, entity/self extraction) | `docs/codeflows/encode.md` |
| consolidation (decay, demotion, clustering, background) | `docs/codeflows/consolidate.md` |
| search / retrieve API (hybrid, FAISS, BM25) | `docs/codeflows/retrieve.md` |
| MemoryService lifecycle (setup, wiring, close) | `docs/codeflows/service_lifecycle.md` |
| Database schema, ORM models, relationships | `docs/codeflows/models.md` |
| LLMService, EmbeddingService, FAISS, BM25, graph | `docs/codeflows/infra.md` |
| FastAPI server, API routes, SSE | `docs/codeflows/server.md` |
| HippoMemClient (HTTP client for daemon mode) | `docs/codeflows/client.md` |
| Studio UI (React pages, components, state) | `docs/codeflows/ui.md` |

---

## 12. Tests and development

```
tests/
├── unit/           # 16 files — component-level tests (scoring, FAISS, graph, etc.)
├── integration/    # 5 files  — cross-component tests (consolidation, entity, self, synthesizer)
├── e2e/            # 1 file   — full recall→encode cycle
└── conftest.py     # Shared pytest fixtures
```

**Run tests**: `pytest tests/`

**Linting**: `ruff check .`

**Examples**:
- `examples/demo.py` — interactive library-mode demo
- `examples/chat_server.py` — FastAPI chat server with hippomem integration

**Package management**: `uv` (see `uv.lock`). Install editable: `uv pip install -e .`
