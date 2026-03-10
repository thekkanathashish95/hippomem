# MemoryService Lifecycle Codeflow

> File refs: `S` = service.py, `SN` = sessions.py, `IN` = inspector.py, `EX` = explorer.py, `DB` = db/session.py, `BASE` = db/base.py

---

## Overview

`MemoryService` is the single public entry point for hippomem. It:
- Wires all sub-components at construction time
- Owns the DB engine and session factory (created in `setup()`)
- Holds the in-process decode cache for turn linking
- Exposes thin wrapper methods for sessions, inspector, and explorer queries
- Manages the optional background consolidation task lifecycle

This document covers everything **except** the core decode/encode/consolidate execution paths (those are in decode.md, encode.md, and consolidate.md).

---

## 1. `MemoryService.__init__()` [S:70]

### Sub-components created at init time (before `setup()`)

```python
MemoryService(llm_api_key, llm_base_url, llm_model=None, embedding_model=None, config=None)
```

**Config resolution** (lines 86–90):
- `self.config = config or MemoryConfig()` — use provided or defaults
- If `llm_model` provided: `self.config.llm_model = llm_model`
- If `embedding_model` provided: `self.config.embedding_model = embedding_model`

**Services instantiated** (lines 92–116):

| Attribute | Type | Notes |
|-----------|------|-------|
| `self._llm_svc` | `LLMService` | api_key, base_url, model, retries/delay/timeout from config |
| `self._emb_svc` | `EmbeddingService` | same api_key and base_url as LLM; embedding_model from config |
| `self._episodic_llm` | `EpisodicLLMOps` | receives `_llm_svc` |
| `self._synthesizer` | `ContextSynthesizer` | receives `_llm_svc`, `_emb_svc`, `config` |
| `self._retrieve_svc` | `RetrieveService` | receives `_emb_svc`, `config`; owns its own `FAISSService` + `BM25Retriever` |
| `self._updater` | `MemoryEncoder` | receives episodic_llm, emb_svc, config, entity_llm_ops, self_extractor |

**Feature-gated objects** (lines 111–116):
- `_entity_llm_ops = EntityLLMOps(_llm_svc)` only if `config.enable_entity_extraction`; else `None`
- `_self_extractor = SelfExtractor(SelfLLMOps(_llm_svc))` only if `config.enable_self_memory`; else `None`
- Both are passed into `MemoryEncoder`; `None` means those code paths are skipped

**Process-local state** (lines 131–139):
- `self._engine = None` — set by `_setup_sync()`
- `self._session_factory = None` — set by `_setup_sync()`
- `self._bg_consolidation = None` — set by `_start_background_consolidation()` if enabled
- `self._background_tasks: Set[asyncio.Task]` — tracks fire-and-forget async tasks (currently unused by encode path; reserved)
- `self._last_decode_cache: OrderedDict[Tuple[user_id, session_id], Tuple[turn_id, used_engram_ids]]`
  - Max 500 entries; true LRU via `move_to_end()` + `popitem(last=False)` on overflow
  - Populated by `_decode_sync`; read by `encode()` Tier 2 (read-only, no LRU update on read)

---

## 2. `setup()` + `_setup_sync()` [S:194]

```python
await memory.setup()
```

- Runs `_setup_sync()` in thread pool (`run_in_executor(None, ...)`)
- After sync setup completes: starts background consolidation if `config.enable_background_consolidation`

### `_setup_sync()` [S:201]
1. Resolve DB directory: strip `sqlite:///` prefix from `config.db_url`, resolve path, `mkdir(parents=True, exist_ok=True)`
2. `self._engine = create_db_engine(config.db_url)` — see §2a
3. `Base.metadata.create_all(self._engine)` — creates all tables if they don't exist
   - All ORM models are imported as side-effects in `service.py` (lines 37–42) to ensure they're registered on `Base.metadata` before this call
4. `self._session_factory = create_session_factory(self._engine)`

### `_start_background_consolidation()` [S:208]
- Creates `BackgroundConsolidationTask` with consolidation service, LLM ops, embedding service, interval, feature flags
- Calls `task.start()` → `asyncio.create_task(_run())` — runs in background

---

### 2a. DB Engine — `create_db_engine(db_url)` [DB:6]

- SQLite-specific: `connect_args = {"check_same_thread": False, "timeout": 30}`
  - `check_same_thread=False`: required because decode/encode run in thread pool executors; sessions are created there but must be usable from those threads
  - `timeout=30`: SQLite busy-wait 30 seconds before raising a lock error (WAL mode reduces contention but doesn't eliminate it)
- SQLite pragma event listener: on every new connection, executes `PRAGMA journal_mode=WAL`
  - WAL (Write-Ahead Logging) allows concurrent reads during a write; critical for server mode where decode reads and encode writes can overlap

### 2b. Session Factory — `create_session_factory(engine)` [DB:27]

```python
sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

- `autocommit=False`: explicit transaction control (callers call `db.commit()` or `db.rollback()`)
- `autoflush=False`: prevents implicit flushes before queries (avoids unexpected SQL)

### 2c. `_get_db()` [S:240]

```python
def _get_db(self) -> Session:
    if self._session_factory is None:
        raise RuntimeError("MemoryService not initialized. Call setup() or use 'async with'.")
    return next(get_db_session(self._session_factory))
```

- `get_db_session` is a generator that yields a session and closes it in `finally`
- `next()` advances to the yield point, returning the open session
- **Caller owns the session lifecycle**: every method that calls `_get_db()` must call `db.close()` in its own `finally` block
- Pattern used by all wrapper methods: `db = self._get_db()` → work → `finally: db.close()`

---

## 3. `close()` [S:222]

```python
await memory.close()
```

1. **Drain in-flight encode tasks** (if any): `await asyncio.wait(_background_tasks, timeout=10)` — waits up to 10 seconds
2. **Stop background consolidation**: `await _bg_consolidation.stop()` — cancels + awaits asyncio task
3. **Dispose DB engine**: `await loop.run_in_executor(None, self._engine.dispose)` — closes all connection pool connections

### `__aenter__` / `__aexit__`

```python
async with MemoryService(...) as memory:
    ...
```

- `__aenter__` calls `await self.setup()`; returns `self`
- `__aexit__` calls `await self.close()`; suppresses no exceptions

---

## 4. `update_llm_config()` — Warm Reload [S:141]

```python
memory.update_llm_config(api_key, base_url, llm_model=None, embedding_model=None)
```

Mutates `LLMService` and `EmbeddingService` credentials in-place. Called when `llm_api_key`, `llm_base_url`, `llm_model`, or `embedding_model` changes (e.g. via `PATCH /config`).

| What changes | Where |
|---|---|
| `api_key` | `_llm_svc.api_key`, `_emb_svc.api_key` |
| `base_url` | `_llm_svc.base_url`, `_emb_svc.base_url` (both stripped of trailing `/`) |
| `llm_model` | `config.llm_model`, `_llm_svc.model` (if provided) |
| `embedding_model` | `config.embedding_model`, `_emb_svc.model` (if provided) |

The `AsyncOpenAI` client used by `server/app.py` for the `/chat` endpoint is swapped separately by the server layer.

---

## 5. `update_feature_flags()` — Hot Reload [S:163]

```python
memory.update_feature_flags()
```

Re-syncs all runtime sub-components that cache copies of `MemoryConfig` values. Called after any hot-field patch so changes take effect on the next operation.

**What it does** (in order):

1. **Entity extraction** — if `enable_entity_extraction` is now True and encoder's `entity_llm_ops` is None: create `EntityLLMOps(_llm_svc)` and assign; if now False: set to `None`
2. **Self memory** — same logic for `self_extractor` / `SelfExtractor(SelfLLMOps(_llm_svc))`
3. **ConsolidationService** — recreates from current config via `_get_consolidation_svc()` and assigns to `_updater.consolidation`
4. **BackgroundConsolidationTask** — if task is running: update `_enable_entity_extraction` and `_enable_self_memory` scalars in-place on the live task instance

### `_get_consolidation_svc()` [S:245]

Creates a fresh `ConsolidationService` from current `MemoryConfig`:

```python
ConsolidationService(config=ConsolidationConfig(
    max_active_events=config.max_active_events,
    max_dormant_events=config.max_dormant_events,
    relevance_decay_rate=config.decay_rate_per_hour,
))
```

Called from `update_feature_flags()`, `_consolidate_sync()`, and `_start_background_consolidation()`.

---

## 6. `_persist_interaction()` [S:656]
> Writes one `LLMInteraction` row + one `LLMCallLog` row per LLM call. Called at the end of each sync operation.

```python
_persist_interaction(operation, user_id, collector, db, turn_id, session_id, output)
```

1. **Guard**: `not collector.records` → return immediately (no LLM calls made, nothing to write)
2. `usage = collector.usage` — aggregated `UsageMetadata` (input_tokens, output_tokens, cost)
3. Create and `db.add(LLMInteraction(...))` with:
   - `call_count = len(collector.records)`
   - `total_input_tokens`, `total_output_tokens`, `total_cost`, `total_latency_ms` from `usage` / `collector.total_latency_ms`
   - `turn_id`, `session_id` (nullable — consolidate has no turn_id)
   - `output`: JSON blob (operation-specific; decode: `{used_engram_ids, used_entity_ids, context, reasoning}`; encode: `{action, event_uuid}`; consolidate: `None`)
4. `db.flush()` — assigns the generated `interaction.id` (needed for FK in call logs)
5. For each `LLMCallRecord` in order: `db.add(LLMCallLog(..., interaction_id=interaction.id, step_order=record.step_order))`
6. `db.commit()`
7. On any exception: `logger.error(...)` + `db.rollback()` — persistence failure is non-fatal (operation already completed)

---

## 7. Session Management [S:592, SN]

### 7a. `MemoryService.initialize_session(user_id, session_id)` [S:594]

Thin wrapper: opens a DB session, calls `sessions.initialize_session(user_id, session_id, db)`, closes session.

### 7b. `sessions.initialize_session(user_id, session_id, db)` [SN:21]
> Create empty working state for a new user/session scope. Idempotent.

1. `WorkingState.for_scope(db, user_id, session_id).first()` — check if already exists
2. If exists: return `existing.state_data.model_dump()` — early return (no-op)
3. If not: create `WorkingStateData(working_state_id=f"ws_{user_id}_{session_id or 'global'}", active_event_uuids=[], recent_dormant_uuids=[])`
4. Create `WorkingState` ORM row and `db.add(ws)` → `db.commit()`
5. Return `state_data.model_dump()`

### 7c. `MemoryService.snapshot_to_session(user_id, new_session_id)` [S:609]

Thin wrapper: opens a DB session, calls `sessions.snapshot_to_session(user_id, new_session_id, db)`, closes session.

### 7d. `sessions.snapshot_to_session(user_id, new_session_id, db)` [SN:51]
> Copy global (`session_id=None`) memory state into a new session at session start. Seeds the session with existing long-term context.

1. Query global `WorkingState` (`session_id=None`) for this user
2. If no global state: call `initialize_session(user_id, new_session_id, db)` and return
3. Copy `active_event_uuids` and `recent_dormant_uuids` from global state → new `WorkingStateData`
4. Create new `WorkingState` row for `(user_id, new_session_id)` with copied state data
5. `traces_svc.copy_traces(user_id, None, user_id, new_session_id, db)` — copy all global ETS traces to the new session scope; returns count copied
6. `db.commit()`
7. Logs INFO: `Snapshotted global memory to session {new_session_id}: {N} active, {M} ETS traces`

**Use case**: called at session start when an app wants the new session to inherit the user's existing memory state rather than starting from scratch.

---

## 8. Inspector Wrappers [S:624, IN]

All wrappers follow the same pattern: `db = self._get_db()` → call `inspector.*` → `finally: db.close()`.

### 8a. `list_interactions(user_id, limit=50)` [IN:43]
- Query `LLMInteraction` where `user_id == user_id`, order by `created_at desc`, limit N
- Returns list of summary dicts (no call logs): `{id, user_id, operation, call_count, total_input_tokens, total_output_tokens, total_tokens, total_cost, total_latency_ms, created_at, turn_id, session_id}`

### 8b. `get_interaction_detail(interaction_id)` [IN:57]
- Query `LLMInteraction` by `id`; returns `None` if not found
- Load all `LLMCallLog` rows FK'd to this interaction, ordered by `step_order`
- Returns `{...summary, steps: [{step_order, op, model, messages, raw_response, input_tokens, output_tokens, cost, latency_ms}]}`

### 8c. `get_interaction_by_turn_id(turn_id)` [IN:78]
- Query all `LLMInteraction` rows with this `turn_id`, ordered by `created_at` (decode row first, then encode)
- Loads call logs for each row
- Returns `{turn_id, interactions: [{...summary, output, steps}]}` or `None` if not found

### 8d. `get_stats(user_id)` [IN:106]
- **Engram counts**: group `Engram` by `engram_kind` for this user → `{episode: N, summary: N, entity: N, persona: N, total: N}`
- **Working memory**: load global `WorkingState` (`session_id=None`) → `active_count`, `dormant_count`
- **Usage aggregates**: `COUNT(id)`, `SUM(total_input_tokens)`, `SUM(total_output_tokens)`, `SUM(total_cost)` over all `LLMInteraction` rows for this user
- Returns `{memory: {...}, usage: {total_interactions, total_input_tokens, total_output_tokens, total_tokens, total_cost}}`

---

## 9. Explorer Wrappers [S:556, EX]

All wrappers follow the same pattern: `db = self._get_db()` → call `explorer.*` → `finally: db.close()`.

### 9a. `get_graph_for_explorer(user_id)` [EX:18]
- Load global `WorkingState` → build `active_uuids` and `dormant_uuids` sets
- Query all `Engram` rows for user → serialize as node list: `{id, core_intent, event_kind, relevance_score, is_active, is_dormant, reinforcement_count, created_at, updated_at}`
- Query all `EngramLink` rows for user → serialize as edge list: `{source, target, weight, link_kind}`
  - MENTION links with `weight == 0` get a display default of `0.25` for graph visualization
- Returns `{nodes: [...], edges: [...]}`

### 9b. `get_event_detail_for_explorer(user_id, event_uuid)` [EX:56]
- Load global `WorkingState` → `active_uuids`, `dormant_uuids`
- Query single `Engram` row; return `None` if not found (server layer maps this to HTTP 404)
- Load outgoing + incoming `EngramLink` rows (excluding MENTION links)
- Merge into `{neighbor_id: accumulated_weight}` dict; sort by weight descending
- Returns full event detail: `{id, core_intent, event_kind, updates, summary_text, relevance_score, reinforcement_count, is_active, is_dormant, created_at, updated_at, last_updated_at, edges}`

### 9c. `get_entities_for_explorer(user_id)` [EX:123]
- Query all `Engram` rows where `engram_kind == "entity"` for user, ordered by `reinforcement_count desc`
- Returns `{entities: [{id, canonical_name, entity_type, facts, summary_text, reinforcement_count, created_at, updated_at}]}`
  - `core_intent` serves as `canonical_name`; `updates` serves as `facts`

### 9d. `get_self_traits_for_explorer(user_id)` [EX:146]
- Query all `SelfTrait` rows for user (no filtering — includes inactive traits)
- Returns `{traits: [{category, key, value, previous_value, confidence_score, evidence_count, is_active, first_observed_at, last_observed_at}]}`

---

## 10. Conversation Turn Wrappers [S]

### 10a. `get_messages(user_id, session_id=None, limit=100)` [S:703]
> Returns DB-backed conversation history as a flat message list for Studio chat display.

- Opens a DB session; queries `ConversationTurn` filtered by `user_id` (and optionally `session_id`), ordered by `created_at asc`, limited to `limit`
- Each turn expands to two message dicts:
  - `{id: f"{turn.id}_u", role: "user", content: user_message, memory_context: None, timestamp}`
  - `{id: f"{turn.id}_a", role: "assistant", content: assistant_response, memory_context: turn.memory_context, timestamp}`
- Returns empty list if no turns
- Called by `GET /messages` endpoint; persists across server restarts (unlike old in-memory `message_logs`)

### 10b. `get_turns_for_engram(user_id, engram_id, limit=50)` [S:740]
> Returns all raw conversation turns associated with an engram UUID, ordered oldest-first.

- Opens a DB session; joins `ConversationTurn` + `ConversationTurnEngram` on `turn_id == turn.id`
- Filters by `engram_id` + `user_id`; ordered by `created_at asc`; limited to `limit`
- Each result dict: `{turn_id, session_id, user_message, assistant_response, memory_context, link_type, created_at}`
  - `link_type`: `"decoded"` (engram was surfaced and injected) or `"encoded"` (engram was written into this turn)
- Called by `GET /engrams/{engram_id}/turns` endpoint
