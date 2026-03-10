# decode() Codeflow

> File refs: `S` = service.py, `SY` = decoder/synthesizer.py, `DL` = decoder/llm_ops.py, `LS` = decoder/local_scan.py, `LT` = decoder/long_term.py, `SC` = decoder/scoring.py, `CB` = decoder/context_builder.py, `SK` = decoder/schemas.py, `BM` = infra/bm25.py

---

## 1. `MemoryService.decode()` [S]
   - 1.1 Normalize `conversation_history` (default to `[]`)
      - Caller passes prior completed turns only; current turn is NOT included here
   - 1.2 `on_step`: optional `Callable[[str], None]` — called from the thread-pool executor with a human-readable step label as each decode phase begins; bridge to async via `loop.call_soon_threadsafe` if needed
   - 1.3 `turn_id`: optional pre-generated UUID — if provided, used as-is; if omitted, generated internally in `_decode_sync`
   - 1.4 `asyncio.get_event_loop().run_in_executor(None, _decode_sync, ...)` — awaited (blocking until done) to preserve ordering: caller receives context before passing to LLM

---

## 2. `_decode_sync()` [S]
   - 2.1 `turn_id = turn_id or str(uuid.uuid4())` — links this decode to its paired encode
   - 2.2 Create `LLMCallCollector` + set `_current_collector` context var (captures all downstream LLM calls)
   - 2.3 `t0 = time.perf_counter()` — start latency timer
   - 2.4 `db = self._get_db()` — open DB session; closed in `finally` block
   - 2.5 `ContextSynthesizer.synthesize(...)` → returns `synthesis` dict
      - Wrapped in try/except: any failure (DB, FAISS, LLM) degrades to `{synthesized_context: "", used_engram_ids: [], used_entity_ids: [], reasoning: "", cascade: "C2"}` — decode never raises to the caller
   - 2.6 Extract fields from `synthesis`:
      - `context = synthesized_context`
      - `formatted = "## Memory Context\n\n{context}"` — empty string if no engrams surfaced
      - `used = used_engram_ids`
      - `used_entities = used_entity_ids`
      - `cascade` — C1 / C2 / C3 label for observability
   - 2.7 Log INFO: `decode: user=... cascade=... engrams=N ms=... turn_id=...` (ms from perf_counter)
   - 2.8 Cache `(user_id, session_id) → (turn_id, used_engram_ids)` in `_last_decode_cache`
      - Bounded `OrderedDict` (max 500 entries); value set → `move_to_end()` → eviction check (true LRU)
      - Oldest key evicted when over capacity
      - Note: `used_entity_ids` is NOT cached here — only `used_engram_ids`
   - 2.9 Build and return `DecodeResult(context, used_engram_ids, reasoning, synthesized_context, used_entity_ids=[], turn_id)`
   - 2.10 `_persist_interaction("decode", ...)` → write `LLMInteraction` + `LLMCallLog` rows
      - Output stored: `{used_engram_ids, used_entity_ids, context, reasoning}`
      - Only writes if `collector.records` is non-empty (no LLM call = no row)

---

## 3. `ContextSynthesizer.synthesize()` [SY]
   - 3.1 `get_conversation_window(conversation_history, num_turns)` → last N prior turns as `"User: ...\nAssistant: ..."` string — see §CB
   - 3.2 `_load_event_context()` → `(active_events, dormant_objectives)` — single DB round-trip — see §3a
   - 3.3 `current_active_event = active_events[0] if active_events else None`
   - 3.4 **C1: Continuation Check** (skip if no active events)
      - `on_step("Checking continuation")`
      - **(LLM)** `DecoderLLMOps.check_continuation(message, conversation_window, active_events[0])` [DL]
      - Returns `ContinuationResult(decision, confidence, reasoning)`
      - `decision` ∈ `{CONTINUE, SHIFT, UNCERTAIN}`; `confidence` ∈ [0, 1]
      - Wrapped in try/except; failure sets `c1_result = None` (treated as UNCERTAIN)
      - Logs debug: `C1: decision=... conf=... → skipping C3 / continuing`
   - 3.5 **C2: Local Scan** → `LocalScanRanker.scan_and_rank()` — see §4
      - `on_step("Scanning memories")`
      - **Skipped** when C1 returned `CONTINUE` with `confidence >= continuation_threshold`; in that case `c2_result = LocalScanResult(events=[], high_confidence=True)` — saves a query embedding round-trip
      - Logs debug: `C2: skipped (C1 CONTINUE high confidence)` or `C2: high_confidence=... → ...`
      - Runs in all other cases: no active events, C1 failed, C1 returned SHIFT/UNCERTAIN, or C1 confidence below threshold
   - 3.6 **Escalation decision**:
      - `should_escalate = (c1 is None OR decision in {SHIFT, UNCERTAIN} OR confidence < threshold) AND NOT c2.high_confidence`
   - 3.7 **C3: Long-Term Retrieval** (only if `should_escalate`) → `LongTermRetriever.retrieve()` — see §5
      - `on_step("Retrieving long-term memories")`
      - `exclude_uuids` = non-None uuids from active + dormant via `e.get("event_uuid") or e.get("event_id")`
      - Wrapped in try/except; failure leaves `c3_result = None` — cascade proceeds without C3 results
   - 3.8 `_collect_events_for_synthesis()` → `(events_for_synthesis, id_to_uuid, cascade)` — see §6
   - 3.9 Guard: empty `events_for_synthesis` → return empty result `(cascade="C2")`
   - 3.10 `_load_self_profile(user_id, db)` → `(self_profile, source)` — see §8
      - Logs debug: `self_profile: source=persona|traits|none`
   - 3.11 **Entity injection** (only if `enable_entity_extraction`) → `_load_linked_entities(event_uuids, user_id, db)` — see §7
      - `event_uuids` = event_uuid values from `events_for_synthesis` (None values filtered out)
      - Logs debug: `linked_entities: count=N` if any found
   - 3.12 Build `entity_id_to_uuid = {"N1": uuid, "N2": uuid, ...}` from `linked_entities` in same order as N-prefix assignment in `_build_synthesis_prompt` — ensures N-ids resolve correctly in `used_entity_ids`
   - 3.13 `on_step("Synthesizing context")` → `_synthesize_with_llm(events, id_to_uuid, message, self_profile, linked_entities, entity_id_to_uuid)` — see §9
   - 3.14 Attach `cascade` to result
   - 3.15 Build reverse `uuid_to_id` map for debug log only; log debug: `synthesis: events_used=N display_ids=[...]`
   - 3.16 Return result

---

### 3a. `_load_event_context()` → `_load_events_from_event_store()` [SY]
   - **`_load_event_context()`**:
      - `_load_working_state(user_id, session_id, db)` → `WorkingStateData` or `None`
         - Queries `WorkingState.for_scope(db, user_id, session_id).first()`; returns None on failure or missing record
      - Returns `([], [])` if no working state found
      - Active: from `WorkingState.active_event_uuids`, query `Engram` rows, id_prefix=`"E"`
      - Dormant: from `WorkingState.recent_dormant_uuids[:max_dormant_events]`, id_prefix=`"D"`
      - Both use `_load_events_from_event_store()` which catches DB failures and returns `[]`
   - **`_load_events_from_event_store(user_id, event_uuids, db, id_prefix)`**:
      - Batch query: `Engram.engram_id.in_(event_uuids)` + `core_intent IS NOT NULL` + `engram_kind != ENTITY`
      - Builds `uuid_to_row` dict from results
      - **Iterates in working-state order** (not DB row order) so `E1`, `E2`, ... match working state position
      - Skips any uuid not found in query result (e.g. deleted engrams)
      - Each event dict: `{event_id, event_uuid, core_intent, updates, event_kind, entity_type, summary_text}`

---

## CB. `context_builder.py` [CB]
> Pure formatting utilities — no DB access. Stateless; callers own `conversation_history`.

   - **`get_conversation_window(conversation_history, num_turns=2)`**:
      - Takes last `num_turns` pairs from `conversation_history`; formats as `"User: ...\nAssistant: ..."` joined by `\n`
      - Returns `""` if `conversation_history` is empty
      - Used by C1, C2 search input, and C3 search input
   - **`format_recent_turns(conversation_history, num_turns)`**:
      - Returns last `(num_turns - 1)` prior turns, excluding the current (last) turn
      - Returns `"(No previous turns)"` if empty or `num_turns <= 1`
      - Used by the encoder (not the decoder cascade)

---

## 4. C2 — `LocalScanRanker.scan_and_rank()` [LS]
> Scores all active + dormant events against the current query.

   - 4.1 Guard: no `embedding_service` → return `LocalScanResult(events=[], high_confidence=False)`
   - 4.2 `search_input = f"{query}\n\n{conversation_window}".strip()` (conversation_window only appended if truthy)
   - 4.3 Embed `search_input` → `query_vec` (numpy float32); embedding failure returns empty `LocalScanResult`
   - 4.4 Concatenate `all_candidates = active_events + dormant_events`
   - 4.5 Single batch DB query to enrich all candidates with `_relevance_score` + `_last_updated`:
      - One `IN` query for all uuids across both active and dormant
      - DB failure falls back to defaults (`relevance=1.0`, `last_updated=None`)
      - Temp fields `_relevance_score`, `_last_updated` written directly onto event dicts; **popped before returning**
   - 4.6 `_get_event_embeddings(candidates, user_id, zero_vec)` — see §4a
   - 4.7 Score active events (indices `0..len(active)-1` in embeddings list):
      - `sem = _cosine_similarity(query_vec, event_vec)` — cosine mapped to [0,1] via `(sim+1)/2`; clamps to `[0, 1]`
      - `score, breakdown = score_engram_with_breakdown(sem, rel, lu, w_sem, w_rel, w_rec, engram_id=eid)`
      - Accumulates `scored_active: List[(score, event, breakdown)]`
   - 4.8 Score dormant events (indices `len(active)..` using offset `off = len(active_events)`)
   - 4.9 Sort active and dormant separately descending by score
   - 4.10 Take `top_active=3` from scored_active + `top_dormant=2` from scored_dormant
   - 4.11 `top_score = max(best_active_score, best_dormant_score)` — computed from the full pre-slice sorted lists (not just selected events)
   - 4.12 `high_confidence = top_score >= threshold`
   - 4.13 Pop temp `_relevance_score` and `_last_updated` fields from selected events
   - 4.14 Logs debug: `scan: active=N dormant=N → top_active=N top_dormant=N high_confidence=...`
   - 4.15 Return `LocalScanResult(events=top_a+top_d, high_confidence, score_breakdowns=breakdowns_a+breakdowns_d)`

---

### 4a. `_get_event_embeddings()` [LS]
> Retrieve vectors for all candidates; prefer FAISS reconstruct, fall back to embed_batch.

   - Load index once: `self.faiss_service.load_index(user_id)` (not `get_or_create_index`)
   - For each event: try `faiss_svc.get_vector(uuid, index)` → if found, add to `result` dict
   - Collect events without a FAISS vector into `need_embed` list (index, text pairs)
   - If `need_embed` is non-empty and embedding_service available:
      - `embedding_service.embed_batch(texts)` — one batch call for all missing vectors
      - If batch call fails entirely: use `fallback_zero` vector for all events in the batch; per-index fallback if partial result
   - Return vectors in same positional order as input `events` list

---

## 5. C3 — `LongTermRetriever.retrieve()` [LT]
> Hybrid FAISS + BM25 retrieval with RRF fusion, graph expansion, and composite scoring.
> Only episodic engrams (EPISODE, SUMMARY) returned — entities injected separately via MENTION links.

   - 5.1 `exclude = set(exclude_uuids)` — used for O(1) membership checks
   - 5.2 `search_input = f"{query}\n\n{conversation_window}".strip()` — same concatenation as C2
   - 5.3 Embed `search_input` → `query_vec` (numpy float32); embedding failure returns empty `LongTermResult`
   - 5.4 Load FAISS index; guard: `index is None or index.ntotal == 0` → return empty `LongTermResult`
   - 5.5 **FAISS search**: `faiss_svc.search(query_vec, top_k * 2, index, user_id)` → raw `(faiss_id, score)` pairs
      - `faiss_svc.build_id_to_uuid_map(user_id, db)` — maps FAISS int64 IDs back to string UUIDs
      - Deduplicates: first occurrence of each uuid wins; builds `faiss_uuid_to_score` dict
   - 5.6 **BM25 search** (if `enable_bm25`): `BM25Retriever.retrieve(search_input, user_id, db, top_k * 2, ttl_seconds)` → `bm25_uuids` (ranked) — see §5a
      - `search_input` (not just `query`) is passed; TTL from `bm25_index_ttl_seconds` config
      - Logs debug: `BM25: hits=N`
   - 5.7 **RRF merge**: `_rrf_merge(faiss_uuids, bm25_uuids, k=rrf_k)` → single `merged_uuids` list — see §5b
   - 5.8 **Primary event collection** — iterate `merged_uuids` in RRF order:
      - Skip if uuid in `exclude` or `seen`; add to `seen` immediately
      - DB lookup in try/except (failed lookups skip that uuid)
      - **Kind filter**: skip if `engram_kind` not in `{EPISODE.value, SUMMARY.value}` or `core_intent` is None
      - `sem = faiss_uuid_to_score.get(uuid, 0.0)` — 0.0 for BM25-only hits
      - **Composite score**: `score_engram_with_breakdown(sem, relevance_score, last_updated_at, ...)`
      - `source`: `"faiss"` if uuid in `faiss_uuid_to_score`, else `"bm25"`
      - Event dict: `{event_uuid, core_intent, score, source, event_kind, entity_type, summary_text, updates}`
      - Collect up to `top_k=5` primary events; stop iterating once reached
   - 5.9 **Graph expansion** (if `enable_graph_expansion and graph_hops >= 1 and max_graph_events > 0 and primary_events`):
      - `graph_hops >= 1` acts as on/off guard; actual expansion is always 1 hop via `get_neighbors`
      - For each seed uuid: `get_neighbors(user_id, seed_uuid, db, min_weight=0.1)` → `(neighbor_uuid, weight)` pairs
         - Each seed call individually wrapped in try/except; failure skips that seed
      - Build `candidate_weights` dict: max edge weight per neighbor uuid across all seeds
      - Skip neighbors already in `exclude` or `seen`; sort by edge weight desc; take top `max_graph_events`
      - For each candidate: `faiss_svc.get_vector(uuid, index)` → semantic score via `_cosine_sim` (no new embedding call; `sem=0.0` if absent)
      - DB lookup + kind filter same as primary collection; source=`"graph"`; `seen.add(nh_uuid)` before DB lookup
   - 5.10 Merge `primary_events + graph_expanded`; **sort by composite score descending** → `all_events`
   - 5.11 Logs debug: `C3 result: primary=N graph=N total=N` and `graph_expand: seed_ids=N → expanded=N (hops=N)`
   - 5.12 Return `LongTermResult(events=all_events, graph_expanded=graph_expanded, total_found=len(all_events))`
      - `graph_expanded` contains only graph-sourced events; `events` is the full merged list

---

### 5a. `BM25Retriever` [BM]
> Keyword retrieval over all episodic engrams per user; index cached with TTL.

   - Index text: `core_intent + " " + " ".join(updates)` per engram
   - **Tokenizer** (`_tokenize`): lowercase → regex word tokens (`\b[a-z0-9]+\b`) → filter `len(token) > 1` → NLTK stopword removal → Porter stemming
      - Stemmed token also checked against stop words (double-filter)
      - NLTK `stopwords` and `PorterStemmer` lazy-loaded at class level (one copy per process); hardcoded fallback stopword set if NLTK unavailable
      - Stemming failure on individual token: falls back to unstemmed token
   - **Index** (`_build_index`): queries all `EPISODE`/`SUMMARY` engrams with non-null `core_intent`; builds tokenized corpus; constructs `BM25Okapi`; returns `(None, [])` on import error, DB failure, empty corpus, or fully empty token corpus
   - **Cache** (`_get_or_build`): `user_id → (BM25Okapi, corpus_ids, built_at)`; returns cached if `time.monotonic() - built_at < ttl_seconds`, else rebuilds
   - **`retrieve(query, user_id, db, top_k, ttl_seconds)`**: tokenize query → `bm25.get_scores(query_tokens)` → `argsort` descending → return `[{"event_uuid", "bm25_score"}]` for `score > 0` hits up to `top_k`; returns `[]` on empty token result or any failure
   - **`invalidate(user_id)`**: `self._cache.pop(user_id, None)` — force rebuild on next call (called by encoder after encode to keep index fresh)

---

### 5b. `_rrf_merge(faiss_uuids, bm25_uuids, k=60)` [LT]
> Reciprocal Rank Fusion over two ranked lists.

   - `score(d) = Σ 1/(k + rank)` where rank is 1-indexed; accumulated across both lists
   - Items appearing in both lists receive additive boost
   - `rrf_k` is configurable (default 60); higher k reduces rank sensitivity
   - Returns merged list of uuids sorted by RRF score descending
   - Logs debug: `C3 candidates: faiss=N bm25=N rrf_merged=N`

---

## 6. `_collect_events_for_synthesis()` [SY]
> Merges cascade outputs into a single flat event list with stable display IDs.

   - **C1 path** (CONTINUE + confidence ≥ threshold):
      - Return `[current_active]` (active_events[0]); `id_to_uuid` = full scope mapping; `cascade = "C1"`
   - **C2/C3 path**:
      - `id_to_uuid` built from active + dormant scope; `uuid_to_id` = reverse mapping
      - C2 events: iterate `c2_events`; look up display_id in `uuid_to_id`; any event not in scope → `logger.warning()` and skip (C2 only scores active/dormant — should never happen); append `{**e, "event_id": display_id}`
      - C3 events (if `c3_result and c3_result.events`): assign `L1, L2, ...` sequentially; `id_to_uuid[eid] = e.get("event_uuid", "")` mutated in-place
      - `cascade = "C3"` if `should_escalate and c3_result and c3_result.events` (non-empty), else `"C2"`
   - Return `(events, id_to_uuid, cascade)`

---

### 6a. `_build_id_to_uuid_mapping()` [SY]
> Builds display_id → uuid mapping used for uuid resolution after synthesis.

   - Active events: `event.get("event_id") or f"E{i+1}"` → `event.get("event_uuid")`
   - Dormant events: `obj.get("event_id") or f"D{i+1}"` → `obj.get("event_uuid") or obj.get("event_id")`
   - Only entries with a non-None uuid are included
   - Result used in §6 C1/C2/C3 paths; extended in-place with L-prefix entries for C3 events

---

## 7. `_load_linked_entities()` [SY]
> Post-cascade entity injection — entities linked to shortlisted events via MENTION edges.

   - Skipped if `enable_entity_extraction = False` or no event UUIDs; returns `[]`
   - Query `EngramLink` for `link_kind=MENTION`, `source_id IN (event_uuids)`, `user_id=user_id`
   - Returns `[]` immediately if no links found
   - Build `entity_best` dict: keep lowest (best) mention_type priority per entity UUID
      - `MENTION_PRIORITY = {protagonist: 0, subject: 1, referenced: 2}` (unknown type → 99)
   - Batch-load `Engram` rows for entity UUIDs, filtered to `engram_kind=ENTITY`
   - Build `candidates` list: skip entities with no `core_intent`; each entry includes `_mention_priority` and `_reinforcement_count` temp fields
   - Sort: `_mention_priority` asc, then `_reinforcement_count` desc within same tier
   - **Pop** `_mention_priority` and `_reinforcement_count` before returning
   - Cap at `max_entities=4`; full method wrapped in try/except → returns `[]` on any DB failure
   - N-prefix IDs (`N1, N2, ...`) are assigned in `_build_synthesis_prompt` (not here); entities excluded from `used_engram_ids` → tracked separately in `used_entity_ids`

---

## 8. `_load_self_profile()` [SY]
> Injects identity context into the synthesis prompt (only if `enable_self_memory`).

   - Returns `(None, "none")` immediately if `enable_self_memory = False`
   - Priority 1: Persona `Engram` (`engram_kind=PERSONA`) with `summary_text` → source=`"persona"`
      - Persona is created/updated by `consolidate_self_memory()` during consolidation
   - Priority 2: `get_active_traits(user_id, db)` + `format_traits_for_injection(traits)` → source=`"traits"`
      - Fallback when Persona Engram doesn't exist yet or has no summary_text
   - Priority 3: `(None, "none")` — self memory disabled, no traits yet, or DB failure
   - Entire method wrapped in try/except — any DB failure returns `(None, "none")`

---

## 9. `_synthesize_with_llm()` → `DecoderLLMOps.synthesize()` [SY, DL]
> Delegates synthesis to DecoderLLMOps; falls back to `_fallback_synthesis()` on any exception.

   - **`_synthesize_with_llm()`** [SY]:
      - Calls `decoder_llm_ops.synthesize(events, id_to_uuid, message, self_profile, linked_entities, entity_id_to_uuid)`
      - On any exception: `logger.warning(...)` → `self._fallback_synthesis(events_for_synthesis, id_to_uuid)` — see §9a
   - **`DecoderLLMOps.synthesize()`** [DL]:
      - 9.1 `_build_synthesis_prompt(events, user_message, prompts, self_profile, linked_entities)` → user content string — see §9b
      - 9.2 **(LLM)** `chat_structured(messages, SynthesisResponse, temp=0.3, max_tokens=4000, op="synthesis")`
         - Returns `SynthesisResponse(synthesized_context, events_used, reasoning)`
         - `events_used` → list of `EventUsed(engram_id, role)` — display ids (E/D/L/N prefixes) plus role label
      - 9.3 Resolve display ids from `events_used`:
         - `eid` in `id_to_uuid` → append uuid to `used_engram_ids`
         - `eid` in `entity_id_to_uuid` → append uuid to `used_entity_ids`
         - IDs not in either mapping are silently dropped
      - 9.4 Return `{synthesized_context, used_engram_ids, used_entity_ids, reasoning}`

---

### 9a. `_fallback_synthesis()` [SY]
> Invoked when `DecoderLLMOps.synthesize()` raises. No LLM call.

   - Empty events → return empty result with `used_entity_ids: []`
   - Non-empty: concatenate `core_intent` strings as `"Current context: intent1, intent2, ..."`
   - `used_uuids` = all uuids resolvable from `id_to_uuid` across all events (not just events_used)
   - Return `{synthesized_context, used_engram_ids=used_uuids, used_entity_ids=[], reasoning="Fallback: LLM synthesis failed."}`

---

### 9b. `_build_synthesis_prompt()` [DL]
> Constructs the user-side synthesis prompt from events, entities, and self profile.

   - Format each event via `_format_event_block(event)`:
      - **Episodic** (`event_kind != "entity"`): `[E1] Topic: {core_intent}\nUpdates:\n- ...`
      - **Entity** (`event_kind == "entity"`): `[L2 - ENTITY: {entity_type}]\nName: ...\nProfile: {summary_text}\nKnown facts:\n- ...`
   - Join event blocks with `"\n\n"` → `events_block`
   - If `linked_entities` present:
      - Assign `event_id = f"N{i+1}"` to each entity via `{**entity, "event_id": f"N{i+1}"}`
      - Format via same `_format_event_block()`, append `"\n\n**Linked Entity Profiles:**\n\n" + entity_blocks` to `events_block`
   - If `self_profile` present: `self_profile_block = f"**User Identity Profile:**\n{self_profile}\n\n---\n\n"` (else empty string)
   - Fill `prompts["user_template"]` with `{user_message, events_block, self_profile_block}` — YAML template controls placement of `self_profile_block` relative to events

---

## 10. Schemas [SK]

   - **`ContinuationResult`** (Pydantic): `decision: str`, `confidence: float [0,1]`, `reasoning: str`
   - **`EventUsed`** (Pydantic): `engram_id: str` (alias `event_id`; display id e.g. E1/D1/L1/N1), `role: str` (primary/supporting/associative)
   - **`SynthesisResponse`** (Pydantic): `synthesized_context: str`, `events_used: List[EventUsed]`, `reasoning: str`
   - **`DecodeResult`** (dataclass): `context: str`, `used_engram_ids: List[str]`, `reasoning: str`, `synthesized_context: str`, `used_entity_ids: List[str] = []`, `turn_id: str = ""`
      - `context` = `"## Memory Context\n\n{synthesized_context}"` (or `""` if empty)
      - `synthesized_context` = raw LLM output without markdown wrapper
      - Pass entire `DecodeResult` to `encode()` so hippomem updates the correct events

---

## 11. C1 LLM call — `check_continuation()` [DL]
> Prompts loaded from `hippomem/prompts/decoder.yaml` section `continuation_check`.

   - Builds prompt: `system` from YAML + `user_template.format(conversation_window, core_intent, user_message)`
   - `(no prior conversation)` substituted if `conversation_window` is empty
   - `chat_structured(messages, ContinuationResult, temperature=0.2, max_tokens=4000, op="continuation_check")`

---

## 12. Scoring — `score_engram_with_breakdown()` [SC]
> Shared by C2 (LocalScanRanker) and C3 (LongTermRetriever). Single source of truth for composite score.

   - **Recency bias** (`_compute_recency_bias`):
      - `recency_bias = max(0, min(1, 1.0 - (hours_since / 168) * 0.5))` — linear decay over ~1 week (168h)
      - `last_updated=None` → 0.0
      - At 0h: recency=1.0; at 168h: recency=0.5; beyond ~336h: recency=0.0
      - Timezone-aware: naive `last_updated` treated as UTC via `.replace(tzinfo=timezone.utc)`
   - **Combined score**:
      - `combined = w_sem * semantic_similarity + w_rel * relevance_score + w_rec * recency_bias`
      - Default weights: `w_sem=0.5, w_rel=0.3, w_rec=0.2` (from `DEFAULT_RETRIEVAL_*_WEIGHT` in config; importable constants used as defaults in both C2 and C3)
   - Returns `(combined_score, {semantic, relevance, recency, combined})` — breakdown values rounded to 4 decimal places
   - Logs debug per engram when `engram_id` param is provided: `score: engram=... total=... sem=... rel=... rec=...`
   - **`score_event()`**: simplified wrapper returning only `combined_score` float (no breakdown); same formula and defaults

   - **Cosine similarity** (local functions, not exported):
      - Both `local_scan._cosine_similarity` and `long_term._cosine_sim` implement: `(dot(a,b) / (|a||b|) + 1) / 2`, clamped to [0, 1]
      - Maps cosine space [-1,1] → [0,1]; returns 0.0 if either vector has zero norm

---

## Cascade summary

| C1 decision       | C2 high_confidence | C3 triggered | `cascade` | Events sent to LLM synthesis |
|-------------------|--------------------|--------------|-----------|------------------------------|
| CONTINUE ≥ thresh | (skipped)          | No           | C1        | active[0] only               |
| CONTINUE < thresh | True               | No           | C2        | top 3 active + top 2 dormant |
| SHIFT/UNCERTAIN   | True               | No           | C2        | top 3 active + top 2 dormant |
| SHIFT/UNCERTAIN   | False              | Yes (hits)   | C3        | C2 events + L1, L2, ... (FAISS + BM25 + graph) |
| (no active)       | False              | Yes (hits)   | C3        | L1, L2, ... (FAISS + BM25 + graph only) |
| (no active)       | False              | No hits      | C2        | (empty → no LLM call)        |
