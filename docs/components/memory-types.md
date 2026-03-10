# Memory Types

hippomem stores three kinds of memory, each serving a different purpose. Understanding the distinction helps you configure the system correctly and interpret what you see in the Studio UI.

---

## Episodic memory

Episodic memories are the core memory type — they capture what happened in a conversation.

Each episodic engram has:
- A **topic** (`core_intent`) — a short description of what the memory is about, e.g. "building a FastAPI app with JWT auth"
- A **list of facts** (`updates`) — bullets that accumulate as the topic evolves across turns
- A **relevance score** — starts at 1.0, decays over time when the memory is not accessed
- A **reinforcement count** — how many times this memory has been actively used in synthesis

When you discuss a topic, hippomem creates an episodic engram for it. As you continue on that topic, new facts are appended to the same engram rather than creating duplicates. If the topic resurfaces in a later session, the engram's relevance score is refreshed and its reinforcement count incremented.

**Example:** Over three conversations about a project, an episodic engram might accumulate facts like:
```
- Building a FastAPI app with JWT auth
- Tokens expire after 24 hours
- Using RS256 algorithm with a 2048-bit key
- Deployed on Railway, hitting CORS issues with the frontend
```

---

## Entity memory

Entity memories capture structured knowledge about the named people, organizations, pets, places, and projects that a user mentions.

Where episodic memory captures *what happened*, entity memory captures *what is known* about a persistent object in the user's world. Each entity engram has a canonical name, a type (person, organization, pet, place, project), and a list of accumulated facts.

Entity profiles grow across interactions. The first time a person is mentioned, a profile is created. Each subsequent mention adds new facts. During consolidation, accumulated facts are merged by an LLM into a coherent summary, and the profile is re-embedded so future search reflects the full picture.

**Example entity profile for a person:**
```
Name: Sarah
Type: person
Facts:
- Product manager at the user's company
- Leading the Q3 launch
- Prefers async communication
- Working on the same JWT auth project
```

When Sarah is mentioned in a future conversation, this profile is surfaced as part of the retrieved context — without the user having to re-explain who she is.

Entity extraction runs automatically after each `encode()` call when `enable_entity_extraction=True` (the default).

---

## Self memory

Self memory captures stable facts and traits about the user themselves — not what happened in a conversation, but who the user is.

These are extracted from signals across many interactions: job role, location, recurring preferences, working style, ongoing projects, and similar durable characteristics. Each trait has a confidence score; only traits above the configured threshold appear in the user persona snapshot.

The persona snapshot is generated during consolidation and included in the memory context passed to your LLM. This means your application can start responses with an understanding of the user's context without the user having to re-establish it.

**Example self traits:**
```
- Software engineer working on backend infrastructure
- Prefers Python and FastAPI
- Based in London
- Typically works on solo projects
- Cares about performance and clean API design
```

Self memory is enabled by default (`enable_self_memory=True`). To disable:

```python
config = MemoryConfig(enable_self_memory=False)
```

---

## Working memory tiers

Regardless of type, engrams move through two tiers of working memory:

**Active** — the memories currently in focus (up to 5 by default). The retrieval cascade checks these first, before doing any broader search. Most turns resolve here.

**Dormant** — recently used memories that have been displaced from active (up to 5 by default). Still quickly accessible, included in the local scan, but no longer the primary focus.

When active capacity is exceeded, the oldest active engram is pushed to dormant. When dormant capacity is exceeded, the oldest dormant engram moves to long-term storage — still retrievable via full search, but no longer receiving preferential attention.

You can tune these limits in `MemoryConfig`:

```python
config = MemoryConfig(
    max_active_events=8,
    max_dormant_events=8,
)
```

---

## Ephemeral traces

Not every turn deserves a full engram. Casual greetings, short clarifying questions, and low-signal exchanges are stored as lightweight traces instead.

Traces are kept in a fixed-capacity FIFO buffer (8 per session by default). They are not embedded or indexed. Their purpose is to inform future memory creation decisions — when a subsequent turn does warrant a full engram, the traces from that session are included as context so the LLM has a complete picture of what was discussed.

Traces cycle out automatically. They are a scratch pad, not permanent storage.
