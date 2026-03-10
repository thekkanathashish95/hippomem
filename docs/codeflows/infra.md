# Infrastructure Layer Codeflow

> File refs: `LL` = infra/llm.py, `EM` = infra/embeddings.py, `FS` = infra/vector/faiss_service.py, `CC` = infra/call_collector.py, `GQ` = infra/graph/queries.py

---

## Overview

The infrastructure layer provides four shared services used across all hippomem operations:

| Service | File | Used by |
|---------|------|---------|
| `LLMService` | `infra/llm.py` | All LLM ops (retriever, encoder, consolidator) |
| `EmbeddingService` | `infra/embeddings.py` | FAISS indexing, C2/C3 query embedding |
| `FAISSService` | `infra/vector/faiss_service.py` | C2 local scan, C3 long-term retrieval, encode FAISS writes |
| `LLMCallCollector` | `infra/call_collector.py` | Inspector persistence (decode/encode/consolidate) |
| Graph queries | `infra/graph/queries.py` | C3 graph expansion, consolidation clustering |

All are instantiated in `MemoryService.__init__` and passed down; none hold DB sessions.

---

## 1. `LLMService` [LL]

### 1a. Construction

```python
LLMService(api_key, base_url, model, max_retries=3, retry_delay=1.0, timeout=60.0)
```

- `base_url` is stripped of trailing `/` on init
- `model` is overridable per-call (defaults to instance model)
- `max_retries`, `retry_delay`, `timeout` are from `MemoryConfig` (`llm_max_retries`, `llm_retry_delay`, `llm_timeout`)

### 1b. `_make_request()` — shared HTTP layer [LL:51]

All LLM calls route through `_make_request`. It handles:

**Payload construction**:
- Always: `model`, `messages`, `temperature`
- Optional: `tools` + `tool_choice` (if set), `max_tokens` (if set), `response_format` (if set)
- URL: `{base_url}/chat/completions`

**Retry loop** (`attempt in range(1, max_retries+1)`):
- `requests.post(url, headers, json=payload, timeout=timeout)`
- On success: parse JSON, check for `"error"` key in response body → raise `LLMError`
- Timing: `time.perf_counter()` wraps the request; ms logged at DEBUG level
- **4xx errors (non-429)**: raise `LLMError` immediately — no retry (client error, retrying won't help)
- **429 and 5xx**: retry with exponential backoff (`delay *= 2` each round)
- **Network errors** (`RequestException`): also retry
- After all retries exhausted: `logger.error(...)` + raise `LLMError`

**Call collector integration** (side-effect, after every successful call):
- Imports `_current_collector` context var and checks if a collector is active
- Reads `usage.prompt_tokens`, `usage.completion_tokens`, `usage.cost` from response body
- Creates `LLMCallRecord(op, model, messages, raw_response, input_tokens, output_tokens, cost, latency_ms)`
- Appends to `collector.add(record)` — see §4

### 1c. `chat()` [LL:155]
> Plain text response. Returns `None` if the model only returned tool calls.

- Calls `_make_request()` (no `response_format`)
- Extracts `choices[0].message.content`
- Returns content string or `None`
- Raises `LLMError` if no choices

### 1d. `chat_structured()` [LL:184]
> Structured JSON output. Returns a validated Pydantic model instance.

Used by every LLM operation in hippomem (C1 check, synthesis, detect_drift, extract_update, etc.).

1. `schema = response_model.model_json_schema()` — build JSON Schema from Pydantic model
2. Inject `"additionalProperties": False` if not already present (required for strict mode)
3. Wrap as `response_format = {"type": "json_schema", "json_schema": {"name": ..., "strict": True, "schema": schema}}`
4. Call `_make_request(..., response_format=response_format)`
5. Extract `content = choices[0].message.content`
6. Guard: empty content → raise `LLMError("Empty content in structured response")`
7. `json.loads(content)` → raise `LLMError` on `JSONDecodeError`
8. `response_model.model_validate(parsed)` → returns validated instance
- All errors (`LLMError`, JSON parse, validation) propagate to caller — callers wrap in try/except

**`op` parameter**: a string label passed through to `_make_request` for logging and collector record tagging (e.g. `"continuation_check"`, `"synthesis"`, `"detect_drift"`)

---

## 2. `EmbeddingService` [EM]

### 2a. Construction

```python
EmbeddingService(api_key, base_url, model="text-embedding-3-small", max_retries=3, retry_delay=1.0, timeout=60.0)
```

- Shares the same `api_key` and `base_url` as `LLMService` (set from `MemoryService.__init__`)
- `embedding_model` comes from `MemoryConfig.embedding_model`

### 2b. `_make_request()` [EM:47]

- URL: `{base_url}/embeddings`
- Payload: `{"model": model, "input": input_data}` — `input_data` is a string or list of strings
- Retry logic identical to `LLMService._make_request`: exponential backoff, 4xx no-retry, 429/5xx retry
- **Does NOT integrate with `LLMCallCollector`** — embedding calls are not logged in Inspector

### 2c. `embed(text)` [EM:88]
> Single text → float vector.

- Guard: empty/whitespace text → raise `EmbeddingError("Cannot embed empty text")`
- Calls `_make_request(text.strip(), model)`
- Returns `data["data"][0]["embedding"]` — a `List[float]`
- Raises `EmbeddingError` if `data["data"]` is empty

### 2d. `embed_batch(texts)` [EM:98]
> List of texts → list of float vectors, in input order.

- Strips whitespace from each text (replaces empty → `""`)
- Guard: empty list → return `[]` immediately (no API call)
- Calls `_make_request(texts, model)` — sends all texts as a single API call
- **Order preservation**: sorts `data["data"]` by `item["index"]` before extracting embeddings
  - OpenAI-compatible APIs return embeddings in an arbitrary order with an `index` field; sorting restores input order
- Returns `List[List[float]]`

---

## 3. `FAISSService` [FS]

### 3a. Construction

```python
FAISSService(base_dir=".hippomem/vectors")
```

- `base_dir` is created if it doesn't exist (`mkdir parents=True, exist_ok=True`)
- One index file per user: `{base_dir}/{safe_user_id}.index`
  - `safe_user_id` = `re.sub(r"[/\\:]+", "_", user_id)` — filesystem-safe

### 3b. UUID → FAISS int64 mapping [FS:21]

`_event_uuid_to_faiss_id(engram_id: str) → np.int64`

FAISS uses integer IDs; UUIDs must be deterministically mapped:
1. Strip hyphens from UUID, take first 16 hex chars → parse as int64
2. Mask: `& 0x7FFF_FFFF_FFFF_FFFF` — ensures positive int64 (FAISS requires non-negative)
3. Fallback (non-UUID strings): SHA256 hash → first 8 bytes → same mask

This mapping is applied consistently in `add_vector`, `remove_vector`, `get_vector`, `search` (exclude), and `build_id_to_uuid_map`.

### 3c. Vector normalization [FS:31]

`_normalize(v: np.ndarray) → np.ndarray`

- L2-normalizes vectors before storing/searching
- Enables inner-product FAISS (`IndexFlatIP`) to compute cosine similarity
- Zero-norm vectors: replaced with `1.0` norm to avoid division by zero
- Always reshapes to `(1, dim)` before normalizing, then squeezes back

### 3d. `load_index(user_id)` [FS:51]
> Load from disk. Returns `None` if file not found or read fails.

- Reads `{base_dir}/{safe_user_id}.index` via `faiss.read_index()`
- Returns `None` on file-not-found or any exception (logged as WARNING)
- Callers that need a guaranteed index use `get_or_create_index()`

### 3e. `save_index(user_id, index)` [FS:62]
> Persist to disk. **Atomic write**: write to `.index.tmp`, then `rename` to `.index`.

- Writes to temp file first; if write succeeds, `tmp.replace(path)` is atomic on POSIX
- `finally` block: removes temp file if it still exists (write failed mid-way)
- Errors logged as ERROR; never raises (save failure is non-fatal — index is in memory)

### 3f. `get_or_create_index(user_id)` [FS:78]
> Load existing or create empty `IndexIDMap2(IndexFlatIP(EMBEDDING_DIM))`.

- Calls `load_index()`; returns it if found
- Otherwise: creates `base = faiss.IndexFlatIP(1536)` + wraps in `faiss.IndexIDMap2(base)`
  - `IndexFlatIP`: inner product search (cosine via normalized vectors)
  - `IndexIDMap2`: maps FAISS int64 IDs to vectors; supports `remove_ids` and `reconstruct`
- Called during encode (Path A content update, Path B new event creation) where an index is always needed
- Distinguished from `load_index()` (used in C2/C3 retrieval where `None` is a valid signal to skip)

### 3g. `add_vector(event_uuid, vector, index, remove_if_exists, user_id)` [FS:87]

1. `faiss_id = _event_uuid_to_faiss_id(event_uuid)`
2. If `remove_if_exists=True`: `index.remove_ids([faiss_id])` — silently ignores if not present
3. `vec = np.array([vector], dtype=np.float32)` → `_normalize(vec)` → reshape to `(1, dim)` if needed
4. `index.add_with_ids(vec_norm, [faiss_id])`
5. Logs DEBUG `add: user=... engram=...` if `user_id` provided
- Called by `add_to_faiss_realtime()` in `infra/vector/embedding.py` (which handles the DB content_hash update)

### 3h. `remove_vector(event_uuid, index)` [FS:110]
> Idempotent removal. Silently ignores if not present.

### 3i. `get_vector(event_uuid, index)` [FS:118]
> Reconstruct stored vector by UUID. Returns `None` if not found.

- Guard: `index is None or index.ntotal == 0` → return `None` immediately
- `index.reconstruct(int(faiss_id))` → cast to `np.float32` → return as `List[float]`
- Returns `None` on any exception (e.g. ID not in index)
- Used in C2 (`_get_event_embeddings`) to prefer stored vectors over re-embedding

### 3j. `search(query_vector, k, index, exclude_event_uuid, user_id)` [FS:129]
> ANN search. Returns `[(faiss_id, similarity), ...]` up to `k` results.

1. Guard: `index.ntotal == 0` → return `[]`
2. `vec = np.array([query_vector], dtype=np.float32)` → `_normalize(vec)` → reshape
3. `search_k = min(k + 1, index.ntotal)` — request one extra to account for possible self-exclusion
4. `index.search(vec_norm, search_k)` → `(distances, ids)` arrays of shape `(1, search_k)`
5. Filter: skip IDs == -1 (FAISS padding), skip `exclude_event_uuid` if provided
6. Return first `k` results as `List[Tuple[np.int64, float]]`
- Distances are inner products (= cosine similarity for normalized vectors); range [-1, 1]

### 3k. `build_id_to_uuid_map(user_id, db)` [FS:160]
> Build `{faiss_id → engram_id}` map from DB for result resolution.

- Queries all `Engram` rows for `user_id`
- Returns `{_event_uuid_to_faiss_id(r.engram_id): r.engram_id for r in rows}`
- Used by C3 to convert FAISS integer IDs back to string UUIDs after search

---

## 4. `LLMCallCollector` [CC]

### Purpose

Captures all LLM calls made during a single top-level operation (decode, encode, or consolidate) without polluting method signatures. Uses a `ContextVar` that is set at the start of each operation and reset in a `finally` block.

### 4a. `_current_collector` ContextVar [CC:87]

```python
_current_collector: ContextVar[Optional[LLMCallCollector]] = ContextVar("_llm_call_collector", default=None)
```

- `ContextVar` is thread-safe: each thread running `_decode_sync` / `_encode_sync` / `_consolidate_sync` has its own value
- Set with `token = _current_collector.set(collector)` at operation start
- Reset with `_current_collector.reset(token)` in `finally` — restores prior value
- `LLMService._make_request()` reads it with `_current_collector.get()` after every successful API call

### 4b. `UsageMetadata` [CC:14]

```python
UsageMetadata(input_token_count, output_token_count, cost)
```

- `from_api_response(usage_dict)`: extracts `prompt_tokens`, `completion_tokens`, `cost` (OpenRouter only)
- `cost` is provider-reported; 0.0 if not in response (standard OpenAI)
- Supports `__add__` for accumulating totals across multiple calls

### 4c. `LLMCallRecord` [CC:44]

```python
@dataclass
LLMCallRecord(op, model, messages, raw_response, input_tokens, output_tokens, cost, latency_ms, step_order=0)
```

- `op`: operation label (e.g. `"continuation_check"`, `"synthesis"`, `"detect_drift"`)
- `raw_response`: first choice's `message.content` (may be empty for tool-call-only responses)
- `step_order`: assigned by `LLMCallCollector.add()` — sequential counter across the operation

### 4d. `LLMCallCollector` [CC:59]

```python
@dataclass
LLMCallCollector(records=[], _counter=0)
```

- `add(record)`: sets `record.step_order = _counter`, increments `_counter`, appends to `records`
- `usage` (property): sums `UsageMetadata` across all records via `__add__`
- `total_latency_ms` (property): sum of all `record.latency_ms`

### 4e. `_persist_interaction()` flow [service.py:656]

Called inside each sync operation after the work is done:
1. Guard: `not collector.records` → return immediately (no LLM calls, nothing to log)
2. `usage = collector.usage` — aggregate tokens + cost
3. Create `LLMInteraction` row: `operation`, `call_count=len(records)`, token/cost/latency totals, `turn_id`, `session_id`, `output` (JSON blob)
4. `db.add(interaction)` → `db.flush()` — get the generated `interaction.id`
5. For each `LLMCallRecord`: create `LLMCallLog` row FK'd to `interaction.id`
6. `db.commit()`
7. On any exception: `logger.error(...)` + `db.rollback()` — persistence failure is non-fatal

---

## 5. Graph Queries [GQ]

### 5a. `get_neighbors(user_id, engram_id, db, min_weight=0.0)` [GQ:13]
> Returns all directly connected engrams (bidirectional). **MENTION links excluded.**

- Two DB queries: `source_id == engram_id` (outgoing) + `target_id == engram_id` (incoming)
- Filter: `link_kind != MENTION` + `weight >= min_weight`
- Merges both into a flat list of `(neighbor_uuid, weight)` tuples
- **Bidirectional**: navigational links (SIMILARITY, RETRIEVAL, TEMPORAL, TRIADIC) are canonically stored but traversal must check both directions since the canonical sort may place either UUID as source
- Called by C3 graph expansion (§5.9 in decode.md); `min_weight=0.1` used there

### 5b. `bfs_reachable(user_id, start_id, db, max_depth=2, min_weight=0.1)` [GQ:42]
> BFS from a single seed. Returns `{engram_id: min_distance}`.

- Uses a `deque` for BFS; tracks visited with distance
- Stops expanding at `max_depth` hops
- Calls `get_neighbors()` at each step
- **Not used in the current decode/encode/consolidate paths** — available for future clustering or graph inspection features

### 5c. `get_engram_cluster(user_id, seed_ids, db, min_weight=0.1)` [GQ:65]
> BFS from multiple seeds. Returns full reachable set as `Set[str]`.

- Similar to `bfs_reachable` but multi-seed and unbounded depth
- **Not used in the current decode/encode/consolidate paths** — available for future clustering
