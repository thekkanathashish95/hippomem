# Server Layer Codeflow

> File refs: `A` = server/app.py, `CS` = server/config_store.py, `CL` = cli.py, `TS` = models/turn_status.py

---

## Overview

The server layer is a FastAPI daemon (`hippomem serve`) wrapping `MemoryService` with:
- **Studio UI** — bundled React SPA served at `/`
- **Chat API** — `/chat` SSE endpoint (integrated decode → LLM stream → encode)
- **Memory API** — `/decode`, `/encode`, `/consolidate` for HippoMemClient integration
- **Config API** — `/config` GET/PATCH with hot/warm reload
- **Inspector API** — `/traces`, `/stats`
- **Explorer API** — `/memory/graph`, `/memory/events`, `/memory/self`, `/memory/entities`

Default port: `8719`. Bound to `127.0.0.1` (localhost only) by default.

---

## 1. CLI Entry Point — `hippomem serve` [CL]

   - `argparse` with `serve` subcommand; args: `--port` (default 8719), `--host` (default `127.0.0.1`)
   - **Logging setup** (before uvicorn starts):
      - Root logger at `INFO`
      - Terminal handler: `WARNING` and above only (stream)
      - File handler: `INFO` and above; `TimedRotatingFileHandler` daily rotation, 7-day retention → `.hippomem/hippomem.log`
      - `uvicorn.access` logger propagation disabled (avoids duplicate request lines)
   - **Banner**: prints Studio URL (OSC 8 hyperlink), API URL, log path to terminal; reads `hippomem` package version via `importlib.metadata`
   - Starts uvicorn: `hippomem.server.app:app`, `log_level="warning"`, `access_log=False`

---

## 2. App Startup — Lifespan [A]

   - `@asynccontextmanager lifespan(app)`:
      - Calls `load_app_config()` → see §3
      - If `api_key` is set: instantiates `MemoryService` + calls `await memory.setup()`, creates `AsyncOpenAI` client
      - If no API key: prints warning with OSC 8 hyperlink to `/settings`; `memory` and `llm_client` remain `None`
      - On shutdown (`yield` exits): `await memory.close()` if memory was initialized
   - Global module-level state: `memory`, `llm_client`, `app_config`, `db_url` (all mutable, updated by PATCH)
   - In-memory per-process state (not persisted):
      - `conversation_histories: dict[str, list[(str,str)]]` — keyed by `user_id`; grows indefinitely during a server run; used only for the `/chat` LLM history window
   - **Note**: message logs are no longer held in-memory. `GET /messages` now reads from the `conversation_turns` DB table via `memory.get_messages()`. Conversation history persists across server restarts.
   - **CORS**: `allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]` — acceptable for localhost; should be restricted if exposed externally

---

## 3. Config Loading [A, CS]

### 3a. `load_app_config()` [A]
> Priority: MemoryConfig defaults → `.env` → `hippomem_config.json`

   - Reads `DB_URL` and `VECTOR_DIR` from env (defaults: `sqlite:///.hippomem/hippomem.db`, `.hippomem/vectors`)
   - Calls `load_config_overlay(db_url)` → reads `hippomem_config.json` if it exists (see §3b)
   - Resolves effective values with priority: JSON overlay > env var > hardcoded default:
      - `llm_api_key`, `llm_base_url` (default: `https://openrouter.ai/api/v1`), `llm_model` (default: `x-ai/grok-4.1-fast`)
      - `chat_model` (default: same as `llm_model`), `system_prompt`, `embedding_model`
   - Constructs `MemoryConfig(llm_model, db_url, vector_dir)`, then calls `_apply_overlay_to_config(config, overlay)`
   - `_apply_overlay_to_config`: applies known MemoryConfig fields from the overlay dict via `setattr`
      - Covered fields: `max_active_events`, `max_dormant_events`, `ephemeral_trace_capacity`, `decay_rate_per_hour`, `continuation_threshold`, `local_scan_threshold`, `retrieval_semantic_weight`, `retrieval_relevance_weight`, `retrieval_recency_weight`, `enable_background_consolidation`, `consolidation_interval_hours`, `enable_entity_extraction`, `enable_self_memory`, `llm_model`, `embedding_model`
   - Returns `(full_config_dict, memory_config, api_key, base_url, llm_model, chat_model, system_prompt)`
   - `full_config_dict`: all exposed fields merged (llm + memory config) — stored in `app_config`

### 3b. `config_store.py` [CS]
> `hippomem_config.json` lives in the same directory as the SQLite DB file.

   - `_db_dir_from_url(db_url)`: strips `sqlite:///` prefix, resolves the file path, returns its parent directory; non-SQLite URLs → `cwd`
   - `config_path(db_url)`: `db_dir / "hippomem_config.json"`
   - `load_config_overlay(db_url)`: reads and JSON-parses the config file; returns `{}` on missing, invalid JSON, or non-dict content
   - `save_config(db_url, config)`: writes full config dict as JSON (indent=2); creates parent dirs if needed

### 3c. `_memory_config_to_dict(cfg)` [A]
> Serializes exposed MemoryConfig fields for the settings UI response.
   - Returns the 14 tunable fields listed above (same set as `_apply_overlay_to_config`, minus `llm_model`/`embedding_model` which are in `full_config_dict` separately)

---

## 4. Schemas [A]

   - **`ChatRequest`**: `user_id: str`, `message: str`
   - **`MessageOut`**: `id: str`, `role: str`, `content: str`, `memory_context: Optional[str]`, `timestamp: str` (ISO UTC)
   - **`ChatResponse`**: `message: MessageOut`
   - **`DecodeRequest`**: `user_id`, `message`, `session_id?`, `conversation_history?: list[list[str]]`
   - **`DecodeResponse`**: `context`, `used_engram_ids`, `used_entity_ids=[]`, `reasoning`, `synthesized_context`, `turn_id=""`
   - **`EncodeRequest`**: `user_id`, `user_message`, `assistant_response`, `decode_result?: DecodeResponse`, `session_id?`, `conversation_history?: list[list[str]]`
   - **`EncodeResponse`**: `status: str`, `turn_id: str`
   - **`ConsolidateRequest`**: `user_id: str`
   - **`RetrieveRequest`**: `user_id`, `query`, `mode="hybrid"`, `top_k=5`, `entity_count=4`, `graph_count=5`, `session_id?`, `exclude_uuids?`, `rrf_k?`, `bm25_index_ttl_seconds?`, `w_sem?`, `w_rel?`, `w_rec?`
   - **`ConfigPatch`**: all config fields as `Optional` — only non-None fields applied

   **Conversion helpers**:
   - `_decode_response_to_result(DecodeResponse) → DecodeResult`: converts HTTP schema to internal `DecodeResult` dataclass
   - `_result_to_decode_response(DecodeResult) → DecodeResponse`: inverse, for `/decode` endpoint response

---

## 5. `/chat` — SSE Chat Endpoint [A]

> `POST /chat` → `StreamingResponse` (media_type `text/event-stream`)
> Full decode → LLM stream → encode pipeline; client sees real-time progress via SSE events.

   - Pre-generates `turn_id = str(uuid.uuid4())` before decode, so TurnStatus row can be written immediately
   - Returns `StreamingResponse` with `Cache-Control: no-cache` and `X-Accel-Buffering: no` headers (prevents nginx buffering)

### 5a. SSE event types (in emission order)

| Type | Payload | When |
|------|---------|------|
| `decode_start` | — | Before decode begins |
| `decode_step` | `{step: str}` | Each decode phase (bridged from `on_step` via `loop.call_soon_threadsafe`) |
| `heartbeat` | — | Every 15s if no events (keep-alive) |
| `decode_done` | `{used_events: int}` | After decode completes |
| `token` | `{delta: str}` | Each streamed LLM token |
| `done` | `{message: MessageOut}` | After LLM stream completes |
| `encode_start` | — | Before encode begins |
| `encode_step` | `{step: str}` | Each encode phase |
| `encode_done` | `{turn_id: str}` | After encode completes |
| `error` | `{detail: str}` | On decode or LLM stream failure (encode errors are logged only) |

### 5b. `generate()` async generator internals

   - `progress_queue: asyncio.Queue` — thread-safe bridge; decode/encode push step events via `loop.call_soon_threadsafe`
   - `_DONE` sentinel object signals task completion to the `drain()` coroutine
   - **`drain(task, heartbeat_secs=15.0)`**: adds `mark_done` done-callback to task; polls queue with 15s timeout; emits heartbeat on timeout; breaks on `_DONE`
   - **Decode phase**:
      - Writes `TurnStatus(phase="decode", status="running")` row via `_ts_write`
      - Creates decode task with `on_step` bridged to progress queue; drains SSE until done
      - Marks TurnStatus row as done via `_ts_done`
      - On failure: emits `error` event and returns (stops generator)
   - **LLM call**:
      - Builds `messages` list: system prompt (with memory context appended if non-empty) + last 6 history turns + current user message
      - History window: `history[-6:]` — last 6 turns (12 messages) as context
      - `llm_client.chat.completions.create(model=chat_model, stream=True)` — uses `chat_model` not `llm_model`
      - Streams tokens; accumulates `assistant_content`
      - Updates `conversation_histories[user_id]` immediately after streaming completes (before encode)
      - Emits `done` event with full `MessageOut`
      - On failure: emits `error` event and returns
   - **Encode phase**:
      - Writes `TurnStatus(phase="encode", status="running")` row
      - Creates encode task; drains SSE until done; marks TurnStatus done
      - Encode errors are only logged (not propagated to client — `encode_done` is still emitted)

---

## 6. TurnStatus [TS]

> DB model for real-time progress tracking and polling fallback.

   - **Columns**: `id` (UUID PK), `turn_id`, `user_id`, `phase` (`decode|encode`), `status` (`running|done|error`), `current_step` (nullable text), `started_at`, `updated_at`, `completed_at` (nullable), `error_msg` (nullable)
   - **Indexes**: `ix_turn_status_turn_id` on `turn_id`; composite `ix_turn_status_user` on `(user_id, started_at)`
   - **`_ts_write(session_factory, turn_id, user_id, phase)`**: creates a `running` row; returns row `id` or `None` on failure; opens/closes its own DB session (does not reuse the MemoryService session)
   - **`_ts_done(session_factory, ts_id)`**: sets `status="done"`, `completed_at=now`, `updated_at=now`; no-op if `ts_id` is None
   - **`GET /turn-status/{turn_id}`**: returns all rows for a turn_id (decode + encode); used as polling fallback if SSE connection drops

---

## 7. Memory API Endpoints [A]

> For HippoMemClient integration — caller owns the decode/encode cycle.

   - **`POST /decode`**: converts `conversation_history: list[list[str]]` → `list[tuple]`; calls `memory.decode()`; returns `DecodeResponse`
   - **`POST /encode`**: converts history + `DecodeResponse` → internal types; calls `memory.encode()`; returns `EncodeResponse(status="ok", turn_id)`
   - **`POST /consolidate`**: calls `memory.consolidate(user_id)`; returns `{"status": "ok"}`
   - **`POST /retrieve`**: accepts `RetrieveRequest`; calls `memory.retrieve()` with all params; returns `retrieve_result_to_dict(result)` — hierarchical `{episodes, total_primary}` structure
      - `episodes[].entities` — MENTION-linked entity engrams per episode
      - `episodes[].related_episodes` — graph-neighbor episodes (1 hop)
      - `source` per episode: `"faiss"` | `"bm25"` | `"hybrid"` | `"graph"`
   - All four: raise `HTTP 503` if `memory is None`

---

## 8. Config API [A]

### `GET /config`
   - Returns `app_config` with `llm_api_key` masked as `"sk-****"`

### `PATCH /config`
   - Accepts `ConfigPatch` (all fields optional); ignores None values and placeholder `"sk-****"` key
   - **Setup mode** (when `memory is None` — no API key on startup):
      - Cold-initializes `MemoryService` + `AsyncOpenAI` from the patch
      - Requires `llm_api_key` (raises `HTTP 400` if absent)
      - On `MemoryService.setup()` failure: raises `HTTP 500`
      - Persists full config via `save_config`
   - **Normal mode** (memory already running):
      - **Hot fields** (everything except `WARM_FIELDS`): mutate `memory.config` in-place via `setattr`; call `memory.update_feature_flags()` to re-sync encoder sub-components, ConsolidationService config, and BackgroundConsolidationTask cached scalars
      - **Warm fields** (`llm_api_key`, `llm_base_url`, `llm_model`, `chat_model`, `embedding_model`): call `memory.update_llm_config()` (updates `LLMService` + `EmbeddingService` in-place); swap `llm_client` to new `AsyncOpenAI` instance
      - Persists full config via `save_config`
   - Returns `{"status": "applied", "config": masked_config}`

### `GET /config/models`
   - Proxies `GET {base_url}/models` (or `https://openrouter.ai/api/v1/models` for OpenRouter URLs)
   - Accepts optional `api_key` and `base_url` query params for pre-save validation
   - Returns `{"valid": true, "models": [{id, name}, ...]}` sorted alphabetically by name
   - Error responses: `{"valid": false, "error": "..."}` for 401, 404, unreachable host, or missing key

---

## 9. Inspector API [A]

   - **`GET /traces?user_id=&limit=50`**: returns `{"interactions": [...]}` via `memory.list_interactions()`
   - **`GET /traces/{interaction_id}`**: returns full interaction detail with LLM call logs; `HTTP 404` if not found
   - **`GET /stats?user_id=`**: returns memory counts + usage aggregates via `memory.get_stats()`

---

## 10. Memory Explorer API [A]

   - **`GET /memory/graph/{user_id}`**: event graph nodes + edges for D3 visualization
   - **`GET /memory/events/{user_id}/{event_uuid}`**: full event detail; `HTTP 404` if not found
   - **`GET /memory/self/{user_id}`**: all self traits for the self-memory view
   - **`GET /memory/entities/{user_id}`**: all entity engrams
   - All four: raise `HTTP 503` if `memory is None`

---

## 11. Other Endpoints [A]

   - **`GET /health`**: `{status: "ok", setup_required: bool, memory_model: str, chat_model: str}` — `setup_required=True` when no API key
   - **`GET /messages?user_id=&session_id=&limit=100`**: DB-backed conversation history; calls `memory.get_messages(user_id, session_id, limit)` → reads from `conversation_turns` table; each turn expands to two entries (user then assistant); returns `[]` if `memory is None`. Persists across server restarts.
   - **`GET /engrams/{engram_id}/turns?user_id=&limit=50`**: returns all raw conversation turns linked to the given engram UUID via `ConversationTurnEngram`; calls `memory.get_turns_for_engram(user_id, engram_id, limit)`; raises `HTTP 503` if `memory is None`; ordered oldest-first; each entry includes `link_type` (`"decoded"` | `"encoded"`)

---

## 12. Studio UI — Static File Serving [A]

   - `STATIC_DIR = Path(__file__).parent / "static"` — bundled React build co-located with `app.py`
   - Setup is skipped (with warning) if `STATIC_DIR` or `index.html` doesn't exist
   - `/assets/*` — mounted as `StaticFiles` directory
   - `GET /` → serves `index.html`
   - `GET /{path:path}` — SPA catch-all:
      - If `path.split("/")[0]` is in `_API_PREFIXES` → raises `HTTP 404` (prevents mistyped API paths from silently returning index.html)
      - If file exists at `STATIC_DIR / path` → serves that file
      - Otherwise → serves `index.html` (SPA client-side routing)
   - `_API_PREFIXES`: `{chat, decode, encode, consolidate, retrieve, messages, engrams, health, traces, stats, memory, config, turn-status}`

---

## Config field taxonomy

| Field | Category | Effect of change |
|-------|----------|-----------------|
| `llm_api_key` | Warm | Swaps `LLMService` + `EmbeddingService` credentials + new `AsyncOpenAI` |
| `llm_base_url` | Warm | Same as above |
| `llm_model` | Warm | Updates `LLMService.model` + `MemoryConfig.llm_model` |
| `chat_model` | Warm | Updates `app_config["chat_model"]` only (used in `/chat` LLM call) |
| `embedding_model` | Warm | Updates `EmbeddingService.model` + `MemoryConfig.embedding_model` |
| `enable_entity_extraction` | Hot | Re-creates `entity_llm_ops` on encoder |
| `enable_self_memory` | Hot | Re-creates `self_extractor` on encoder |
| `enable_background_consolidation` | Hot | Updates `BackgroundConsolidationTask` cached scalar |
| All other MemoryConfig fields | Hot | Written directly to `memory.config` in-place |

---

## Key design notes

- **`conversation_histories`** is process-local (in-memory dict). Server restart clears it. History is used for `/chat` only (LLM context window); `/decode` and `/encode` callers manage their own history.
- **`GET /messages`** is now DB-backed via `ConversationTurn` table — persists across restarts. Replaces the old in-memory `message_logs` dict.
- **`chat_model` vs `llm_model`**: `llm_model` is used by hippomem internally (C1, synthesis, encode LLM calls). `chat_model` is used only for the `/chat` endpoint's user-facing response. They can differ.
- **Encode errors in `/chat`**: logged but not propagated — `encode_done` is always emitted so the client doesn't hang. The chat response has already been delivered to the user by then.
- **`_ts_write` / `_ts_done`** open their own DB sessions (not the MemoryService session), because decode and encode run in thread pool executors with their own sessions.
