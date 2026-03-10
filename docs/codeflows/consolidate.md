# consolidate() Codeflow

> File refs: `S` = service.py, `CS` = consolidator/service.py, `CO` = consolidator/llm_ops.py, `BG` = consolidator/background.py

---

## 1. `MemoryService.consolidate()` [S:254]
   - Async entry point; delegates to `loop.run_in_executor(None, _consolidate_sync, user_id)`
   - Errors caught + logged at this level; never raises to caller

---

## 2. `MemoryService._consolidate_sync()` [S:270]
   - Create `LLMCallCollector` + set `_current_collector` context var (token-based)
   - Call `consolidate_user(user_id, db, ...)` — see §3
   - `_persist_interaction("consolidate", user_id, collector, db)` → write `LLMInteraction` row
   - `_current_collector.reset(token)` + `db.close()` in `finally`

---

## 3. `consolidate_user()` [CS:367]
> Central dispatcher. Called by `MemoryService._consolidate_sync()` and `BackgroundConsolidationTask`.

Signature:
```python
consolidate_user(user_id, db, consolidation_svc, enable_entity_extraction=False,
                 consolidation_llm_ops=None, embedding_service=None,
                 vector_dir=".hippomem/vectors", enable_self_memory=False,
                 self_trait_min_confidence=0.5)
```

Steps (each wrapped in individual try/except; failures are logged, not raised):

| # | Condition | What |
|---|-----------|------|
| 1 | Always | Staleness decay + demotion per session scope |
| 2 | `enable_entity_extraction` + `llm_ops` + `embedding_service` | Entity profile enrichment |
| 3 | `enable_self_memory` | Prune stale traits |
| 4 | `enable_self_memory` + `llm_ops` | Persona Engram generation/update |

**Step 1** — query all `WorkingState.session_id` scopes for this user (distinct); for each: `consolidation_svc.consolidate(user_id, session_id, db)` → see §4

**Step 2** — `enrich_entity_profiles(user_id, db, llm_ops, embedding_service, vector_dir)` → see §6

**Step 3** — `prune_stale_traits(user_id, db)` → see §7

**Step 4** — `consolidate_self_memory(user_id, db, llm_ops, min_confidence)` → see §8

---

## 4. `ConsolidationService` [CS:41]

### `ConsolidationConfig` [CS:24]
```
max_active_events: int = 5
max_dormant_events: int = 5
relevance_decay_rate: float = 0.98   # per hour
recency_lambda: float = 0.05
weight_relevance: float = 0.5
weight_recency: float = 0.3
weight_frequency: float = 0.2
stale_after_minutes: int = 1440      # 24h
```
Built from `MemoryConfig` by `MemoryService._get_consolidation_svc()`.

### `apply_decay()` [CS:52]
Public convenience wrapper: loads `WorkingStateData` if not supplied, then delegates to `apply_decay_uuids()`. Used by the encoder path for on-demand decay without a full demotion pass.

### `apply_decay_uuids()` [CS:66]
Per-hour exponential decay applied to all active `Engram` rows.

```
hours_since = (now - last_decay_applied_at).total_seconds() / 3600
decay_factor = relevance_decay_rate ^ hours_since        # 0.98^hours
score_after  = clamp(score_before * decay_factor, 0.0, 1.0)
```

- Rows with no `last_decay_applied_at` are initialised to `now` (skip first pass).
- Updates `relevance_score` and `last_decay_applied_at` in-place; no commit.

### `consolidate()` [CS:108]
Entry point for staleness demotion. Loads `WorkingStateData`, then calls `_consolidate_uuids()`.

### `_consolidate_uuids()` [CS:122]
Full staleness pass:
1. `apply_decay_uuids()` on all active events (no commit yet)
2. Query `Engram` rows → build `events_for_scoring` list: `{event_uuid, relevance_score, last_touched (ISO str), reinforcement_count}`
3. Score each event → `(event, demotion_score)` — see §5
4. **Staleness demotion** (only if `len(active) >= max_active_events`):
   - Filter to stale events (`_is_stale()` — see §5.2)
   - If any: find `max(stale_scored, key=demotion_score)` → demote that one event
   - At most **1 event** demoted per staleness pass
5. Prepend demoted uuid to `dormant`; evict tail if `len(dormant) > max_dormant_events`
6. `WorkingState.persist(db, ...)` + `db.commit()`
7. Return `ConsolidationResult(demoted_event_ids, total_active_after)`

> Note: Capacity-based demotion (making room when active > max) is handled in the encoder path, not here.

---

## 5. Demotion Scoring Math [CS:182]

### 5.1 `_compute_demotion_score()` — higher = more likely to demote
```
minutes_since_touch = (now - last_touched).total_seconds() / 60

recency_factor    = exp(-recency_lambda * minutes_since_touch)    # default lambda=0.05
frequency_factor  = log(1 + reinforcement_count)
norm_frequency    = min(frequency_factor / 5.0, 1.0)             # capped at 1

retention = relevance * 0.5  +  recency_factor * 0.3  +  norm_frequency * 0.2
demotion_score = 1.0 - retention
```

**Interpretation:**
- An event touched recently has high `recency_factor` → low demotion score → survives.
- A heavily reinforced event has high `norm_frequency` → also resists demotion.
- A decayed, untouched, weakly reinforced event scores near 1.0 → first to go.

### 5.2 `_is_stale()` — gate before demotion
```
stale = (minutes_since_touch > stale_after_minutes)  # default 1440 min = 24h
      AND (relevance_score < 0.2)
```
Both conditions must hold. A low-relevance event that was touched recently is **not** stale.

---

## 6. Entity Enrichment — `enrich_entity_profiles()` [CS:436]
> Decays and re-summarises entity Engrams from accumulated facts.

1. Query all `Engram` rows for user with `engram_kind = ENTITY`
2. For each entity row:
   - **Entity decay**: same exponential formula as §4 but `entity_decay_rate = 0.999/hour` (very slow — entities persist)
     - Captures `last_enriched_at = last_decay_applied_at` *before* overwriting with `now`
   - **Enrichment guard**: skip if `updated_at <= last_enriched_at` (no new facts since last run)
     - Skipped rows still get `last_decay_applied_at = now` (decay always applied)
   - **(LLM)** `ConsolidationLLMOps.update_entity_profile(canonical_name, entity_type, all_facts, existing_summary)` → `{merged_facts, summary_text}` — see §9
   - Update `row.updates = merged_facts`, `row.summary_text = summary_text`
   - **Re-embed**: build `embed_text = name (type)\nsummary\nfacts joined by \n`; call `embedding_service.embed(embed_text)`
   - `add_to_faiss_realtime(user_id, engram_id, vector, content_hash, faiss_svc, index, db)`
3. `faiss_svc.save_index(user_id, index)` once after loop (only if `enriched > 0`)
4. `db.commit()`; return count enriched

---

## 7. Trait Pruning — `prune_stale_traits()` [CS:248]
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

## 8. Self Memory Consolidation — `consolidate_self_memory()` [CS:296]
> Generates or updates the Persona Engram from active SelfTraits.

1. `get_active_traits(user_id, db)` → filter to `confidence_score >= min_confidence` (default 0.5)
2. Guard: no qualifying traits → return `False` (no-op)
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

Both ops use `llm.chat_structured()` at `temperature=0.3`, `max_tokens=4000`.

### `generate_identity_summary(traits_by_category)` [CO:36]
- Formats traits as block: `Category:\n  - key: value\n  - ...` per category
- Prompt: `consolidator.yaml → generate_identity_summary`
- Response model: `GenerateIdentitySummaryResponse { identity_summary: str }`
- Returns `identity_summary` string (empty string on failure)

### `update_entity_profile(canonical_name, entity_type, all_facts, existing_summary)` [CO:65]
- Formats facts as `- fact` bullets; existing summary as text
- Prompt: `consolidator.yaml → update_entity_profile`
- Response model: `UpdateEntityProfileResponse { merged_facts: List[str], summary_text: str }`
- Returns `{"merged_facts": [...], "summary_text": "..."}` (falls back to original data on LLM error)

---

## 10. Background Consolidation — `BackgroundConsolidationTask` [BG:20]
> Opt-in asyncio background task running `consolidate_user()` for all users on a schedule.

**Enabled via**: `MemoryConfig.enable_background_consolidation = True` (default: `False`)
**Started in**: `MemoryService._start_background_consolidation()` [S:208] during `setup()`

Key fields:
```
interval_seconds = interval_hours * 3600    # default 1h
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
| 1    | Always | Decay + staleness demotion per session scope (max 1 event/scope) |
| 2    | `enable_entity_extraction` | Entity decay + LLM profile merge + FAISS re-embed |
| 3    | `enable_self_memory` | Deactivate low-evidence, low-confidence, stale SelfTraits |
| 4    | `enable_self_memory` | LLM persona narrative → upsert Persona Engram |
