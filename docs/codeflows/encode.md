# encode() Codeflow

> File refs: `S` = service.py, `E` = encoder/updater.py, `EL` = memory/episodic/llm_ops.py, `ENT` = memory/entity/llm_ops.py, `SE` = memory/self/extractor.py, `SL` = memory/self/llm_ops.py, `SS` = memory/self/service.py, `GE` = infra/graph/edges.py, `VE` = infra/vector/edges.py, `VB` = infra/vector/embedding.py, `TS` = memory/traces/service.py, `CS` = consolidator/service.py

---

## 1. `MemoryService.encode()` [S:399]
   - 1.1 **Resolve turn_id + used_engram_ids + used_entity_ids** (4-tier fallback):
      - **Tier 1**: caller passed `decode_result` with `turn_id` → use `turn_id`, `used_engram_ids`, `used_entity_ids` directly
      - **Tier 2**: `(user_id, session_id)` cache hit in `_last_decode_cache` → use cached `(turn_id, used_engram_ids)`; `used_entity_ids = []`
         - Note: Tier 2 does NOT call `move_to_end()` — read-only cache access (no LRU update)
      - **Tier 3/4**: generate provisional `turn_id = uuid4()`; `used_engram_ids = []` (sentinel — signals DB fallback in `_encode_sync`); `used_entity_ids = []`
   - 1.2 `await self._encode_async(...)` — encode is fully awaited, not fire-and-forget
   - 1.3 Returns `turn_id` after encode completes
      - `_background_tasks` set exists on `MemoryService` (used by background consolidation) but is NOT used by the encode path

---

## 2. `_encode_async()` [S:455]
   - 2.1 Append current turn and trim: `history = (conversation_history + [(user_message, assistant_response)])[‑updater_history_turns:]`
      - Appends THEN trims — current turn is always the last element
   - 2.2 Resolve final values from `decode_result`:
      - `reasoning = decode_result.reasoning if decode_result else ""`
      - `synthesized_context = decode_result.synthesized_context if decode_result else ""`
      - `used_entity_ids = (decode_result.used_entity_ids if decode_result else None) or used_entity_ids or []` — 3-way fallback
   - 2.3 `loop.run_in_executor(None, _encode_sync, ...)` — runs `_encode_sync` in thread pool
      - Wrapped in try/except: `logger.error("encode() failed for user %s: %s", ...)` — exception swallowed

---

## 3. `_encode_sync()` [S:488]
   - 3.1 Create `LLMCallCollector` + set `_current_collector` context var
   - 3.2 `db = self._get_db()` — open DB session; closed in `finally` block
   - 3.3 **Tier 3 DB fallback** (only if `used_engram_ids` is empty sentinel):
      - Query latest `LLMInteraction` for this `user_id` + `session_id` with `operation="decode"`, ordered by `created_at desc`
      - Age check: `(datetime.now(UTC).replace(tzinfo=None) - row.created_at.replace(tzinfo=None)).total_seconds() <= turn_link_max_age_seconds`
         - Both sides stripped to naive UTC before comparison
      - If within threshold: `turn_id = row.turn_id`; `used_engram_ids = (row.output or {}).get("used_engram_ids", [])`
      - **Tier 4**: threshold exceeded or no row → provisional `turn_id` stands; `used_engram_ids = []` → Path B encode
   - 3.4 Call `MemoryEncoder.update(user_id, session_id, conversation_history, db, used_engram_ids, reasoning, synthesized_context, used_entity_ids, on_step)` → `result`
   - 3.5 Log INFO: `encode: user=... action=... engram=... turn_id=...`
      - `engram_id = result.get("event_id") or "none"` — string `"none"` if no episode created
   - 3.6 `_persist_interaction("encode", ...)` → write `LLMInteraction` + `LLMCallLog` rows
      - Output stored: `{action, event_uuid}`
      - Skipped entirely if `collector.records` is empty (no LLM calls were made)
   - 3.7 `_save_conversation_turn(db, user_id, session_id, turn_id, user_message, assistant_response, memory_context, used_engram_ids, encoded_engram_id)` — see §3a
      - `user_message = conversation_history[-1][0]`, `assistant_response = conversation_history[-1][1]` — current turn extracted from trimmed history
      - `memory_context = synthesized_context` — raw synthesized context (without markdown wrapper)
      - `encoded_engram_id = result.get("event_id")` — episode UUID from this encode (may be None)

---

### 3a. `_save_conversation_turn()` [S:651]
> Persists the raw turn and its engram associations. Fully non-fatal — any error is logged and rolled back without affecting the encode outcome.

   - Creates `ConversationTurn` row (user_id, session_id, turn_id, user_message, assistant_response, memory_context); `db.flush()` to get `turn.id` without committing
   - Iterates `used_engram_ids` (decoded engrams): for each unique uuid → `ConversationTurnEngram(turn_id=turn.id, engram_id=uuid, link_type="decoded", user_id)`; deduplicates via `seen_engram_ids` set
   - If `encoded_engram_id` is set and not already in `seen`: `ConversationTurnEngram(link_type="encoded")` — the episode this turn was written into
   - `db.commit()` — single commit for both `ConversationTurn` and all `ConversationTurnEngram` rows
   - On exception: `logger.error(...)` + `db.rollback()`

---

## 4. `MemoryEncoder.update()` [E:75]
   - 4.1 Guard: empty `conversation_history` → load working state, return `{working_state, event_id: None, action: "skip"}`
   - 4.2 `user_message, agent_response = conversation_history[-1]` — extract current turn
   - 4.3 `used_engram_ids = used_engram_ids or []` — normalize None to empty list
   - 4.4 Load or create `WorkingStateData` via `WorkingState.load_or_create(db, user_id, session_id)`
   - 4.5 `step("Analyzing conversation")` — fires `on_step` callback if provided
   - 4.6 **Route on `used_engram_ids`**:
      - Non-empty → **Path A** [logs debug `path=A reason=used_engram_ids`]: `_update_used_events()` → see §5
      - Empty → **Path B** [logs debug `path=B reason=cold_start`]: `_create_or_ets()` → see §6
   - 4.7 `_apply_decay_to_active()` — delegates to `ConsolidationService.apply_decay_uuids()` for active engrams
   - 4.8 `_handle_demotion()` — see §4a; logs debug `working_state: active=N/max demoted=N`
   - 4.9 `working_state.last_updated = datetime.now(UTC).isoformat()` — set timestamp before persist
   - 4.10 `WorkingState.persist(db, user_id, session_id, working_state)` — write updated working state
   - 4.11 **Entity reinforcement** (if `used_entity_ids` AND `entity_llm_ops` set): `_reinforce_used_entities()` — see §9
      - Runs BEFORE entity extraction — wrapped in try/except with `logger.error`
   - 4.12 **Entity extraction** (always runs if `entity_llm_ops` set, regardless of episodic path):
      - `step("Extracting entities")` — fires `on_step` callback
      - `episode_uuid` may be None (ETS/skip turns): entities still created/updated, but no MENTION link written
      - If `entity_llm_ops` is None: logs info `entity_extract: skipped — entity_llm_ops is None (enable_entity_extraction=...)`
      - Wrapped in try/except with `logger.error` — see §8
   - 4.13 **Self extraction** (if `self_extractor` set):
      - `step("Updating self model")` — fires `on_step` callback
      - Runs regardless of whether `event_uuid_result` is set
      - Wrapped in try/except with `logger.error` — see §10
   - 4.14 Return `{working_state: working_state.model_dump(), event_id: event_uuid_result, action}`

---

### 4a. `_handle_demotion()` [E:544]
> FIFO demotion when active list exceeds capacity. Score-based staleness demotion lives in ConsolidationService.consolidate().

   - `while len(active) > max_active_events`:
      - `u = active.pop()` — pops the **last** (oldest) element
      - `demoted.append(u)`
      - `dormant.insert(0, u)` — prepend to dormant (most-recently demoted is dormant[0])
      - `if len(dormant) > max_dormant_events: dormant.pop()` — evict tail of dormant on overflow
   - Returns list of demoted UUIDs

---

### 4b. Decay math — `ConsolidationService.apply_decay_uuids()` [CS:66]
> Called by `_apply_decay_to_active()` on every encode turn, for all active engrams.

   - For each active engram row:
      - `hours_since = (now - last_decay_applied_at).total_seconds() / 3600.0`
      - `decay_factor = relevance_decay_rate ^ hours_since`  (default rate = 0.98 → ~2%/hr, ~40%/day)
      - `score_after = max(0.0, min(1.0, score_before * decay_factor))`
      - `row.last_decay_applied_at = now`
   - No-op if `hours_since <= 0`; skips row and sets `last_decay_applied_at = now` if field was None

---

## 5. Path A — `_update_used_events()` [E:198]
> Entered when decode() returned engrams that were used in context.

   - 5.1 Fetch primary engram row (`used_engram_ids[0]`) → `active_core_intent` (stripped), `active_event_updates`
   - 5.2 If `active_core_intent` is non-empty → **(LLM)** `detect_drift()` [EL:100] — see §5a
      - `recent_turns = format_recent_turns(conversation_history, updater_detect_drift_turns)`
      - Returns `(decision, reason)`; on exception: falls back to `("update_existing", None)`
   - 5.3 **Branch on drift decision**:
      - `create_new_branch` → [logs debug `path_A: drift=create_new_branch`] `_create_new_event(drift_from_intent=active_core_intent)`, then `strengthen_temporal_links([used_engram_ids[0]], new_uuid)`, return `(new_uuid, "create_new_branch")`
      - `update_existing` → [logs debug `path_A: drift=update_existing`] continue
   - 5.4 `_update_retrieval_state(user_id, working_state, used_engram_ids, db)` — see §5b
   - 5.5 `db.commit()` — commits retrieval state changes before content update
   - 5.6 `recent_turns_extract = format_recent_turns(conversation_history, updater_extract_update_turns)`
   - 5.7 `_update_event_content(...)` — see §5c
   - 5.8 If `len(used_engram_ids) > 1`: `strengthen_retrieval_links(user_id, used_engram_ids, db)` — all-pairs RETRIEVAL links
   - 5.9 Return `(used_engram_ids[0], "update_existing")`

---

### 5a. `EpisodicLLMOps.detect_drift()` [EL:100]
   - Formats `active_event_updates` as indented bullet block; `"(none)"` if empty
   - `recent_turns` defaults to `"(No previous turns)"` if blank
   - **(LLM)** `chat_structured(messages, DetectDriftResponse, temp=0.3, max_tokens=4000, op="detect_drift")`
   - Post-validation: if `decision` not in `{"update_existing", "create_new_branch"}` → normalize to `"update_existing"`
   - On exception: `logger.error(...)`, return `("update_existing", None)`

---

### 5b. `_update_retrieval_state()` [E:259]
> Promotes used engrams toward active[0]; updates last_updated_at and reinforcement_count.

   - For each `event_uuid` in `used_engram_ids`:
      - DB lookup: bump `reinforcement_count += 1`, set `last_updated_at = now`
      - **Promotion logic**:
         - If uuid in dormant: `dormant.remove(uuid)` + `active.insert(0, uuid)` — dormant → active head
         - If uuid not in active: `active.insert(0, uuid)` — newly seen → active head
         - If uuid in active but not at `[0]`: `active.remove(uuid)` + `active.insert(0, uuid)` — re-order to head
         - If uuid is already `active[0]`: no change
   - `db.flush()` — does NOT commit (caller commits after this returns)

---

### 5c. `_update_event_content()` [E:315]
> LLM update of core_intent and updates; re-embed and sync FAISS when content changes.

   - Build `event_tuples: List[(uuid, row, event_dict)]` for all rows with non-empty `core_intent`
   - Early return if `event_tuples` is empty
   - **(LLM)** `extract_event_update(events, user_message, agent_response, reasoning, synthesized_context, recent_turns)` [EL:36] — see §5d
   - Load FAISS once: `faiss_svc.load_index(user_id) or faiss_svc.get_or_create_index(user_id)` — tries existing index first
   - `faiss_dirty = False`
   - For each `(event_uuid, row, _), updated` pair:
      - Apply LLM result: if `add_update=True and update`: append to `new_updates`; if `refined_core_intent`: replace `new_core_intent`
      - `new_content_hash = compute_content_hash(new_core_intent, new_updates)` — see §12a
      - If `content_hash_changed`:
         - Update `row.core_intent`, `row.updates`, `row.content_hash`, `row.updated_at`
         - `embed_engram(event_uuid, new_core_intent, new_updates, embedding_service)` — see §12b
         - If result: `add_to_faiss_realtime(...)` — see §12c; then `process_links_realtime(...)` — see §13
         - FAISS write wrapped in try/except with `logger.error`; sets `faiss_dirty = True`
      - Else (no change): update `row.updated_at = now` only
      - Logs debug: `path_A update: content_hash_changed=... → re-embed|skip`
   - If `faiss_dirty`: `faiss_svc.save_index(user_id, index)` — one save after full loop

---

### 5d. `EpisodicLLMOps.extract_event_update()` [EL:36]
   - Formats multiple events as numbered `Memory 1: / Memory 2:` blocks with `core_intent` and `updates`
   - `memory_section`: includes `synthesized_context` + `reasoning` if present; else `"(none)"`
   - `recent_turns` defaults to `"(No previous turns)"` if blank
   - **(LLM)** `chat_structured(messages, ExtractEventUpdateResponse, temp=0.3, max_tokens=4000, op="extract_event_update")`
   - Returns list of `{add_update, update, refined_core_intent}` — one per event in order
   - Pads short responses to match `len(events)` with `{add_update: False, update: None, refined_core_intent: None}`
   - Truncates responses longer than `len(events)` to avoid index errors
   - On exception: `logger.error(...)`, return all-fallback list

---

## 6. Path B — `_create_or_ets()` [E:395]
> Entered when no prior engrams were used (cold start, first turn, etc.)

   - 6.1 `traces_svc.get_traces(user_id, session_id, db)` → `ets_traces: List[str]` (ordered by `created_at asc`)
   - 6.2 `recent_turns_create = format_recent_turns(conversation_history, updater_should_create_turns)`
   - 6.3 **(LLM)** `should_create_new_event(user_message, agent_response, ets_traces, recent_turns)` [EL:146]
      - Formats ETS traces as bullet block; `"(none)"` if empty
      - **(LLM)** `chat_structured(messages, ShouldCreateNewEventResponse, temp=0.3, max_tokens=4000)`
      - Returns `(bool(result.should_create), result.reason)` ; on exception: `(False, None)`
   - 6.4 Logs debug: `path_B: should_create=True/False`
   - 6.5 **Branch on decision**:
      - `True` → `_create_new_event(...)` — see §7; return `(event_uuid, "create_new")`
      - `False` → ETS path
   - 6.6 **(LLM)** `maybe_append_to_ets(user_message, agent_response, existing_traces, recent_turns)` [EL:249]
      - `recent_turns_create` (same window as should_create call) is passed here
      - Returns `(True, trace_summary)` only if `result.store and result.trace_summary and isinstance(str) and strip()` — strict validation
      - On exception or invalid: returns `(False, None)`
   - 6.7 `appended_to_ets = bool(store and trace_summary)`
   - 6.8 Logs debug: `path_B skip: appended_to_ets=True/False`
   - 6.9 If `appended_to_ets`: `traces_svc.append_trace(user_id, session_id, trace_summary, db, max_size=ephemeral_trace_capacity)` — see §6a
   - 6.10 Return `(None, "append_trace" if appended_to_ets else "skip")`

---

### 6a. `traces_svc.append_trace()` [TS:31]
> FIFO fixed-capacity trace store per (user_id, session_id) scope.

   - Guard: empty / whitespace content → return immediately
   - Count existing traces for this scope (session_id filter: exact match or `IS NULL` for None)
   - If `count >= max_size`: query oldest by `created_at asc`, `db.delete(oldest)`, `db.flush()` — evict before insert
   - `db.add(Trace(user_id, session_id, content=content.strip()))` → `db.commit()`

---

## 7. `_create_new_event()` [E:437]
> Shared by Path A (drift branch) and Path B (create branch). Accepts optional `drift_from_intent`.

   - 7.1 `recent_turns_gen = format_recent_turns(conversation_history, updater_generate_event_turns)`
   - 7.2 `event_uuid = str(uuid4())` — generated **before** LLM call
   - 7.3 **(LLM)** `generate_new_event(user_message, agent_response, recent_turns, drift_from_intent=...)` [EL:186] — see §7a
   - 7.4 `content_hash = compute_content_hash(core_intent, updates)` — see §12a
   - 7.5 Create `Engram` row: `reinforcement_count=0, relevance_score=1.0, last_decay_applied_at=now, last_updated_at=now`
      - `db.add(store)` → `db.flush()`
   - 7.6 `faiss_svc.get_or_create_index(user_id)` — always guarantees a valid index (unlike `load_index`)
   - 7.7 `embed_engram(event_uuid, core_intent, updates, embedding_service)` → `(vector, content_hash)` or `None` — see §12b
   - 7.8 If result: `add_to_faiss_realtime(...)` — see §12c; then `process_links_realtime(...)` — see §13
      - Entire FAISS block wrapped in try/except with `logger.error` — FAISS failure is non-fatal; event is persisted regardless
   - 7.9 `faiss_svc.save_index(user_id, index)` — save inside the same try block
   - 7.10 **Temporal edge**: if `active` is non-empty: `strengthen_temporal_links(user_id, [active[0]], event_uuid, db)` — links most-recent active to new event
   - 7.11 `working_state.active_event_uuids = [event_uuid] + working_state.active_event_uuids` — prepend to active
   - 7.12 Logs INFO: `Created new event {event_uuid} for user {user_id}`
   - 7.13 Return `(event_uuid, [])`

---

### 7a. `EpisodicLLMOps.generate_new_event()` [EL:186]
   - `recent_turns` defaults to `"(No previous turns)"` if blank
   - If `drift_from_intent` set: injects **drift context block** into prompt:
      - `"This memory is being created because the conversation diverged from: '{drift_from_intent}'"`
      - Instructs LLM to anchor `core_intent` on what is genuinely NEW; treats recent_turns as background only
   - If `drift_from_intent` is None: `drift_context_block = ""` — prompt behaves as standard creation
   - **(LLM)** `chat_structured(messages, GenerateNewEventResponse, temp=0.3, max_tokens=4000, op="generate_new_event")`
   - Returns dict: `{core_intent, updates, relevance_score: 1.0, reinforcement_count: 0, created_at, last_touched, last_decay_applied_at}`
   - On exception: fallback returns `{core_intent: "Discussion about: {message[:50]}...", updates: [message[:100]]}`

---

## 8. Entity extraction — `_extract_and_link_entities()` [E:562]
> Always runs if `entity_llm_ops` is set. `episode_uuid` may be None (ETS/skip turns).
> No MENTION link is written when `episode_uuid` is None.

   - 8.1 `recent_turns = format_recent_turns(conversation_history, updater_entity_extract_turns)`
   - 8.2 **Build hint map** from `known_entity_uuids` (decoder-resolved entities):
      - `_load_hint_entity_details(known_entity_uuids, user_id, db)` — batch-queries ENTITY engrams with non-null `core_intent`; returns `[{uuid, name, entity_type, facts}]`
      - For each result: assigns alias `H1, H2, ...`; populates `hint_map: Dict[str, str]` (`alias → uuid`)
      - `_truncate_facts(facts, max_chars=3000, max_fact_chars=300)` — each fact capped at 300 chars with `...`; total per entity capped at 3000 chars
      - Formats `hint_block` string: `"**Known entities (likely referenced in this turn):**\nH1: Alice (person) — fact1; fact2\n..."`
      - If `known_entity_uuids` is empty or no rows found: `hint_map = {}`, `hint_block = ""`
   - 8.3 **(LLM)** `entity_llm_ops.extract_entities(user_message, agent_response, recent_turns, hint_block=hint_block)` [ENT:21]
      - `hint_block` injected into user template via `{hint_block}` placeholder (empty string = no hints, no behavior change)
      - Each `ExtractedEntity` may include `hint_id: Optional[str]` — `"H1"` if the LLM matched a hint, `None` for new entities
      - `temperature=0.1`, `max_tokens=4000`; on exception returns `EntityExtractionResult(entities=[])` (empty, not None)
   - 8.4 Logs info: `entity_extract: user=... episode=... found=N significant=N hints=N`
   - 8.5 Iterates ALL entities; `significant` check is inside the loop (non-significant skipped via `continue`)
   - 8.6 For each significant entity — entire block in try/except: `db.rollback()` + `logger.error` on failure:
      - **Hint anchor branch** (if `extracted.hint_id` is set AND `hint_id in hint_map`):
         - Resolves UUID directly from `hint_map`; calls `_append_facts_to_entity(resolved_uuid, ...)` — skips name scan and disambiguation entirely
         - Logs debug: `entity='...' match=hint_anchor uuid=...`
      - **Normal branch** (hint_id is None or not in map): `_find_or_create_entity(extracted, user_id, db, user_message, agent_response, recent_turns)` — see §8a
      - 8.6.1 If `entity_uuid and episode_uuid`: `_link_entity_to_episode(user_id, episode_uuid, entity_uuid, mention_type, db)` — see §8b
      - 8.6.2 `db.commit()` — per-entity commit to release DB lock before next entity's embedding API call

---

### 8a. `_find_or_create_entity()` [E:658]
> Only called for entities with no hint_id. Lookup strategy: name scan → exact auto-update → LLM disambiguation → create.

   - `_find_entity_candidates_by_name(canonical_name, entity_type, user_id, db)` [E:610]:
      - Queries all ENTITY engrams for this user filtered by same `entity_type`
      - Match tiers per row: `exact` (case-insensitive equality) → `substring` (one inside the other, bidirectional) → `token` (share ≥1 token with `len > 2`)
      - Token set built from `name.lower().split()` filtering `len > 2`
      - Returns `List[(tier, row)]`
   - **0 candidates** → `_create_entity_node(extracted, user_id, db, faiss_svc)` — see §8d; logs debug `entity='...' match=none → create`
   - **1 exact match** → `_append_facts_to_entity(matched_row.engram_id, ...)` via `get_or_create_index` — logs debug `entity='...' match=exact uuid=...`
   - **Multiple matches or non-exact only** → build `mention_context` from `recent_turns + user_message + agent_response`; **(LLM)** `entity_llm_ops.disambiguate_entity(new_name, entity_type, mention_context, candidates_for_llm)` [ENT:50]
      - Candidates formatted as `candidate_1: {name}\n  - {fact}...` blocks
      - `temperature=0.1`, `max_tokens=4000`; on exception returns `DisambiguationResult(match=None, confidence=0.0, reason="LLM error")`
      - `result.match` format: `"candidate_N"` — parsed as `int(result.match.split("_")[1]) - 1`; `IndexError/ValueError` → fall through to create
      - Match → `_append_facts_to_entity(matched_row.engram_id, ...)` — logs debug `entity='...' match=disambiguate uuid=...`
      - No match or parse error → `_create_entity_node(...)` — logs debug `entity='...' match=none (llm returned null) → create`

---

### 8b. `_link_entity_to_episode()` [E:842]
   - Query existing `EngramLink` where `source_id == episode_uuid, target_id == entity_uuid, link_kind == MENTION`
      - MENTION links are **directional** (episode → entity), NOT canonical-sorted (unlike SIMILARITY/RETRIEVAL/TEMPORAL/TRIADIC)
   - If not exists: `db.add(EngramLink(link_kind=MENTION, mention_type=mention_type))`
   - `db.flush()` — not commit (caller commits after this returns)

---

### 8c. `_append_facts_to_entity()` [E:750]
   - Loads entity row; returns `entity_uuid` immediately if row not found (no-op guard)
   - `new_facts = [f for f in extracted.facts if f not in existing_facts]` — dedup against existing
   - Always bumps `reinforcement_count += 1` (even if no new facts)
   - Re-embeds only if `new_facts` were added:
      - `_build_entity_embed_text(name, entity_type, updated_facts)` — see §12d
      - `embedding_service.embed(embed_text)` → single embed (not batch)
      - `content_hash = compute_content_hash(row.core_intent, row.updates)` — see §12a
      - `add_to_faiss_realtime(...)` — see §12c; then `faiss_svc.save_index(user_id, index)`
      - Re-embed failure: `logger.error(...)`, continues (re-embed is non-fatal)
   - Logs debug: `entity=... facts_added=N re_embedded=True/False`
   - `db.flush()` before returning

---

### 8d. `_create_entity_node()` [E:797]
   - `entity_uuid = str(uuid4())`, `content_hash = compute_content_hash(canonical_name, facts)` — see §12a
   - Engram created with: `engram_kind=ENTITY, reinforcement_count=1, relevance_score=1.0, summary_text=None`
      - `summary_text` is set later by `ConsolidationService.enrich_entity_profiles()` during consolidation
   - `db.add(node)` → `db.flush()` → logs debug `entity=... match=create sim=0.000`
   - Embed text: `_build_entity_embed_text(canonical_name, entity_type, facts)` — see §12d
   - FAISS: `get_or_create_index(user_id)` → `embedding_service.embed(embed_text)` → `add_to_faiss_realtime(...)` + `save_index(user_id, index)` — see §12c
   - FAISS failure: `logger.error(...)`, entity row is persisted regardless

---

## 9. Entity reinforcement — `_reinforce_used_entities()` [E:292]
> No LLM. Runs BEFORE entity extraction (§8), after working-state persist.
> Only runs when `entity_llm_ops` is set AND `used_entity_ids` is non-empty.

   - 9.1 Bulk-query: `Engram.engram_id.in_(used_entity_ids)` + `engram_kind=ENTITY` + `user_id`
   - 9.2 For each row: `reinforcement_count += 1`, `last_updated_at = now`
   - 9.3 `db.flush()`
   - 9.4 Logs debug: `entity_reinforce: user=... count=N`
   - Effect: entities repeatedly surfaced in synthesis rank higher in future entity retrieval (sorted by `reinforcement_count desc`) and gain a recency boost in composite scoring

---

## 10. Self extraction — `SelfExtractor.extract_and_accumulate()` [SE:28]
> Runs last, after entity extraction. Runs regardless of episodic path outcome.

   - 10.1 `get_existing_traits(user_id, db)` [SS:13] — load **active-only** trait rows (category, key, value, evidence_count); inactive traits are excluded so the prompt context stays tight
   - 10.2 `recent_turns = format_recent_turns(conversation_history, _SELF_EXTRACT_TURNS=3)` — hardcoded 3 turns
   - 10.3 **(LLM)** `llm_ops.extract_self_candidates(user_message, existing_traits, recent_turns)` [SL:16] → `result.candidates`
      - Prompt shows existing active traits as `category | key: value  (seen Nx)` block
      - LLM is instructed to return ONLY traits not already captured in the profile, or traits whose value has meaningfully changed — no action classification
      - `temperature=0.1`, `max_tokens=4000`; on exception returns `SelfExtractionResult(candidates=[])`
   - 10.4 Fast path: if `not result.candidates` → return immediately (no DB write)
   - 10.5 Logs debug: `extract: candidates=N`
   - 10.6 `accumulate_traits(user_id, result.candidates, db)` [SS:30] → `upserted: int` — see §10a
   - 10.7 `db.commit()`
   - 10.8 Logs debug: `traits: upserted=N`

---

### 10a. `accumulate_traits()` [SS:30]
> Pure upsert — the LLM only returns new or changed traits, so every candidate is either a fresh insert or an intentional value update.

   - **No existing row** (new trait):
      - Insert with `is_active=True`, `evidence_count=1`, `confidence_score = candidate.confidence_estimate`
      - `first_observed_at = last_observed_at = now`
   - **Existing row** (value changed):
      - `row.previous_value = row.value; row.value = candidate.value` — old value preserved in `previous_value`
      - `evidence_count += 1`, `is_active = True` (re-activates if consolidator had demoted), `last_observed_at = now`
      - `confidence_score = min(1.0, row.confidence_score + 0.1 * candidate.confidence_estimate)`
      - Note: code also handles the case where `row.value == candidate.value` defensively (no value write, evidence still increments) — this should not occur in normal operation since the LLM is instructed not to return already-captured traits
   - Returns `upserted: int` (count of rows inserted or updated)

---

## 11. Graph edge functions [GE]
> Called during encode to maintain the event graph for C3 graph expansion.

   - **`strengthen_temporal_links(user_id, source_engram_ids, new_engram_id, db)`** [GE:51]:
      - For each `old_id` in `source_engram_ids`: `upsert_link(user_id, old_id, new_engram_id, TEMPORAL, TEMPORAL_BONUS, db)`
      - Called by: Path A `create_new_branch`, `_create_new_event` on non-empty active list

   - **`strengthen_retrieval_links(user_id, used_engram_ids, db)`** [GE:66]:
      - Guard: `len(used_engram_ids) < 2` → return immediately
      - All-pairs: `[(i, j) for i in range(N) for j in range(i+1, N)]` → each pair calls `upsert_link(..., RETRIEVAL, RETRIEVAL_BONUS, db)`
      - Called by: Path A `update_existing` when 2+ engrams were used

   - **`upsert_link(user_id, source_id, target_id, link_kind, delta, db)`** [GE:20]:
      - Canonical order: `a, b = sorted([source_id, target_id])` — ensures bidirectional dedup (SIMILARITY/RETRIEVAL/TEMPORAL/TRIADIC only — not MENTION, which is directional)
      - If link exists: `link.weight = (link.weight or 0) + delta`; update `last_updated`
      - If not exists: `db.add(EngramLink(..., weight=delta))`
      - `db.flush()` — not commit

---

### Edge weight constants [config.py]
| Constant | Default | Used for |
|---|---|---|
| `DEFAULT_EDGE_SIMILARITY_ALPHA` | `0.1` | SIMILARITY links (FAISS neighbors) |
| `DEFAULT_EDGE_TRIADIC_BONUS` | `0.02` | TRIADIC closure bonus |
| `DEFAULT_EDGE_RETRIEVAL_BONUS` | `0.15` | RETRIEVAL links (co-synthesized engrams) |
| `DEFAULT_EDGE_TEMPORAL_BONUS` | `0.15` | TEMPORAL links (predecessor → new event) |
| `DEFAULT_EDGE_TOP_K` | `20` | FAISS neighbors considered for real-time edge processing |
| `DEFAULT_EDGE_MIN_SIMILARITY` | `0.75` | Minimum FAISS score for a neighbor to receive a SIMILARITY edge |

---

## 12. Embedding + FAISS utilities [VB]

### 12a. `compute_content_hash(core_intent, updates)` [VB:16]
   - `content = f"{core_intent} {' '.join(updates or [])}"`
   - Returns `SHA256(content.encode()).hexdigest()[:16]` — first 16 hex chars (64-bit fingerprint)
   - Used to detect whether engram content changed before re-embedding

### 12b. `embed_engram(engram_id, core_intent, updates, embedding_svc)` [VB:22]
   - Embed text: `f"{core_intent} {' '.join(updates or [])}"` — same concatenation as content hash
   - Calls `embedding_svc.embed(content)` → vector
   - Returns `(vector, content_hash)` or `None` on exception (warning logged, non-fatal)

### 12c. `add_to_faiss_realtime(user_id, engram_id, vector, content_hash, faiss_svc, index, db)` [VB:39]
   - Queries Engram row for `user_id + engram_id`; `remove_if_exists = existing is not None`
   - `faiss_svc.add_vector(engram_id, vector, index, remove_if_exists=..., user_id=user_id)` — refreshes or adds
   - Updates `existing.content_hash = content_hash` in DB
   - `db.flush()` — not commit
   - Logs debug: `faiss_refresh` or `faiss_add`

### 12d. `_build_entity_embed_text(canonical_name, entity_type, facts)` [E:37]
   - `parts = [f"{canonical_name} ({entity_type})"]`
   - If facts: `parts.append("\n".join(facts))`
   - Returns `"\n".join(parts)` — name/type header + newline-separated facts
   - Note: does NOT include `summary_text` (that's added during consolidation enrichment)

---

## 13. Real-time link processing — `process_links_realtime()` [VE:47]
> Creates SIMILARITY + TRIADIC links after any engram create/update. Called from both Path A and Path B via `_update_event_content` and `_create_new_event`.

   - 13.1 **SIMILARITY links**: `top_k_similar(vector, user_id, engram_id, TOP_K, db, faiss_svc, index)` → `neighbors: List[(uuid, score)]`
      - FAISS search returns `TOP_K + 1` results; excludes self; filters by `score >= MIN_SIMILARITY` (default 0.75)
      - `id_to_uuid` map built from DB to resolve FAISS integer IDs → engram UUIDs
      - For each neighbor: `upsert_link(..., SIMILARITY, ALPHA=0.1, db)` — weight accumulates on repeated co-occurrence
      - Pair deduplicated via `processed_pairs: Set[Tuple[str, str]]` (canonical sorted pair)
   - 13.2 **TRIADIC closure**: for each pair `(a, b)` among neighbors:
      - Check if existing SIMILARITY link between `a` and `b` exists in DB
      - If yes: `upsert_link(a, b, TRIADIC, TRIADIC_BONUS=0.02, db)` — strengthen the triangle's weakest side
      - Pair deduplicated via same `processed_pairs` set
   - 13.3 `db.flush()` — not commit
   - 13.4 Returns list of neighbor engram IDs

---

## Actions summary

| `used_engram_ids` | drift / LLM result  | `action` returned   |
|-------------------|---------------------|---------------------|
| non-empty         | `update_existing`   | `update_existing`   |
| non-empty         | `create_new_branch` | `create_new_branch` |
| empty             | LLM → create        | `create_new`        |
| empty             | LLM → ETS stored    | `append_trace`      |
| empty             | LLM → ETS skip      | `skip`              |
| (no history)      | —                   | `skip`              |
