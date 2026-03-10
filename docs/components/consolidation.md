# Consolidation

Consolidation is hippomem's maintenance process. It keeps memory coherent over time by decaying stale memories, promoting important ones, enriching entity profiles, and synthesizing a user persona from accumulated self-knowledge.

---

## What consolidation does

Each consolidation cycle runs the following steps:

1. **Decay** — reduces the relevance score of all active engrams based on how long they have been idle. The default rate is ~2% per hour, so a memory that hasn't been accessed in a day loses roughly 40% of its score.

2. **Demotion** — engrams whose composite score (relevance + recency + frequency) falls below a threshold are moved from active to dormant, making room for more current memories.

3. **Entity enrichment** — entity profiles that have accumulated new facts since the last cycle are re-summarized by an LLM and re-embedded, so future semantic search reflects the full picture.

4. **Persona synthesis** — accumulated self-traits are merged into a coherent persona snapshot for the user, which is then included in future `decode()` context.

---

## When to call consolidate()

`consolidate()` is not a per-turn operation. It is a periodic maintenance call.

**Recommended patterns:**

- **End of session** — call once after the conversation ends:
  ```python
  await memory.consolidate(user_id)
  ```

- **On a schedule** — call from a background job (e.g. daily, or every few hours):
  ```python
  # Example: daily job
  for user_id in active_users:
      await memory.consolidate(user_id)
  ```

- **Background mode** — let hippomem run it automatically (see below)

There is no harm in calling `consolidate()` more frequently than needed — the cycle is lightweight when there is little to process.

---

## Background consolidation

hippomem can run consolidation automatically in an asyncio background task. Enable it in `MemoryConfig`:

```python
config = MemoryConfig(
    enable_background_consolidation=True,
    consolidation_interval_hours=1.0,  # run every hour
)
memory = MemoryService(llm_api_key="sk-...", config=config)
```

The background task starts when `memory.setup()` is called (or when entering `async with memory:`). It runs for all users who have had activity since the last cycle.

Background consolidation is disabled by default. Enable it if you are running a long-lived service and want maintenance to happen without explicit calls.

---

## Decay mechanics

Every active engram has a `relevance_score` between 0.0 and 1.0. Each consolidation cycle applies:

```
new_score = current_score × (decay_rate_per_hour ^ hours_since_last_access)
```

The default `decay_rate_per_hour` of `0.98` means:
- After 1 hour idle: ~2% decay
- After 24 hours idle: ~40% decay
- After 72 hours idle: ~70% decay

Memories that are actively retrieved and used during `decode()` have their scores refreshed, making them resilient to decay. Memories that are never accessed gradually fade.

To slow decay (longer memory retention):

```python
config = MemoryConfig(decay_rate_per_hour=0.995)  # ~0.5%/hr, ~11%/day
```

To speed decay (shorter memory retention):

```python
config = MemoryConfig(decay_rate_per_hour=0.95)  # ~5%/hr, ~70%/day
```

---

## Demotion scoring

When consolidation checks whether to demote an active engram to dormant, it uses a composite score:

```
score = (0.5 × relevance_score) + (0.3 × recency_score) + (0.2 × frequency_score)
```

- **Relevance score** — the decayed relevance value
- **Recency score** — exponential decay based on time since last access
- **Frequency score** — normalized reinforcement count

Engrams with the lowest composite scores are demoted first when active capacity is exceeded.
