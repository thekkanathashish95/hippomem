# consolidate() Codeflow

> File refs: `S` = service.py, `CS` = consolidator/service.py, `CO` = consolidator/llm_ops.py, `BG` = consolidator/background.py

---

## 1. `MemoryService.consolidate()` [S:261]
   - Async entry point; delegates to `loop.run_in_executor(None, _consolidate_sync, user_id)`
   - Errors caught + logged at this level; never raises to caller

---

## 2. `MemoryService._consolidate_sync()` [S:277]
   - Create `LLMCallCollector` + set `_current_collector` context var (token-based)
   - Call `consolidate_user(user_id, db, ...)` — see §3
   - `_persist_interaction("consolidate", user_id, collector, db)` → write `LLMInteraction` row
   - `_current_collector.reset(token)` + `db.close()` in `finally`

---

## 3. `consolidate_user()` [CS:230]
> Central dispatcher. Called by `MemoryService._consolidate_sync()` and `BackgroundConsolidationTask`.

Signature:
```python
consolidate_user(user_id, db, enable_episode_consolidation=True,
                 enable_entity_extraction=False,
                 consolidation_llm_ops=None, embedding_service=None,
                 vector_dir=".hippomem/vectors", enable_self_memory=False)
```

> Decay and demotion are handled entirely by the encoder on each turn — not here.

Steps (each wrapped in individual try/except; failures are logged, not raised):

| # | Condition | What |
|---|-----------|------|
| 1 | `enable_episode_consolidation` + `llm_ops` + `embedding_service` | Episode fact consolidation |
| 2 | `enable_entity_extraction` + `llm_ops` + `embedding_service` | Entity profile enrichment |
| 3 | `enable_self_memory` | Prune stale traits |
| 4 | `enable_self_memory` + `llm_ops` | Persona Engram generation/update |

**Step 1** — `consolidate_episode_facts(user_id, db, llm_ops, embedding_service, vector_dir)` → see §5

**Step 2** — `enrich_entity_profiles(user_id, db, llm_ops, embedding_service, vector_dir)` → see §6

**Step 3** — `prune_stale_traits(user_id, db)` → see §7

**Step 4** — `consolidate_self_memory(user_id, db, llm_ops)` → see §8

---

## 4. `ConsolidationService` [CS:21]

> Owns decay only. Demotion is the encoder's responsibility.

### `ConsolidationConfig` [CS:21]
```
max_active_events: int = 5
max_dormant_events: int = 5
relevance_decay_rate: float = 0.98   # per hour
```
Built from `MemoryConfig` by `MemoryService._get_consolidation_svc()`. Passed to the encoder (`WorkingMemoryUpdater.consolidation`) for decay and capacity tracking.

### `apply_decay()` [CS:52]
Public convenience wrapper: loads `WorkingStateData` if not supplied, then delegates to `apply_decay_uuids()`. Used by the encoder path for on-demand decay.

### `apply_decay_uuids()` [CS:66]
Per-hour exponential decay applied to all active `Engram` rows.

```
hours_since = (now - last_decay_applied_at).total_seconds() / 3600
decay_factor = relevance_decay_rate ^ hours_since        # 0.98^hours
score_after  = clamp(score_before * decay_factor, 0.0, 1.0)
```

- Rows with no `last_decay_applied_at` are initialised to `now` (skip first pass).
- Updates `relevance_score` and `last_decay_applied_at` in-place; no commit.

---

## Engram: `pending_facts` and `needs_consolidation` columns

Two columns added to the `engrams` table support the encoder→consolidation handoff:

| Column | Type | Writer | Reader |
|--------|------|--------|--------|
| `pending_facts` | JSON (nullable) | Encoder — appends raw new facts/updates since last consolidation run | Consolidation — reads, merges, then clears to `[]` |
| `needs_consolidation` | Boolean (indexed, default False) | Encoder — sets `True` when appending to `pending_facts` | Consolidation — filters on `True`; clears to `False` after processing |

**All fact read sites** (decode synthesis, encode context, BM25 index, retrieve) combine both:
```python
"updates": (row.updates or []) + (row.pending_facts or [])
```
This ensures unprocessed pending facts are visible between consolidation runs.

**`row.updates`** is the clean consolidated baseline — written only by consolidation, never by the encoder.

---

## 5. Episode Consolidation — `consolidate_episode_facts()` [CS:384]
> Compresses accumulated pending update statements into the episode's consolidated baseline.

1. Query `Engram` rows for user where `engram_kind = EPISODE` AND `needs_consolidation IS True`
2. If no matching rows → return `0`
3. For each episode row:
   - **(LLM)** `ConsolidationLLMOps.consolidate_episode_updates(core_intent, consolidated_updates=row.updates, pending_updates=row.pending_facts)` → `{merged_updates}` — see §9
   - `row.updates = merged_updates`; `row.pending_facts = []`; `row.needs_consolidation = False`; `row.updated_at = now`
   - **Re-embed**: `embed_engram(engram_id, core_intent, updates, embedding_service)` → `(vector, content_hash)`
   - `add_to_faiss_realtime(user_id, engram_id, vector, content_hash, faiss_svc, index, db)`
4. `faiss_svc.save_index(user_id, index)` once after loop (only if `consolidated > 0`)
5. `db.commit()`; return count consolidated

---

## 6. Entity Enrichment — `enrich_entity_profiles()` [CS:296]
> Re-summarises entity Engrams from accumulated pending facts.

1. Query `Engram` rows for user where `engram_kind = ENTITY` AND `needs_consolidation IS True`
2. If no matching rows → return `0`
3. For each entity row:
   - **Entity decay**: same exponential formula as §4 but `entity_decay_rate = 0.999/hour` (very slow — entities persist); `row.last_decay_applied_at = now`
   - **(LLM)** `ConsolidationLLMOps.update_entity_profile(canonical_name, entity_type, consolidated_facts=row.updates, pending_facts=row.pending_facts, existing_summary)` → `{merged_facts, summary_text}` — see §9
   - `row.updates = merged_facts`; `row.summary_text = summary_text`; `row.pending_facts = []`; `row.needs_consolidation = False`
   - **Re-embed**: build `embed_text = name (type)\nsummary\nfacts joined by \n`; call `embedding_service.embed(embed_text)`
   - `add_to_faiss_realtime(user_id, engram_id, vector, content_hash, faiss_svc, index, db)`
4. `faiss_svc.save_index(user_id, index)` once after loop (only if `enriched > 0`)
5. `db.commit()`; return count enriched

---

## 7. Trait Pruning — `prune_stale_traits()` [CS:112]
> Deactivates `SelfTrait` rows that are no longer likely relevant.

Params (with defaults): `stale_days=30`, `min_evidence_to_keep=2`, `min_confidence_to_keep=0.7`

A trait is deactivated if **ALL** of the following hold (conservative AND logic):
```
evidence_count < min_evidence_to_keep    (never reinforced — seen only once)
last_observed_at < now - stale_days      (not seen in 30 days)
confidence_score < min_confidence_to_keep
```

**Why AND:** A high-confidence single-shot preference (`confidence >= 0.7`) survives. A frequently-reinforced trait (`evidence_count >= 2`) also survives regardless of recency. Only low-evidence, low-confidence, long-unobserved traits are pruned.

Sets `is_active = False`; `db.commit()`. Returns count deactivated.

---

## 8. Self Memory Consolidation — `consolidate_self_memory()` [CS:160]
> Generates or updates the Persona Engram from active SelfTraits.

1. `get_active_traits(user_id, db)` → all `is_active=True` traits. No confidence filter applied here — activation is the single quality gate, enforced in `accumulate_traits()` at extraction time.
2. Guard: no active traits → return `False` (no-op)
3. `compute_traits_hash(traits)` → `sha256(json.dumps(sorted [{category,key,value}]))` — deterministic, order-independent
4. Query existing `Engram(engram_kind=PERSONA)` for this user
5. Guard: `persona.content_hash == current_hash` → return `False` (traits unchanged, skip LLM call)
6. Build `by_category: Dict[str, List[str]]` — `{category: ["key: value", ...]}` using `defaultdict`
7. **(LLM)** `ConsolidationLLMOps.generate_identity_summary(by_category)` → identity narrative string — see §9
8. **Upsert Persona Engram**:
   - If none: create `Engram(engram_kind=PERSONA, core_intent="self_profile", summary_text=narrative, content_hash=hash, relevance_score=1.0, last_decay_applied_at=now)`
   - If exists: update `summary_text`, `content_hash`, `updated_at`
9. `db.commit()`; return `True`

---

## 9. `ConsolidationLLMOps` [CO:30]

All ops use `llm.chat_structured()` at `temperature=0.3`, `max_tokens=4000`.

### `generate_identity_summary(traits_by_category)` [CO:36]
- Formats traits as block: `Category:\n  - key: value\n  - ...` per category
- Prompt: `consolidator.yaml → generate_identity_summary`
- Response model: `GenerateIdentitySummaryResponse { identity_summary: str }`
- Returns `identity_summary` string (empty string on failure)

### `update_entity_profile(canonical_name, entity_type, consolidated_facts, pending_facts, existing_summary)` [CO:65]
- Sends **two labeled sections** to the LLM:
  - `Consolidated facts` — trusted baseline (already merged and clean)
  - `New facts` — pending, appended since last consolidation (integrate these)
- Prompt: `consolidator.yaml → update_entity_profile`
- Response model: `UpdateEntityProfileResponse { merged_facts: List[str], summary_text: str }`
- Returns `{"merged_facts": [...], "summary_text": "..."}` (falls back to `consolidated_facts + pending_facts` on LLM error)

### `consolidate_episode_updates(core_intent, consolidated_updates, pending_updates)` [CO:~95]
- Sends two labeled sections: existing consolidated updates and new pending updates
- Goal: supersede contradictions, compress, cap merged list at 8–10 items
- Prompt: `consolidator.yaml → consolidate_episode_updates`
- Response model: `ConsolidateEpisodeResponse { merged_updates: List[str] }`
- Returns `{"merged_updates": [...]}` (falls back to `consolidated_updates + pending_updates` on LLM error)

---

## 10. Background Consolidation — `BackgroundConsolidationTask` [BG:20]
> Opt-in asyncio background task running `consolidate_user()` for all users on a schedule.

**Enabled via**: `MemoryConfig.enable_background_consolidation = True` (default: `False`)
**Started in**: `MemoryService._start_background_consolidation()` [S:215] during `setup()`

Key fields:
```
interval_seconds = interval_hours * 3600    # default 1h
enable_episode_consolidation — synced from MemoryConfig (default True)
enable_entity_extraction / enable_self_memory — synced from MemoryConfig
```

### Loop — `_run()` [BG:78]
```
while True:
    await asyncio.sleep(interval_seconds)
    await loop.run_in_executor(None, _run_sync)
```

### `_run_sync()` [BG:87]
1. `get_db_session(session_factory)` → open DB session
2. Query all distinct `user_id`s from `WorkingState`
3. For each user: `consolidate_user(user_id, db, ...)` — same dispatcher as §3
4. `db.close()` in `finally`
5. Per-user failures logged as warnings; other users continue

### Lifecycle
- `start()`: `asyncio.create_task(_run())`
- `stop()`: cancel + await task; called during `MemoryService.close()`
- Feature flag changes: `MemoryService.update_feature_flags()` updates `_enable_entity_extraction` and `_enable_self_memory` on the live task instance in-place

---

## Steps Summary

| Step | Condition | What it does |
|------|-----------|--------------|
| 1    | `enable_episode_consolidation` + `llm_ops` + `embedding_service` | Merge pending episode updates into consolidated baseline + FAISS re-embed |
| 2    | `enable_entity_extraction` + `llm_ops` + `embedding_service` | Entity decay + LLM profile merge (consolidated + pending facts) + FAISS re-embed |
| 3    | `enable_self_memory` | Deactivate low-evidence, low-confidence, stale SelfTraits |
| 4    | `enable_self_memory` + `llm_ops` | LLM persona narrative → upsert Persona Engram |
