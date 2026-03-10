# HippoMemClient Codeflow

> File refs: `CL` = client.py, `DS` = decoder/schemas.py, `ES` = encoder/schemas.py, `RS` = retrieve/schemas.py

---

## Overview

`HippoMemClient` is a thin async HTTP wrapper for apps that connect to a running hippomem daemon (`hippomem serve`). It mirrors `MemoryService`'s public API — `decode`, `encode`, `consolidate` — but delegates all work over HTTP rather than executing it in-process.

**When to use HippoMemClient vs MemoryService directly:**

| | `MemoryService` | `HippoMemClient` |
|---|---|---|
| Process | In-process (no daemon needed) | Requires a running daemon |
| Dependency | `pip install hippomem` | `pip install hippomem[server]` (adds httpx) |
| Setup | `await memory.setup()` (DB init) | None (daemon is already running) |
| DB access | Direct SQLAlchemy | None — HTTP only |
| Multi-process | No (single process owns the DB) | Yes (daemon is the single owner) |
| Turn linking | Tier 1–4 decode cache | Tier 1 only (caller must pass `decode_result`) |

---

## 1. `HippoMemClient.__init__()` [CL:49]

```python
HippoMemClient(base_url="http://localhost:8719", timeout=30.0)
```

- `base_url` stripped of trailing `/`; stored as `self.base_url`
- `httpx` imported lazily via `_get_httpx()` — raises `ImportError` with install hint if not installed
- `self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)` — persistent connection pool; reused across all calls

### Lazy httpx import [CL:29]

```python
def _get_httpx():
    try:
        import httpx
        return httpx
    except ImportError:
        raise ImportError("httpx is required ... pip install hippomem[server]") from None
```

- httpx is an optional dependency (`hippomem[server]` extra); base `hippomem` install does not require it
- Import attempted at `__init__` time, not at module import time

---

## 2. Lifecycle [CL:54]

### `aclose()` [CL:54]
```python
await client.aclose()
```
- Calls `self._client.aclose()` — closes the underlying httpx connection pool

### Context manager [CL:58]
```python
async with HippoMemClient("http://localhost:8719") as mem:
    ...
```
- `__aenter__`: returns `self` (no setup needed beyond `__init__`)
- `__aexit__`: calls `await self.aclose()`

---

## 3. `decode()` [CL:64]

```python
result: DecodeResult = await client.decode(
    user_id, message,
    session_id=None,
    conversation_history=None,
)
```

**Payload construction**:
```python
payload = {
    "user_id": user_id,
    "message": message,
    "session_id": session_id,
    "conversation_history": [list(pair) for pair in (conversation_history or [])],
}
```
- `conversation_history` tuples are serialized to `list` (JSON arrays) — `tuple[str, str]` → `[str, str]`
- `session_id` is sent even if `None` (daemon server handles `None` gracefully)

**HTTP call**: `POST /decode` with JSON payload

**Response → `DecodeResult`**:
```python
DecodeResult(
    context=data["context"],
    used_engram_ids=data["used_engram_ids"],
    used_entity_ids=data.get("used_entity_ids", []),
    reasoning=data["reasoning"],
    synthesized_context=data["synthesized_context"],
    turn_id=data.get("turn_id", ""),
)
```
- `used_entity_ids` and `turn_id` use `.get()` with defaults — backward-compatible with older daemon versions
- `r.raise_for_status()` — raises `httpx.HTTPStatusError` on non-2xx (e.g. daemon 503 if not initialized)
- No retry logic — network errors propagate to caller

---

## 4. `encode()` [CL:91]

```python
result: EncodeResult = await client.encode(
    user_id, user_message, assistant_response,
    decode_result=result,
    session_id=None,
    conversation_history=None,
)
```

**Payload construction**:
```python
payload = {
    "user_id": user_id,
    "user_message": user_message,
    "assistant_response": assistant_response,
    "session_id": session_id,
    "conversation_history": [list(pair) for pair in (conversation_history or [])],
}
```

**`decode_result` serialization** (only if provided, lines 109–117):
```python
payload["decode_result"] = {
    "context": decode_result.context,
    "used_engram_ids": decode_result.used_engram_ids,
    "used_entity_ids": decode_result.used_entity_ids,
    "reasoning": decode_result.reasoning,
    "synthesized_context": decode_result.synthesized_context,
    "turn_id": decode_result.turn_id,
}
```
- The `DecodeResult` dataclass is manually serialized to a dict (not using `dataclasses.asdict`) because the server expects the `DecodeResponse` Pydantic schema field names

**HTTP call**: `POST /encode` with JSON payload

**Response → `EncodeResult`**:
```python
EncodeResult(turn_id=data.get("turn_id", ""))
```
- `EncodeResult` is a simple dataclass with a single field: `turn_id: str`

### Turn linking behavior

When `decode_result` is passed, the daemon server uses **Tier 1** resolution (decode_result has `turn_id`). This is the same Tier 1 used by direct `MemoryService` callers.

**Tier 2/3/4 (in-process cache / DB fallback) do NOT apply** when using `HippoMemClient`:
- There is no shared in-process `_last_decode_cache` between the client and the daemon
- Always pass `decode_result` to `encode()` to ensure correct engram linking

---

## 5. `consolidate()` [CL:124]

```python
await client.consolidate(user_id)
```

**HTTP call**: `POST /consolidate` with `{"user_id": user_id}`

- Returns `None` (response body `{"status": "ok"}` is ignored)
- `r.raise_for_status()` — raises on non-2xx
- Fire-and-wait: consolidate is awaited before returning (same as direct `MemoryService.consolidate()`)

---

## 6. `retrieve()` [CL:129]

```python
result: RetrieveResult = await client.retrieve(
    user_id, query,
    mode="hybrid",          # "faiss" | "bm25" | "hybrid"
    top_k=5,
    entity_count=4,
    graph_count=5,
    session_id=None,
    exclude_uuids=None,
    rrf_k=None,
    bm25_index_ttl_seconds=None,
    w_sem=None, w_rel=None, w_rec=None,
)
```

**Payload construction** (only non-None optional params are included):
```python
payload = {
    "user_id": user_id,
    "query": query,
    "mode": mode,
    "top_k": top_k,
    "entity_count": entity_count,
    "graph_count": graph_count,
    # optional: session_id, exclude_uuids, rrf_k, bm25_index_ttl_seconds, w_sem, w_rel, w_rec
}
```

**HTTP call**: `POST /retrieve` with JSON payload

**Response → `RetrieveResult`**:
- `_dict_to_retrieve_result(data)` reconstructs the full hierarchy:
  - `episodes` → list of `RetrievedEpisode` via `_dict_to_episode()`
  - Each episode's `entities` → list of `RetrievedEntity` via `_dict_to_entity()`
  - Each episode's `related_episodes` → recursively via `_dict_to_episode()`
- Returns `RetrieveResult(episodes, total_primary)`
- `r.raise_for_status()` — raises `httpx.HTTPStatusError` on non-2xx

**Key fields on `RetrievedEpisode`**:
- `source`: `"faiss"` | `"bm25"` | `"hybrid"` | `"graph"`
- `graph_hop`: `0` = primary result, `1+` = graph-expanded related
- `entities[]`: MENTION-linked entity engrams (canonical_name, entity_type, facts, etc.)
- `related_episodes[]`: graph-neighbor episodes (1 hop from primary; no further recursion)

---

## 7. Error handling

`HippoMemClient` does **not** swallow exceptions:

| Condition | Exception raised |
|---|---|
| httpx not installed | `ImportError` (at `__init__` time) |
| Non-2xx HTTP response | `httpx.HTTPStatusError` (from `raise_for_status()`) |
| Network failure | `httpx.RequestError` (e.g. `ConnectError` if daemon not running) |
| JSON decode failure | `httpx.DecodingError` (malformed response body) |

Common daemon errors:
- `503 Service Unavailable` — daemon started but no API key configured yet (visit `/settings`)
- `404 Not Found` — wrong endpoint or path

---

## 8. Typical integration pattern

```python
from hippomem.client import HippoMemClient

async with HippoMemClient("http://localhost:8719") as mem:
    # Per-turn loop:
    result = await mem.decode(user_id, user_message, conversation_history=history)

    # Pass result.context to your LLM system prompt:
    system_prompt = base_system_prompt
    if result.context:
        system_prompt += "\n\n" + result.context
    assistant_response = await your_llm(system_prompt, user_message)

    # Always pass decode_result to encode() for correct turn linking:
    await mem.encode(
        user_id, user_message, assistant_response,
        decode_result=result,
        conversation_history=history,
    )

    # Maintain your own history:
    history.append((user_message, assistant_response))
```

**Key difference from direct integration**: with `HippoMemClient` the app does not call `hippomem serve` — the daemon is started separately (e.g. via `hippomem serve` CLI or as a sidecar process).
