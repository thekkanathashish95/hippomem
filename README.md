# hippomem

[![PyPI version](https://img.shields.io/pypi/v/hippomem)](https://pypi.org/project/hippomem/)
[![Python versions](https://img.shields.io/pypi/pyversions/hippomem)](https://pypi.org/project/hippomem/)
[![Downloads](https://img.shields.io/pypi/dm/hippomem)](https://pypi.org/project/hippomem/)
[![License](https://img.shields.io/pypi/l/hippomem)](https://pypi.org/project/hippomem/)
[![Status](https://img.shields.io/pypi/status/hippomem)](https://pypi.org/project/hippomem/)

Brain-inspired persistent memory for AI applications.

hippomem is a memory layer that sits alongside your AI applications and gives them persistent, structured, evolving memory — across sessions and, eventually, across applications. The long-term goal is a single shared memory store that any AI application can read from and write to: one place where a user's knowledge, preferences, and context accumulate over time and remain accessible to any tool they use.

This is the first step toward that vision. Today, hippomem gives individual AI applications long-term memory that persists between conversations, builds up structured knowledge about the user, and stays coherent over time through a consolidation process.

**What hippomem stores:**
- **Episodic memory** — facts, preferences, and events from conversations
- **Entity memory** — people, pets, and organizations the user mentions
- **Self memory** — stable traits and facts about the user (e.g. job, location, habits)

All stored locally in SQLite + FAISS. No data leaves your machine.

hippomem does not try to remember everything. Unlike a fact store or a rolling message log, it is modeled on how human memory actually works: selective, lossy, and shaped by relevance. Memories that are used get reinforced; memories that go untouched decay. The hypothesis hippomem is built on is that this lossiness is not a weakness — it is what makes memory useful. A system that forgets selectively surfaces what matters, rather than drowning every response in accumulated context.

---

> **Note:** hippomem is an actively evolving open-source project. It is functional and being used, but you should expect rough edges in both the implementation and documentation. If you find gaps or bugs, please raise a GitHub issue or open a pull request — contributions will directly shape what gets built next.
>
> For detailed documentation, visit the [docs on GitHub](https://github.com/thekkanathashish95/hippomem/tree/main/docs).

---

## Install

```bash
pip install hippomem
```

Requires Python 3.11+.

---

## Usage modes at a glance

| Mode | How |
|------|-----|
| **Daemon** | `hippomem serve` — standalone service + Studio UI |
| **Library** | `from hippomem import MemoryService` — runs in your process |
| **Client** | `from hippomem.client import HippoMemClient` — connects to daemon over HTTP |

---

## Quickstart: Daemon mode

Run hippomem as a persistent local service. Multiple apps can share one memory store, and you get the Studio UI for free.

```bash
cp .env.example .env
# Edit .env — set LLM_API_KEY at minimum

hippomem serve
# → API + Studio UI at http://localhost:8719
```

Options:

```bash
hippomem serve --port 8719 --host 127.0.0.1
```

### Studio UI

The Studio UI is available at `http://localhost:8719` when the daemon is running:

| Tab | What it shows |
|-----|---------------|
| **Dashboard** | Memory counts, token usage, cost |
| **Chat** | Test the decode → LLM → encode loop interactively |
| **Memory Explorer** | List, grid, and D3 graph of stored episodic memories and entity profiles |
| **Self** | Self-traits learned about the user, grouped by category (goals, preferences, personality, etc.) |
| **Inspector** | Per-operation LLM traces with prompts, responses, token/cost/latency |
| **Settings** | Configure LLM connection, feature toggles, and advanced memory tuning |

### Connecting your app

Use `HippoMemClient` to connect from any application:

```python
from hippomem.client import HippoMemClient

async with HippoMemClient("http://localhost:8719") as mem:
    result = await mem.decode("user_123", "What was I working on?")
    # inject result.context into your LLM system prompt
    response = await your_llm(system=result.context, message=user_message)
    await mem.encode("user_123", user_message, response, decode_result=result)
```

`HippoMemClient` is included in the standard `pip install hippomem`.

---

## Quickstart: Library mode

Embed memory directly in your app process. No separate service needed.

```python
import asyncio
from hippomem import MemoryService, MemoryConfig

async def main():
    memory = MemoryService(
        llm_api_key="sk-...",
        llm_base_url="https://openrouter.ai/api/v1",  # or any OpenAI-compatible URL
    )

    async with memory:
        user_id = "user_123"
        history = []

        user_message = "I'm building a FastAPI app with JWT auth."

        # 1. Retrieve relevant memory before your LLM call
        result = await memory.decode(user_id, user_message, conversation_history=history)

        # 2. Inject result.context into your LLM system prompt
        response = await your_llm(system=result.context, message=user_message)

        # 3. Store the exchange after your LLM responds
        await memory.encode(user_id, user_message, response, decode_result=result)
        history.append((user_message, response))

asyncio.run(main())
```

See `examples/demo.py` and `examples/chat_server.py` for full working examples.

### Direct memory search

Use `retrieve()` when you want raw search results rather than synthesized LLM context — for example to build your own UI, run analysis, or power a search feature:

```python
result = await memory.retrieve(
    user_id,
    "FastAPI JWT auth",
    mode="hybrid",   # "hybrid", "faiss", or "bm25"
    top_k=5,
)
for episode in result.episodes:
    print(episode.core_intent, episode.entities)
```

`retrieve()` is independent of the decode/encode loop — you can call it at any time without affecting normal memory operation.

---

## Configuration

Set environment variables in `.env` (copy from `.env.example`):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_API_KEY` | Yes | — | API key for your LLM provider |
| `LLM_BASE_URL` | No | `https://openrouter.ai/api/v1` | OpenAI-compatible base URL |
| `LLM_MODEL` | No | `google/gemini-3.1-flash-lite-preview` | Model for hippomem's internal operations |
| `CHAT_MODEL` | No | Same as `LLM_MODEL` | Model for `/chat` endpoint (daemon mode) |
| `SYSTEM_PROMPT` | No | Built-in default | Base system prompt in daemon mode |
| `DB_URL` | No | `sqlite:///.hippomem/hippomem.db` | SQLite database path |
| `VECTOR_DIR` | No | `.hippomem/vectors` | FAISS vector index directory |

For library mode, pass `llm_api_key` and `llm_base_url` directly to `MemoryService`. Everything else can be tuned via `MemoryConfig`:

```python
from hippomem import MemoryService, MemoryConfig

config = MemoryConfig(
    llm_model="x-ai/grok-4.1-fast",
    db_url="sqlite:///my_app.db",
    vector_dir="./my_vectors",
    enable_entity_extraction=True,   # extract people, orgs, pets (default: True)
    enable_self_memory=True,         # track stable user traits (default: True)
    enable_background_consolidation=False,  # periodic decay + clustering
)
memory = MemoryService(llm_api_key="sk-...", llm_base_url="...", config=config)
```

---

## How it works

hippomem uses a cascade of LLM-powered steps inspired by how the hippocampus encodes and retrieves episodic memory:

- **decode** (before your LLM call): checks recent context continuity → retrieves relevant memory → synthesizes a context string ready to inject into your system prompt
- **encode** (after your LLM response): extracts new information → creates or updates memory engrams → links related memories via graph edges → updates entity and self-memory if enabled
- **consolidate** (periodic): compresses accumulated episode facts into clean baselines, enriches entity profiles, prunes stale self-traits, and synthesizes active user signals into a structured identity persona
- **retrieve** (optional): direct search API that returns raw structured results — episodes with linked entities and graph-connected neighbors — independent of the decode/encode lifecycle

---

## Docs

- [Quickstart guide](https://github.com/thekkanathashish95/hippomem/blob/main/docs/guides/quickstart.md)
- [Configuration reference](https://github.com/thekkanathashish95/hippomem/blob/main/docs/guides/configuration.md)
- [Studio UI](https://github.com/thekkanathashish95/hippomem/blob/main/docs/components/studio-ui.md)
- [Memory types](https://github.com/thekkanathashish95/hippomem/blob/main/docs/components/memory-types.md)
- [Consolidation](https://github.com/thekkanathashish95/hippomem/blob/main/docs/components/consolidation.md)
- [Architecture overview](https://github.com/thekkanathashish95/hippomem/blob/main/docs/contributing/architecture.md)

---

## License

MIT
