# Quickstart

This guide covers the three ways to use hippomem: the Studio UI (no code needed), as a standalone daemon service with API access, or as a library embedded directly in your application.

---

## Prerequisites

- Python 3.11 or higher
- An API key for an OpenAI-compatible LLM provider (OpenAI, OpenRouter, xAI, etc.)

## Install

```bash
pip install hippomem
```

---

## Option A: Daemon mode

Run hippomem as a standalone local service. You get the Studio UI for exploring and testing memory, plus an API your applications can connect to. Multiple apps can share one memory store.

### 1. Configure

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```
LLM_API_KEY=sk-...
```

See the [configuration guide](configuration.md) for all available options.

### 2. Start the daemon

```bash
hippomem serve
```

By default this starts on `http://127.0.0.1:8719`. To change host or port:

```bash
hippomem serve --port 8719 --host 127.0.0.1
```

### 3a. Use the Studio UI (no code needed)

Open `http://localhost:8719` in your browser. The Studio lets you:

- **Chat** — have a conversation and watch memory being built in real time. Each message goes through the full decode → LLM → encode loop, so you can immediately see what gets remembered and recalled.
- **Memory Explorer** — browse all stored episodic memories and entity profiles as a list, grid, or D3 graph. See what hippomem knows, how memories are connected, and how relevance scores change over time.
- **Self** — view the traits and facts hippomem has inferred about the user from their conversations — goals, preferences, personality, projects, and more.
- **Inspector** — see exactly what happened on every operation: the prompts sent, the LLM responses, token counts, cost, and latency. The best place to start if something isn't working as expected.
- **Settings** — configure your LLM provider, toggle features (entity memory, self memory, background consolidation), and tune memory behaviour — all without editing files or restarting.

No coding required for any of the above. The Studio is a complete interface for exploring, testing, and configuring hippomem.

### 3b. Connect your app via API

Use `HippoMemClient` — included in the standard `pip install hippomem`:

```python
from hippomem.client import HippoMemClient

async with HippoMemClient("http://localhost:8719") as mem:
    result = await mem.decode("user_123", "What was I working on?")
    response = await your_llm(system=result.context, message=user_message)
    await mem.encode("user_123", user_message, response, decode_result=result)
```

The client API is identical to `MemoryService` — `decode()`, `encode()`, `consolidate()`, `retrieve()`.

---

## Option B: Library mode

Embed hippomem directly in your application process. No separate service needed.

### 1. Initialize MemoryService

```python
from hippomem import MemoryService, MemoryConfig

memory = MemoryService(
    llm_api_key="sk-...",
    llm_base_url="https://openrouter.ai/api/v1",  # or any OpenAI-compatible URL
)
```

Use `async with memory:` so setup and teardown are handled automatically:

```python
async with memory:
    # your app logic here
```

Or call manually:

```python
await memory.setup()
# ...
await memory.close()
```

### 2. The turn loop

On every conversation turn, call `decode()` before your LLM and `encode()` after:

```python
user_id = "user_123"
history = []  # list of (user_message, assistant_response) tuples — you maintain this

user_message = "I'm building a FastAPI app with JWT auth."

# Before your LLM call — retrieve relevant memory
result = await memory.decode(user_id, user_message, conversation_history=history)

# Inject result.context into your LLM system prompt
response = await your_llm(system=result.context, message=user_message)

# After your LLM responds — store what happened
await memory.encode(user_id, user_message, response, decode_result=result)

# Update your own history list
history.append((user_message, response))
```

**Important:** Always pass `decode_result=result` to `encode()`. This links the two calls so hippomem knows which memory context was active during the response.

### 3. Periodic consolidation

Call `consolidate()` periodically (e.g. once per session, or on a schedule) to decay stale memories and maintain memory quality:

```python
await memory.consolidate(user_id)
```

This is separate from `encode()` by design — it is a maintenance operation, not a per-turn call.

### Full example

```python
import asyncio
from hippomem import MemoryService

async def main():
    memory = MemoryService(
        llm_api_key="sk-...",
        llm_base_url="https://openrouter.ai/api/v1",
    )

    async with memory:
        user_id = "user_123"
        history = []

        messages = [
            "I'm building a FastAPI app with JWT auth.",
            "The tokens should expire after 24 hours.",
            "What should I use for the secret key?",
        ]

        for user_message in messages:
            result = await memory.decode(user_id, user_message, conversation_history=history)
            response = await your_llm(system=result.context, message=user_message)
            await memory.encode(user_id, user_message, response, decode_result=result)
            history.append((user_message, response))

        # Run consolidation at the end of the session
        await memory.consolidate(user_id)

asyncio.run(main())
```

See `examples/demo.py` and `examples/chat_server.py` for complete working examples.

---

## Next steps

- [Configuration](configuration.md) — all `MemoryConfig` options explained
- [Studio UI](../components/studio-ui.md) — full Studio UI reference
- [Memory types](../components/memory-types.md) — what hippomem stores and why
- [Consolidation](../components/consolidation.md) — how memory stays coherent over time
