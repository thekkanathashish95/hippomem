# Studio UI

The Studio UI is a browser-based interface included with hippomem's daemon mode. It gives you a live view into memory state, a chat interface for testing, and full LLM operation traces — all without writing any code.

---

## Starting the daemon

```bash
hippomem serve
# Studio available at http://localhost:8719
```

The Studio opens at the same address as the API. No separate setup needed.

---

## Tabs

### Dashboard

An overview of the current memory state:

- Total engram count (episodic, entity, persona)
- Cumulative token usage and estimated cost across all operations
- Recent activity

### Chat

An interactive chat interface that runs the full decode → LLM → encode loop:

- Type a message and send it as any user ID
- Memory context retrieved by `decode()` is shown alongside the response
- The exchange is stored via `encode()` after each turn
- Useful for testing that memory is being recalled and updated correctly without writing integration code

### Memory Explorer

A visual browser of stored episodic memories and entity profiles:

- **List view** — tabular view of all engrams with their relevance score, type, last accessed time, and core content
- **Grid view** — card-based layout for scanning memory at a glance
- **Graph view** — D3.js force-directed graph showing engrams as nodes and their relationships (graph edges) as links; useful for understanding how memories are connected

You can filter by user, engram type (episode, entity, persona), and sort by relevance or recency.

### Self

Shows what hippomem has learned about the user from their conversations. Traits are grouped by category:

| Category | Examples |
|----------|---------|
| **Stable Attributes** | Job title, location, primary language |
| **Goals** | Current projects, objectives |
| **Personality** | Communication style, working habits |
| **Preferences** | Tool choices, framework preferences |
| **Constraints** | Time zones, availability, limitations |
| **Projects** | Active initiatives mentioned across sessions |

Each trait shows its current value, evidence count (how many times it has been observed), first and last observed timestamps, and whether it is active or still unconfirmed. Requires `enable_self_memory=True`.

### Inspector

Per-operation LLM traces. Every `decode()`, `encode()`, and `consolidate()` call that passes through the daemon is logged:

- The exact prompt sent to the LLM
- The raw LLM response
- Token counts (input + output)
- Estimated cost
- Latency in milliseconds
- Which engrams were used or updated

The Inspector is the primary debugging tool — if memory isn't being recalled or stored correctly, start here to see exactly what the system decided and why.

### Settings

Configure hippomem at runtime without restarting the daemon. Changes take effect immediately and persist across restarts.

**Connection**
- API Base URL and API Key — your LLM provider credentials
- Memory Model — the model hippomem uses for internal operations (extraction, synthesis, retrieval decisions)
- Chat Model — the model used for the Studio's Chat tab
- System Prompt — base prompt prepended before memory context in the Chat tab

**Features** (toggle on/off)
- Background Consolidation — periodic decay and demotion without manual `consolidate()` calls
- Memory Clustering — group related episodes into summaries during consolidation (requires Background Consolidation)
- Entity Memory — track named people, orgs, pets, and projects across conversations
- Self Memory — extract and accumulate stable user traits and persona

**Advanced** (collapsed by default)
- Memory capacity: active slots, dormant slots, ephemeral trace slots
- Retrieval cascade: C1 continuation threshold, C2 local scan threshold
- Retrieval scoring weights: semantic, relevance, recency (must sum to 1.0)
- Decay rate per hour and consolidation interval

---

## API access

The same daemon also exposes a REST API at `http://localhost:8719`. Key endpoints:

| Endpoint | Description |
|----------|-------------|
| `POST /decode` | Retrieve memory context for a user message |
| `POST /encode` | Store a completed turn |
| `POST /consolidate` | Run consolidation for a user |
| `POST /retrieve` | Direct memory search (hybrid, FAISS, or BM25) |
| `GET /traces` | List recent LLM operation traces |
| `GET /memory/graph/{user_id}` | Raw graph data for a user |
| `GET /memory/entities/{user_id}` | All entity engrams for a user |
| `GET /memory/self/{user_id}` | Self-memory traits for a user |
| `GET /stats` | Aggregate usage stats |
| `GET /health` | Health check |
| `GET /config` | Current runtime configuration |
| `PATCH /config` | Update configuration at runtime |

Full API docs are available at `http://localhost:8719/docs` (Swagger UI) when the daemon is running.
