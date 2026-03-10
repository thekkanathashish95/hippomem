# hippomem

[![PyPI version](https://img.shields.io/pypi/v/hippomem)](https://pypi.org/project/hippomem/)
[![Python versions](https://img.shields.io/pypi/pyversions/hippomem)](https://pypi.org/project/hippomem/)
[![Downloads](https://img.shields.io/pypi/dm/hippomem)](https://pypi.org/project/hippomem/)
[![License](https://img.shields.io/pypi/l/hippomem)](https://pypi.org/project/hippomem/)
[![Status](https://img.shields.io/pypi/status/hippomem)](https://pypi.org/project/hippomem/)

Brain-inspired persistent memory for LLM chat applications.

hippomem gives your LLM app long-term memory across sessions. It stores what users tell you, surfaces relevant context before each LLM call, and consolidates memory over time — all from two lines of code.

```python
context = await memory.decode(user_id, message)   # retrieve relevant memory
await memory.encode(user_id, message, response, context)  # store what happened
```

---

## Install

**Library only** — embed memory directly into your application process:

```bash
pip install hippomem
```

Requires Python 3.11+.

---

## Quickstart: Library mode

Embed memory directly in your app. No separate process needed.

```python
import asyncio
from hippomem import MemoryService, MemoryConfig

async def main():
    memory = MemoryService(
        llm_api_key="sk-...",
        llm_base_url="https://api.openai.com/v1",  # or any OpenAI-compatible URL
    )

    async with memory:
        user_id = "user_123"
        history = []

        # On each turn:
        user_message = "I'm building a FastAPI app with JWT auth."

        # 1. Retrieve relevant memory before your LLM call
        result = await memory.decode(user_id, user_message, conversation_history=history)

        # 2. Inject result.context into your LLM system prompt
        response = await your_llm(system=result.context, message=user_message)

        # 3. Store the exchange after your LLM responds
        await memory.encode(user_id, user_message, response, result)
        history.append((user_message, response))

asyncio.run(main())
```

See `examples/demo.py` for a full working example.

---

## Quickstart: Daemon mode

Run hippomem as a persistent local service. Multiple apps can share one memory store.

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

Then connect from your app using `HippoMemClient`:

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

## Studio UI

When running `hippomem serve`, the Studio UI is available at `http://localhost:8719`:

| Tab | What it shows |
|-----|---------------|
| **Dashboard** | Memory counts, token usage, cost |
| **Chat** | Test the decode → LLM → encode loop interactively |
| **Memory Explorer** | List, grid, and D3 graph of stored memories |
| **Inspector** | Per-operation LLM traces with prompts, responses, token/cost/latency |

---

## Configuration

Set environment variables in `.env` (copy from `.env.example`):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_API_KEY` | Yes | — | API key for your LLM provider |
| `LLM_BASE_URL` | No | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `LLM_MODEL` | No | `gpt-4o-mini` | Model for hippomem's internal operations |
| `CHAT_MODEL` | No | Same as `LLM_MODEL` | Model for `/chat` endpoint (daemon mode) |
| `SYSTEM_PROMPT` | No | Built-in default | Base system prompt in daemon mode |
| `DB_URL` | No | `sqlite:///hippomem.db` | SQLite database path |
| `VECTOR_DIR` | No | `./hippomem_vectors` | FAISS vector index directory |

For library mode, pass `llm_api_key` and `llm_base_url` directly to `MemoryService`. Everything else can be tuned via `MemoryConfig`:

```python
from hippomem import MemoryService, MemoryConfig

config = MemoryConfig(
    llm_model="gpt-4o-mini",
    db_url="sqlite:///my_app.db",
    vector_dir="./my_vectors",
)
memory = MemoryService(llm_api_key="sk-...", llm_base_url="...", config=config)
```

---

## Usage modes at a glance

| Mode | Install | How |
|------|---------|-----|
| **Library** | `pip install hippomem` | `from hippomem import MemoryService` — runs in your process |
| **Daemon** | `pip install hippomem` | `hippomem serve` — standalone service + Studio UI |
| **Client** | `pip install hippomem` | `from hippomem.client import HippoMemClient` — connects to daemon over HTTP |

---

## How it works

hippomem uses a cascade of LLM-powered steps inspired by how the hippocampus encodes and retrieves episodic memory:

- **decode** (before your LLM call): checks recent context continuity → retrieves relevant events → synthesizes a context string
- **encode** (after your LLM response): extracts new information → creates or updates memory events → links related events via graph edges
- **consolidate** (periodic): decays stale events, promotes important ones, clusters related memories

Memory is stored locally in SQLite + FAISS. No data leaves your machine.

---

## License

MIT
