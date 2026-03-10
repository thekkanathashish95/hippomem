# retrieve() Codeflow

> File refs: `S` = service.py, `RS` = retrieve/service.py, `SK` = retrieve/schemas.py, `SC` = decoder/scoring.py, `BM` = infra/bm25.py, `GQ` = infra/graph/queries.py

---

## 1. `MemoryService.retrieve()` [S]
   - 1.1 Async entry point; all params keyword-only except `user_id` and `query`
   - 1.2 `mode` ∈ `{"faiss", "bm25", "hybrid"}` (default `"hybrid"`)
   - 1.3 `top_k` — max primary episodes returned (default 5)
   - 1.4 `entity_count` — max entities attached per episode (default 4)
   - 1.5 `graph_count` — max related episodes attached per episode via graph edges (default 5)
   - 1.6 `exclude_uuids` — optional list of engram UUIDs to skip in all phases
   - 1.7 Scoring weight overrides: `w_sem`, `w_rel`, `w_rec` (pass-through to composite scorer; `None` = use config defaults)
   - 1.8 `asyncio.get_running_loop().run_in_executor(None, _retrieve_sync, ...)` — runs sync work in thread pool; returns `RetrieveResult`
   - No degraded fallback — propagates exceptions to caller (unlike `decode()`)

---

## 2. `_retrieve_sync()` [S]
   - 2.1 `db = self._get_db()` — open DB session; closed in `finally` block
   - 2.2 Delegates entirely to `self._retrieve_svc.retrieve(...)` — thin wrapper
   - 2.3 Returns `RetrieveResult` from `RetrieveService`

---

## 3. `RetrieveService.retrieve()` [RS]
> Mode-driven primary retrieval, composite scoring, then per-episode enrichment.

   - 3.1 Resolve effective values: `rrf_k`, `bm25_ttl`, `w_sem/w_rel/w_rec` — override params take precedence over config defaults
   - 3.2 Validate: `top_k < 0` → `ValueError`; unknown `mode` → `ValueError`
   - 3.3 **FAISS phase** (if `mode in {"faiss", "hybrid"}`):
      - Embed `query` → `query_vec` (numpy float32)
      - `self._faiss.load_index(user_id)` → `faiss_index`
      - Guard: `faiss_index is None or ntotal == 0`:
         - `mode == "faiss"` → return empty `RetrieveResult(episodes=[], total_primary=0)` immediately
         - `mode == "hybrid"` → continue (BM25-only fallback)
      - `self._faiss.search(query_vec, top_k * 3, faiss_index, user_id)` → raw `(faiss_id, score)` pairs
      - `self._faiss.build_id_to_uuid_map(user_id, db)` — map FAISS int64 IDs → string UUIDs
      - Deduplicate: first occurrence of each uuid wins → `faiss_uuids` list + `faiss_uuid_to_score` dict
   - 3.4 **BM25 phase** (if `mode in {"bm25", "hybrid"}`):
      - `self._bm25.retrieve(query, user_id, db, top_k * 3, bm25_ttl)` → `bm25_uuids` list (see §BM)
   - 3.5 **Merge**:
      - `mode == "faiss"`: `merged_uuids = faiss_uuids`
      - `mode == "bm25"`: `merged_uuids = bm25_uuids`
      - `mode == "hybrid"`: `_rrf_merge(faiss_uuids, bm25_uuids, k=rrf_k)` → `(merged_uuids, uuid_to_rrf)` — see §4
   - 3.6 **Primary candidate collection** — iterate `merged_uuids` in merged order:
      - Skip if uuid in `exclude` or `seen`; add to `seen` immediately
      - DB lookup: `Engram` row filtered by `user_id + engram_id`
      - **Filter**: skip if no row, no `core_intent`, or `engram_kind` not in `{EPISODE, SUMMARY}`
      - **Source label**: `"hybrid"` if in both lists, `"faiss"` if FAISS-only, `"bm25"` if BM25-only
      - `cosine = faiss_uuid_to_score.get(uuid, 0.0)` — 0.0 for BM25-only hits
      - **Composite score**: `score_engram_with_breakdown(cosine, relevance_score, last_updated_at, w_sem, w_rel, w_rec)` — see §SC
      - `rrf_score = uuid_to_rrf.get(uuid)` — `None` for non-hybrid modes
      - Collect up to `top_k` candidates; stop iterating once reached
   - 3.7 Sort `primary_candidates` by composite score descending
   - 3.8 **Per-episode enrichment** — for each primary candidate:
      - `_load_entities_for_episode(user_id, episode_uuid, db, entity_count)` — see §5
      - `_load_related_episodes(user_id, episode_uuid, db, graph_count, exclude, seen, query_vec, faiss_index, w_sem, w_rel, w_rec)` — see §6
      - Assemble `RetrievedEpisode(graph_hop=0, entities=..., related_episodes=...)`
   - 3.9 Return `RetrieveResult(episodes=episodes, total_primary=len(episodes))`

---

## 4. `_rrf_merge(faiss_uuids, bm25_uuids, k)` [RS]
> Reciprocal Rank Fusion — same algorithm as C3 in the decode path.

   - `score(d) = Σ 1/(k + rank + 1)` where rank is 0-indexed (note: +1 offset vs decode's C3 which uses 1-indexed)
   - Items in both lists receive additive boost
   - Returns `(merged_uuids, uuid_to_rrf_score)` — uuid_to_rrf passed through for per-episode `rrf_score` field
   - `rrf_k` configurable (default from config, typically 60)

---

## 5. `_load_entities_for_episode()` [RS]
> Entities linked to a primary episode via MENTION edges, ranked by mention type.

   - Guard: `max_entities <= 0` → return `[]`
   - Query `EngramLink` for `link_kind=MENTION`, `source_id=episode_uuid`, `user_id=user_id`
   - No links → return `[]`
   - `MENTION_PRIORITY = {protagonist: 0, subject: 1, referenced: 2}` (unknown → 99)
   - `entity_best` dict: keep lowest (best) priority per entity UUID across all links
   - Batch-load `Engram` rows: `engram_id IN (entity_uuids)`, `engram_kind=ENTITY`, `user_id=user_id`
   - Skip entities with no `core_intent`
   - Sort: `mention_priority` asc, then `reinforcement_count` desc within same tier
   - Cap at `max_entities`; full method wrapped in try/except → `[]` on any DB failure
   - Returns `List[RetrievedEntity]` with `graph_hop=0`, `source="mention"`

---

## 6. `_load_related_episodes()` [RS]
> 1-hop graph neighbors of a primary episode, scored and returned as flat `RetrievedEpisode` list.

   - Guard: `graph_count <= 0` → return `[]`
   - `get_neighbors(user_id, episode_uuid, db, min_weight=0.1)` [GQ] → `(neighbor_uuid, edge_weight)` pairs
   - Sort neighbors by edge weight descending; iterate top `graph_count`
   - Skip if neighbor in `exclude` or `seen`; add to `seen` before DB lookup (prevents cross-episode duplicates)
   - DB lookup + kind filter same as primary (EPISODE/SUMMARY, non-null core_intent)
   - **Semantic score**: if `query_vec` available, `self._faiss.get_vector(nh_uuid, faiss_index)` → `_cosine_sim(query_vec, vec)` — no new embedding call; `cosine=0.0` if vector absent or index unavailable
   - Composite score via `score_engram_with_breakdown(...)` with same weights as primary
   - Assembled as `RetrievedEpisode(graph_hop=1, source="graph")` — no recursive entity/related loading
   - Full method wrapped in try/except → `[]` on any failure

---

## 7. Scoring [SC]
> Same `score_engram_with_breakdown()` shared with C2/C3 in the decode path.

   - `combined = w_sem * cosine + w_rel * relevance_score + w_rec * recency_bias`
   - Default weights: `w_sem=0.5, w_rel=0.3, w_rec=0.2` (from config)
   - Recency bias: linear decay from 1.0 (0h) → 0.5 (168h) → 0.0 (~336h); `last_updated=None` → 0.0
   - Returns `(combined_score, breakdown_dict)` — breakdown not surfaced in `RetrieveResult` (only composite score exposed)

---

## 8. Schemas [SK]

   - **`RetrievedEntity`** (dataclass): `event_uuid`, `core_intent`, `score=None`, `source="mention"`, `event_kind="entity"`, `entity_type`, `summary_text`, `updates`, `cosine_score=None`, `rrf_score=None`, `graph_hop=None`
   - **`RetrievedEpisode`** (dataclass): `event_uuid`, `core_intent`, `score`, `source`, `event_kind`, `summary_text`, `updates`, `entity_type`, `cosine_score`, `rrf_score`, `graph_hop` (0=primary, 1=related), `entities: List[RetrievedEntity]`, `related_episodes: List[RetrievedEpisode]`
   - **`RetrieveResult`** (dataclass): `episodes: List[RetrievedEpisode]`, `total_primary: int`
   - **`retrieve_result_to_dict()`**: JSON-serializable dict; uses `_episode_to_dict()` (recursive) + `asdict()` for entities
   - Source values: `"faiss"` | `"bm25"` | `"hybrid"` (primary episodes), `"graph"` (related episodes), `"mention"` (entities)

---

## Retrieve vs decode — key differences

| Aspect | `retrieve()` | `decode()` |
|--------|-------------|------------|
| Purpose | Raw search API — caller processes results | Inject context into LLM prompt |
| Output | Hierarchical episodes + entities + related | Synthesized text string (`context`) |
| LLM calls | None | C1 continuation check + synthesis |
| Error handling | Propagates exceptions | Degrades to empty context |
| Thread model | `run_in_executor` (same) | `run_in_executor` (same) |
| BM25 index freshness | No invalidation on retrieve | BM25 invalidated by `encode()` |
| Graph expansion | Per-episode `related_episodes[]`, flat | C3 global expansion, merged before synthesis |
| Entity loading | Per-episode `entities[]`, via MENTION links | Global injection via `_load_linked_entities()` |
