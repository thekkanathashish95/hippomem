# Data Models & Schemas Reference

> File refs:
> ORM: `models/engram.py`, `models/engram_link.py`, `models/working_state.py`, `models/trace.py`, `models/self_trait.py`, `models/llm_interaction.py`, `models/turn_status.py`, `models/conversation_turn.py`, `models/conversation_turn_engram.py`
> Schemas: `schemas/working_state.py`, `decoder/schemas.py`, `encoder/schemas.py`, `memory/episodic/schemas.py`, `memory/entity/schemas.py`, `memory/self/schemas.py`, `retrieve/schemas.py`
> Config: `config.py`
> DB: `db/base.py`, `db/session.py`

---

## 1. Database Layer [db/]

### `db/base.py`

```python
Base = declarative_base()
```

Single SQLAlchemy declarative base shared by all ORM models. All model classes inherit from `Base`. `Base.metadata.create_all(engine)` in `MemoryService._setup_sync()` creates all tables.

### `db/session.py`

**`create_db_engine(db_url)`**:
- SQLite: `connect_args = {"check_same_thread": False, "timeout": 30}`
- SQLite WAL mode: enabled via `event.listens_for(engine, "connect")` → `PRAGMA journal_mode=WAL`
- Non-SQLite: no extra connect args

**`create_session_factory(engine)`**:
- `sessionmaker(autocommit=False, autoflush=False, bind=engine)`

**`get_db_session(session_factory)`**:
- Generator; yields a `Session`; closes in `finally`
- Used by `MemoryService._get_db()` via `next(get_db_session(...))`

---

## 2. ORM Models

### 2a. `Engram` — `models/engram.py` — table: `engrams`

Single source of truth for all memory content. Stores episodic events, entity profiles, and persona engrams.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | String PK | No | UUID, auto-generated |
| `user_id` | String | No | Indexed |
| `engram_id` | String | No | External UUID (used in FAISS, links, working state) |
| `content_hash` | String | Yes | SHA256[:16] of `core_intent + updates`; used to detect re-embed need |
| `engram_kind` | String | No | `EngramKind` enum value |
| `entity_type` | String | Yes | Only for ENTITY: `"person"`, `"organization"`, `"place"`, `"project"`, `"pet"` |
| `core_intent` | String | Yes | Primary text content; topic sentence for EPISODE; canonical name for ENTITY |
| `updates` | JSON | Yes | `List[str]` — fact bullets for EPISODE updates; fact list for ENTITY |
| `summary_text` | Text | Yes | Narrative summary; set by consolidator for ENTITY; persona narrative for PERSONA |
| `reinforcement_count` | Integer | Yes | How many times this engram was used in synthesis |
| `relevance_score` | Float | Yes | Decays exponentially over time; starts at 1.0 |
| `last_decay_applied_at` | DateTime(tz) | Yes | Timestamp of last decay application |
| `created_at` | DateTime(tz) | No | Server default `now()` |
| `updated_at` | DateTime(tz) | No | `onupdate=now()` — updated on any row change |
| `last_updated_at` | DateTime(tz) | Yes | Last time this engram was used in synthesis (set by encoder) |

**Unique constraint**: `(user_id, engram_id)`

**`EngramKind` enum**:
| Value | Meaning |
|-------|---------|
| `episode` | A conversational memory event |
| `summary` | A condensed multi-event summary (future) |
| `entity` | A named entity profile (person, org, place, etc.) |
| `persona` | A synthesized user identity narrative (self memory) |

---

### 2b. `EngramLink` — `models/engram_link.py` — table: `engram_links`

Unified link model for all engram-to-engram relationships: navigational edges (graph traversal) and MENTION links (episode→entity).

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | String PK | No | UUID, auto-generated |
| `user_id` | String | No | Indexed |
| `source_id` | String | No | `engram_id` of source engram |
| `target_id` | String | No | `engram_id` of target engram |
| `link_kind` | String | No | `LinkKind` enum value |
| `weight` | Float | Yes | Edge weight; null/0 for MENTION links |
| `mention_type` | String | Yes | `MentionType` enum value; only set for MENTION links |
| `created_at` | DateTime(tz) | No | Server default `now()` |
| `last_updated` | DateTime(tz) | No | `onupdate=now()` |

**Unique constraint**: `(user_id, source_id, target_id, link_kind)`

**`LinkKind` enum**:
| Value | Directional | Canonical sort | Created by | Weight |
|-------|-------------|----------------|------------|--------|
| `similarity` | No | Yes (sorted UUIDs) | encode: `process_links_realtime()` | Accumulates +0.1 per co-embedding |
| `temporal` | No | Yes | encode: `strengthen_temporal_links()` | Accumulates +0.15 per branch |
| `retrieval` | No | Yes | encode: `strengthen_retrieval_links()` | Accumulates +0.15 per co-synthesis |
| `triadic` | No | Yes | encode: `process_links_realtime()` | Accumulates +0.02 per triangle |
| `mention` | **Yes** (episode → entity) | **No** | encode: `_link_entity_to_episode()` | 0 (no weight) |

**`MentionType` enum**:
| Value | Meaning |
|-------|---------|
| `protagonist` | Entity is the main subject of the episode (priority 0) |
| `subject` | Entity is a key participant (priority 1) |
| `referenced` | Entity is mentioned incidentally (priority 2) |

---

### 2c. `WorkingState` — `models/working_state.py` — table: `working_states`

Tracks which engram UUIDs are currently active or dormant per user/session scope. Content (text, updates) lives in `Engram`; this is UUID lists only.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | String PK | No | UUID |
| `user_id` | String | No | Indexed |
| `session_id` | String | Yes | Indexed; `None` = global scope |
| `state_data` | `WorkingStateDataType` | No | JSON-serialized `WorkingStateData` |
| `created_at` | DateTime(tz) | No | Server default |
| `last_updated` | DateTime(tz) | No | `onupdate=now()` |

**Unique constraint**: `(user_id, session_id)`

**Class methods** (used throughout hippomem instead of raw queries):

| Method | What it does |
|--------|-------------|
| `for_scope(db, user_id, session_id)` | Returns query filtered to scope; handles `session_id IS NULL` vs string |
| `load(db, user_id, session_id)` | Returns `WorkingStateData` or `None` |
| `load_or_create(db, user_id, session_id)` | Returns `WorkingStateData`; returns fresh empty one if no row (not persisted yet) |
| `persist(db, user_id, session_id, state_data)` | Upsert: update existing row or insert new; `db.commit()` |

---

### 2d. `Trace` — `models/trace.py` — table: `traces`

Pre-memory weak conversational traces. FIFO fixed-capacity per `(user_id, session_id)` scope.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | String PK | No | UUID |
| `user_id` | String | No | |
| `session_id` | String | Yes | `None` = global scope |
| `content` | Text | No | Summarized trace text |
| `created_at` | DateTime(tz) | No | Used for FIFO ordering |

**Index**: `ix_traces_scope (user_id, session_id)`

Not part of synthesis, scoring, or working memory. Promoted to full `Engram` when `should_create_new_event()` returns True on a subsequent turn.

---

### 2e. `SelfTrait` — `models/self_trait.py` — table: `self_traits`

Durable user identity signals extracted across conversation turns.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | String PK | No | UUID |
| `user_id` | String | No | Indexed |
| `category` | String | No | `stable_attribute`, `goal`, `personality`, `preference`, `constraint`, `project`, `social` |
| `key` | String | No | Normalized attribute name (e.g. `"occupation"`, `"response_format"`) |
| `value` | Text | No | The trait content |
| `previous_value` | Text | Yes | Prior value when `update` action fires; one level of history |
| `confidence_score` | Float | No | Accumulated LLM-estimated confidence; default 0.0 |
| `evidence_count` | Integer | No | Number of independent observations; default 0 |
| `is_active` | Boolean | No | `True` from first observation (set on insert); set to `False` only by consolidation pruning; immediately re-set to `True` on any subsequent observation |
| `first_observed_at` | DateTime(tz) | Yes | |
| `last_observed_at` | DateTime(tz) | Yes | Updated on every confirm/update |

**Unique constraint**: `(user_id, category, key)` — one row per trait identity

---

### 2f. `LLMInteraction` — `models/llm_interaction.py` — table: `llm_interactions`

One row per top-level operation (decode, encode, or consolidate). Aggregates all LLM calls within that operation.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | String PK | No | UUID |
| `user_id` | String | No | Indexed |
| `operation` | String | No | `"decode"`, `"encode"`, `"consolidate"` |
| `call_count` | Integer | No | Number of LLM calls in this operation |
| `total_input_tokens` | Integer | No | Sum across all calls |
| `total_output_tokens` | Integer | No | Sum across all calls |
| `total_cost` | Float | No | Sum across all calls (0.0 for non-OpenRouter) |
| `total_latency_ms` | Integer | No | Sum across all calls |
| `created_at` | DateTime(tz) | No | Server default |
| `turn_id` | String | Yes | Indexed; links decode + encode rows; null for consolidate |
| `session_id` | String | Yes | Indexed; used for Tier 3 DB fallback scoping |
| `output` | JSON | Yes | Operation-specific output blob |

**`output` JSON by operation**:
- decode: `{used_engram_ids: [...], used_entity_ids: [...], context: str, reasoning: str}`
- encode: `{action: str, event_uuid: str}` (action = update_existing / create_new / etc.)
- consolidate: `null`

---

### 2g. `LLMCallLog` — `models/llm_interaction.py` — table: `llm_call_logs`

One row per individual LLM API call. FK'd to `LLMInteraction`.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | String PK | No | UUID |
| `interaction_id` | String FK | No | → `llm_interactions.id`; indexed |
| `user_id` | String | No | Indexed (denormalized for direct queries) |
| `op` | String | No | Call label (e.g. `"continuation_check"`, `"synthesis"`, `"detect_drift"`) |
| `model` | String | No | Model used for this specific call |
| `messages` | JSON | No | Full prompt messages list |
| `raw_response` | Text | No | First choice content |
| `input_tokens` | Integer | No | |
| `output_tokens` | Integer | No | |
| `cost` | Float | No | |
| `latency_ms` | Integer | No | |
| `step_order` | Integer | No | Sequential within the interaction (0-indexed) |
| `created_at` | DateTime(tz) | No | Server default |

---

### 2h. `TurnStatus` — `models/turn_status.py` — table: `turn_status`


Real-time decode/encode phase tracking. Written by the server layer for SSE progress and polling fallback.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | String PK | No | UUID |
| `turn_id` | String | No | Pre-generated before decode; links both phases |
| `user_id` | String | No | |
| `phase` | String | No | `"decode"` or `"encode"` |
| `status` | String | No | `"running"`, `"done"`, `"error"` |
| `current_step` | Text | Yes | Most recent `on_step` label (not currently updated mid-flight) |
| `started_at` | DateTime(tz) | No | `datetime.now(UTC)` at row creation |
| `updated_at` | DateTime(tz) | No | Updated on status change |
| `completed_at` | DateTime(tz) | Yes | Set when status → `"done"` or `"error"` |
| `error_msg` | Text | Yes | Set on `"error"` status |

**Indexes**: `ix_turn_status_turn_id (turn_id)`, `ix_turn_status_user (user_id, started_at)`

---

### 2i. `ConversationTurn` — `models/conversation_turn.py` — table: `conversation_turns`

Raw conversation pair storage. One row per `encode()` call — stores user/assistant message pair with the memory context injected into that turn.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | String PK | No | UUID, auto-generated |
| `user_id` | String | No | |
| `session_id` | String | Yes | |
| `turn_id` | String | Yes | Links to `LLMInteraction.turn_id` (decode + encode rows) |
| `user_message` | Text | No | |
| `assistant_response` | Text | No | |
| `memory_context` | Text | Yes | `synthesized_context` injected into LLM for this turn |
| `created_at` | DateTime(tz) | No | Server default |

**Indexes**: composite `ix_conv_turns_user (user_id, created_at)`, composite `ix_conv_turns_session (user_id, session_id, created_at)`, `ix_conv_turns_turn_id (turn_id)`

---

### 2j. `ConversationTurnEngram` — `models/conversation_turn_engram.py` — table: `conversation_turn_engrams`

Junction table linking conversation turns to engrams. Enables reverse lookup: given an engram or entity UUID, retrieve all raw conversation turns where it appeared.

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | String PK | No | UUID, auto-generated |
| `turn_id` | String | No | `ConversationTurn.id` (no hard FK — no cascade on engram delete) |
| `engram_id` | String | No | `Engram.engram_id` UUID |
| `link_type` | String | No | `"decoded"` — engram was surfaced by decode; `"encoded"` — engram this turn was written into |
| `user_id` | String | No | Denormalized for user-scoped queries |

**Indexes**: composite `ix_cte_engram_user (engram_id, user_id)`, `ix_cte_turn (turn_id)`

No hard FK on `engram_id` — engrams can be independently deleted without cascading.

---

## 3. Pydantic Schemas

### 3a. `WorkingStateData` — `schemas/working_state.py`

```python
WorkingStateData(
    working_state_id: str = "",
    last_updated: str = "",          # ISO datetime string
    active_event_uuids: List[str] = [],
    recent_dormant_uuids: List[str] = [],
)
```

- Stored as JSON in `WorkingState.state_data` via `WorkingStateDataType` (SQLAlchemy `TypeDecorator`)
- `active_event_uuids`: ordered list; index 0 = most recently active engram
- `recent_dormant_uuids`: ordered list; index 0 = most recently demoted
- `model_config = {"extra": "ignore"}` — forwards-compatible with additional fields

**`WorkingStateDataType`** (custom SQLAlchemy type):
- `process_bind_param`: `WorkingStateData → dict` for DB write
- `process_result_value`: `dict → WorkingStateData` for DB read; handles `None` and raw dict

---

### 3b. `DecodeResult` — `decoder/schemas.py`

```python
@dataclass
DecodeResult(
    context: str,                    # "## Memory Context\n\n{synthesized_context}" or ""
    used_engram_ids: List[str],      # UUIDs of engrams used in synthesis
    reasoning: str,                  # LLM's synthesis reasoning
    synthesized_context: str,        # Raw LLM output without markdown wrapper
    used_entity_ids: List[str] = [], # UUIDs of entity engrams referenced
    turn_id: str = "",               # UUID linking this decode to its encode
)
```

- `context` is what callers inject into the LLM system prompt
- `synthesized_context` is the raw text without the `## Memory Context\n\n` wrapper (stored in inspector)
- Pass the entire `DecodeResult` to `encode()` to ensure all fields are available for turn linking

---

### 3c. `EncodeResult` — `encoder/schemas.py`

```python
@dataclass
EncodeResult(turn_id: str)
```

Return value of `MemoryService.encode()` and `HippoMemClient.encode()`. Single field linking to the decode row.

---

### 3d. Decoder LLM schemas — `decoder/schemas.py`

**`ContinuationResult`** (C1 response):
```python
ContinuationResult(
    decision: str,       # "CONTINUE" | "SHIFT" | "UNCERTAIN"
    confidence: float,   # [0.0, 1.0]
    reasoning: str,
)
```

**`EventUsed`** (within SynthesisResponse):
```python
EventUsed(
    engram_id: str,   # display ID (E1/D1/L1/N1); field alias: "event_id"
    role: str,        # "primary" | "supporting" | "associative"
)
```

**`SynthesisResponse`** (C2/C3 synthesis LLM response):
```python
SynthesisResponse(
    synthesized_context: str,
    events_used: List[EventUsed],
    reasoning: str,
)
```

---

### 3e. Episodic LLM schemas — `memory/episodic/schemas.py`

**`EventUpdateItem`** / **`ExtractEventUpdateResponse`** (extract_event_update LLM response):
```python
EventUpdateItem(
    add_update: bool = False,
    update: Optional[str] = None,
    refined_core_intent: Optional[str] = None,
)
ExtractEventUpdateResponse(updates: List[EventUpdateItem])
```

**`DetectDriftResponse`** (detect_drift LLM response):
```python
DetectDriftResponse(
    decision: Literal["update_existing", "create_new_branch"] = "update_existing",
    reason: Optional[str] = None,
)
```

**`ShouldCreateNewEventResponse`** (should_create_new_event LLM response):
```python
ShouldCreateNewEventResponse(
    should_create: bool = True,
    reason: Optional[str] = None,
)
```

**`GenerateNewEventResponse`** (generate_new_event LLM response):
```python
GenerateNewEventResponse(
    core_intent: str = "New conversation topic",
    updates: List[str] = [],
)
```

**`MaybeAppendToEtsResponse`** (maybe_append_to_ets LLM response):
```python
MaybeAppendToEtsResponse(
    store: bool = False,
    trace_summary: Optional[str] = None,
)
```

---

### 3f. Entity schemas — `memory/entity/schemas.py`

**`ExtractedEntity`** (per-entity output from entity extraction LLM):
```python
ExtractedEntity(
    canonical_name: str,
    entity_type: str,    # "person" | "organization" | "place" | "project" | "pet" | "tool" | "other"
    mention_type: str,   # "protagonist" | "subject" | "referenced"
    facts: List[str],
    significant: bool,   # whether this entity warrants storage
)
```

**`EntityExtractionResult`** (top-level LLM response):
```python
EntityExtractionResult(entities: List[ExtractedEntity] = [])
```

**`DisambiguationResult`** (entity disambiguation LLM response):
```python
DisambiguationResult(
    match: Optional[str] = None,   # "candidate_N" or None (new entity)
    confidence: float = 0.0,
    reason: str = "",
)
```

---

### 3g. Self schemas — `memory/self/schemas.py`

**`ExtractedSelfCandidate`** (per-trait output from self extraction LLM):
```python
ExtractedSelfCandidate(
    category: str,               # "stable_attribute" | "goal" | "personality" | "preference" | "constraint" | "project" | "social"
    key: str,                    # normalized snake_case identifier
    value: str,                  # the trait content
    action: Literal["new", "update", "confirm"],
    confidence_estimate: float,  # [0.0, 1.0]
)
```

**`SelfExtractionResult`** (top-level LLM response):
```python
SelfExtractionResult(candidates: List[ExtractedSelfCandidate] = [])
```

---

### 3h. Retrieve schemas — `retrieve/schemas.py`

Used by `RetrieveService`, `MemoryService.retrieve()`, and `HippoMemClient.retrieve()`.

**`RetrievedEntity`** (dataclass):
```python
RetrievedEntity(
    event_uuid: str,
    core_intent: str,
    score: Optional[float] = None,      # None for mention-sourced entities
    source: str = "mention",
    event_kind: str = "entity",
    entity_type: Optional[str] = None,
    summary_text: Optional[str] = None,
    updates: List[Any] = [],            # fact list from Engram.updates
    cosine_score: Optional[float] = None,
    rrf_score: Optional[float] = None,
    graph_hop: Optional[int] = None,    # 0 = directly linked via MENTION
)
```

**`RetrievedEpisode`** (dataclass):
```python
RetrievedEpisode(
    event_uuid: str,
    core_intent: str,
    score: float,                          # composite score
    source: str,                           # "faiss" | "bm25" | "hybrid" | "graph"
    event_kind: str,                       # "episode" | "summary"
    summary_text: Optional[str] = None,
    updates: List[Any] = [],
    entity_type: Optional[str] = None,
    cosine_score: Optional[float] = None,
    rrf_score: Optional[float] = None,
    graph_hop: Optional[int] = None,       # 0 = primary, 1+ = graph-expanded related
    entities: List[RetrievedEntity] = [],  # MENTION-linked entities
    related_episodes: List[RetrievedEpisode] = [],  # graph-neighbor episodes
)
```

**`RetrieveResult`** (dataclass):
```python
RetrieveResult(
    episodes: List[RetrievedEpisode],
    total_primary: int,                # count of primary (non-graph) episodes
)
```

**`retrieve_result_to_dict(result)`** — serialization helper used by `POST /retrieve` response:
- Converts `RetrieveResult` to JSON-serializable dict, recursing into nested `related_episodes`
- `_episode_to_dict()` handles nested episodes; `asdict()` handles flat `RetrievedEntity`

---

## 4. `MemoryConfig` — `config.py`

All fields are dataclass attributes with defaults. Pass `MemoryConfig(field=value, ...)` to `MemoryService`.

### Working memory capacity

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `max_active_events` | int | 5 | Encoder FIFO demotion, ConsolidationConfig |
| `max_dormant_events` | int | 5 | Encoder demotion overflow, ConsolidationConfig |
| `ephemeral_trace_capacity` | int | 8 | ETS append (max traces per scope) |

### Decay

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `decay_rate_per_hour` | float | 0.98 | `apply_decay_uuids()` (~2%/hr, ~40%/day) |

### Retrieval cascade thresholds

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `continuation_threshold` | float | 0.7 | C1: confidence ≥ this → skip C3 |
| `local_scan_threshold` | float | 0.6 | C2: top_score ≥ this → high_confidence (skip C3) |
| `conversation_window_turns` | int | 2 | C1/C2/C3: how many prior turns in search input |

### Retrieval scoring weights (sum to 1.0)

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `retrieval_semantic_weight` | float | 0.5 | C2 + C3 composite score |
| `retrieval_relevance_weight` | float | 0.3 | C2 + C3 composite score |
| `retrieval_recency_weight` | float | 0.2 | C2 + C3 composite score |

### Edge weights

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `edge_similarity_alpha` | float | 0.1 | SIMILARITY link weight delta |
| `edge_triadic_bonus` | float | 0.02 | TRIADIC link weight delta |
| `edge_retrieval_bonus` | float | 0.15 | RETRIEVAL link weight delta |
| `edge_temporal_bonus` | float | 0.15 | TEMPORAL link weight delta |
| `edge_top_k` | int | 20 | FAISS neighbors for real-time edge processing |
| `edge_min_similarity` | float | 0.75 | Min FAISS score to create a SIMILARITY edge |

### C3 graph expansion

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `enable_graph_expansion` | bool | True | C3: enables neighbor lookup after FAISS/BM25 |
| `graph_hops` | int | 1 | C3: acts as on/off guard (actual expansion is always 1 hop) |
| `max_graph_events` | int | 5 | C3: max neighbors added from graph expansion |

### C3 BM25 / hybrid retrieval

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `enable_bm25` | bool | True | C3: enables BM25 keyword search |
| `bm25_index_ttl_seconds` | int | 300 | BM25 index cache TTL (5 minutes) |
| `rrf_k` | int | 60 | Reciprocal Rank Fusion constant |

### Encoder conversation window sizes

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `updater_detect_drift_turns` | int | 5 | detect_drift recent_turns window |
| `updater_should_create_turns` | int | 5 | should_create + maybe_append_to_ets window |
| `updater_extract_update_turns` | int | 2 | extract_event_update recent_turns window |
| `updater_generate_event_turns` | int | 3 | generate_new_event recent_turns window |
| `updater_history_turns` | int | 20 | Max history trimmed before passing to updater |
| `updater_entity_extract_turns` | int | 4 | Entity extraction recent_turns window |

### LLM / embedding

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `llm_model` | str | `"x-ai/grok-4.1-fast"` | All LLM calls (overridden by server's `llm_model`) |
| `embedding_model` | str | `"text-embedding-3-small"` | All embedding calls |
| `llm_max_retries` | int | 3 | LLMService retry loop |
| `llm_retry_delay` | float | 1.0 | Initial retry backoff seconds (doubles each round) |
| `llm_timeout` | float | 60.0 | Per-request HTTP timeout |

### Storage

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `db_url` | str | `"sqlite:///.hippomem/hippomem.db"` | DB engine creation |
| `vector_dir` | str | `".hippomem/vectors"` | FAISSService base directory |

### Background consolidation

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `enable_background_consolidation` | bool | False | `setup()`: starts background task if True |
| `consolidation_interval_hours` | float | 1.0 | Background task sleep interval |

### Self memory

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `enable_self_memory` | bool | True | Creates SelfExtractor in encoder; enables consolidate steps 3+4 |
| `self_trait_min_confidence` | float | 0.5 | Persona generation: minimum trait confidence to include |

### Entity extraction

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `enable_entity_extraction` | bool | True | Creates EntityLLMOps in encoder; enables consolidate step 2 |

### Turn linking

| Field | Type | Default | Used by |
|-------|------|---------|---------|
| `turn_link_max_age_seconds` | int | 600 | Tier 3 DB fallback: max decode row age to link to encode |

### Module-level constants (importable defaults)

These live at module level in `config.py` and are imported by `scoring.py`, `graph/edges.py`, `vector/edges.py` as their own defaults:

```python
DEFAULT_RETRIEVAL_SEMANTIC_WEIGHT = 0.5
DEFAULT_RETRIEVAL_RELEVANCE_WEIGHT = 0.3
DEFAULT_RETRIEVAL_RECENCY_WEIGHT = 0.2

DEFAULT_EDGE_SIMILARITY_ALPHA = 0.1
DEFAULT_EDGE_TRIADIC_BONUS = 0.02
DEFAULT_EDGE_RETRIEVAL_BONUS = 0.15
DEFAULT_EDGE_TEMPORAL_BONUS = 0.15
DEFAULT_EDGE_TOP_K = 20
DEFAULT_EDGE_MIN_SIMILARITY = 0.75
```
