# Configuration

hippomem is configured through environment variables (daemon mode) or a `MemoryConfig` object (library mode). Both cover the same options.

---

## Daemon mode: environment variables

Copy `.env.example` to `.env` and edit:

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_API_KEY` | Yes | — | API key for your LLM provider |
| `LLM_BASE_URL` | No | `https://openrouter.ai/api/v1` | OpenAI-compatible base URL |
| `LLM_MODEL` | No | `google/gemini-3.1-flash-lite-preview` | Model for hippomem's internal operations |
| `CHAT_MODEL` | No | Same as `LLM_MODEL` | Model used for the `/chat` endpoint |
| `SYSTEM_PROMPT` | No | Built-in default | Base system prompt prepended to memory context in daemon mode |
| `DB_URL` | No | `sqlite:///.hippomem/hippomem.db` | SQLite database path |
| `VECTOR_DIR` | No | `.hippomem/vectors` | Directory for FAISS vector index files |

---

## Library mode: MemoryConfig

Pass a `MemoryConfig` instance to `MemoryService` to override any option:

```python
from hippomem import MemoryService, MemoryConfig

config = MemoryConfig(
    llm_model="x-ai/grok-4.1-fast",
    db_url="sqlite:///my_app.db",
    vector_dir="./my_vectors",
)
memory = MemoryService(llm_api_key="sk-...", llm_base_url="https://openrouter.ai/api/v1", config=config)
```

All fields have sensible defaults. You only need to set what you want to change.

---

## MemoryConfig reference

### LLM and embedding

| Field | Default | Description |
|-------|---------|-------------|
| `llm_model` | `x-ai/grok-4.1-fast` | Model used for all internal LLM operations (extraction, synthesis, consolidation) |
| `embedding_model` | `text-embedding-3-small` | Embedding model for FAISS indexing |
| `llm_max_retries` | `3` | Retry attempts on LLM call failure |
| `llm_retry_delay` | `1.0` | Seconds between retries |
| `llm_timeout` | `60.0` | Timeout in seconds per LLM call |

### Storage

| Field | Default | Description |
|-------|---------|-------------|
| `db_url` | `sqlite:///.hippomem/hippomem.db` | SQLAlchemy database URL |
| `vector_dir` | `.hippomem/vectors` | Directory for per-user FAISS index files |

### Memory features

| Field | Default | Description |
|-------|---------|-------------|
| `enable_entity_extraction` | `True` | Extract and track named entities (people, orgs, pets, places) after each encode |
| `enable_self_memory` | `True` | Extract and track stable user traits (job, location, habits) |
| `enable_background_consolidation` | `False` | Run decay and demotion on a background asyncio loop |
| `consolidation_interval_hours` | `1.0` | How often (hours) background consolidation runs |

### Working memory capacity

| Field | Default | Description |
|-------|---------|-------------|
| `max_active_events` | `5` | Max engrams in active working memory per user |
| `max_dormant_events` | `5` | Max recently-demoted engrams kept in the dormant tier |
| `ephemeral_trace_capacity` | `8` | Max weak traces per session before FIFO eviction |

### Decay

| Field | Default | Description |
|-------|---------|-------------|
| `decay_rate_per_hour` | `0.98` | Relevance score multiplier per hour (~2%/hr, ~40%/day if unused) |

### Retrieval cascade thresholds

| Field | Default | Description |
|-------|---------|-------------|
| `continuation_threshold` | `0.7` | C1 confidence needed to skip full search (stay on current topic) |
| `local_scan_threshold` | `0.6` | C2 score needed to skip global search |
| `conversation_window_turns` | `2` | Recent turns passed to retrieval cascade |

### Retrieval scoring weights

| Field | Default | Description |
|-------|---------|-------------|
| `retrieval_semantic_weight` | `0.5` | Weight given to semantic (FAISS) similarity |
| `retrieval_relevance_weight` | `0.3` | Weight given to engram relevance score |
| `retrieval_recency_weight` | `0.2` | Weight given to recency of last access |

### Hybrid retrieval (BM25)

| Field | Default | Description |
|-------|---------|-------------|
| `enable_bm25` | `True` | Run keyword search alongside FAISS; merge via Reciprocal Rank Fusion |
| `bm25_index_ttl_seconds` | `300` | Seconds before the per-user BM25 index is rebuilt |
| `rrf_k` | `60` | RRF constant — higher values smooth rank differences |

### Graph expansion

| Field | Default | Description |
|-------|---------|-------------|
| `enable_graph_expansion` | `True` | Follow graph edges to find related engrams during retrieval |
| `graph_hops` | `1` | Number of hops to traverse from matched engrams |
| `max_graph_events` | `5` | Max graph-neighbor engrams added to retrieval results |

### Self memory

| Field | Default | Description |
|-------|---------|-------------|
| `self_trait_min_confidence` | `0.5` | Minimum confidence score for a trait to appear in persona snapshots |

---

## Choosing a model

hippomem uses its configured model for internal operations only — extraction, synthesis, consolidation. It does not touch the model your application uses for chat.

Any OpenAI-compatible model works. Lower-cost, fast models (flash/mini tiers) are a good fit for the internal operations since hippomem makes several LLM calls per turn. The default (`google/gemini-3.1-flash-lite-preview` via OpenRouter) reflects this.

If you are on OpenAI directly:

```python
config = MemoryConfig(llm_model="x-ai/grok-4.1-fast")
memory = MemoryService(
    llm_api_key="sk-...",
    llm_base_url="https://openrouter.ai/api/v1",
    config=config,
)
```
