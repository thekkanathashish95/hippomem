# Changelog

All notable changes to hippomem are documented here.

---

## [0.4.0] - 2026-09-05

Trust-foundation release. The daemon is no longer an open localhost API by default once you set a token.

### Breaking
- `GET /traces/{id}` and `GET /turn-status/{id}` require a `user_id` query parameter and return only that user's rows.
- `GET /config/models` no longer accepts `api_key` / `base_url` query parameters. Probe a key with `POST /config/models` and a JSON body.
- LLM API keys are never written to `hippomem_config.json`. They live in `LLM_API_KEY` or `secrets.json` (mode `0600`).
- Inspector call logs no longer store raw prompts/responses by default (`store_raw_llm_prompts=False`). Old traces may still contain prompts until TTL prune (`inspector_ttl_days`, default 7).
- NLTK is removed. BM25 tokenization uses a built-in stopword list and **does not stem**. Retrieval scores can shift vs 0.3.0.
- `hippomem serve --host 0.0.0.0` (or `::`) exits with code 2 unless `HIPPOMEM_API_TOKEN` or `HIPPOMEM_TOKENS` is set.
- CORS is limited to localhost / `127.0.0.1` plus `HIPPOMEM_CORS_ORIGINS` (no `*`).
- Studio Dashboard lives at `/dashboard`. `/` redirects there.

### Added
- Optional scoped bearer auth: `HIPPOMEM_API_TOKEN` (admin, all users) and `HIPPOMEM_TOKENS=name:token:ns=<prefix>[:admin]`.
- `DELETE /users/{id}?confirm=true` (admin) and `GET /users/{id}/export` (`schema_version: 1`).
- `MemoryService.delete_user` / `export_user` and matching `HippoMemClient` methods.
- `HippoMemClient(..., token=)` (or `HIPPOMEM_API_TOKEN`).
- Per-user lock around encode, consolidate, and delete so concurrent writes cannot corrupt a FAISS index.
- Studio: daemon token field (browser `localStorage`), `/dashboard` route, clearer errors when the key or token is missing.
- GitHub Actions CI (pytest, ruff, bandit, blocking pip-audit) and tag-triggered PyPI release (`v*`).

### Fixed
- `Dict` was used without import in `consolidator/service.py` (runtime `NameError` on the persona-summary path).
- Unused `compute_content_hash` import in the same module.

---

## [0.3.0] - 2026-03-15

### Added
- **Self memory**: confidence-gated persona activation with structured traits (name, age, occupation, personality, interests, social connections) and pending trait injection into context
- **`pending_facts` + `needs_consolidation` flag**: cleaner handoff between encoder and consolidation — facts accumulate in working state and are promoted during consolidation
- **Anchor entity extraction**: decoder hints (H-prefix aliases) guide the encoder to extract facts anchored to the correct entity
- **Server deps moved to core**: no more `[server]` extra needed — `pip install hippomem` includes everything

### Fixed
- NLTK no longer downloads corpora on startup
- Event updates constrained to 1–2 sentences / 30 words max, preventing runaway memory entries
- Studio: refresh buttons added to Entities and Self Memory views
- Studio: scroll-to-bottom button visibility corrected
- Studio: all datetimes displayed in user local time
- Studio: persona shown correctly in Self tab; entity facts label and social category fixed
- Studio: consolidated vs. pending facts split clearly in episode and entity panels

---

## [0.2.0] - 2026-02-01

### Added
- Background consolidation (asyncio, no Celery) via `MemoryConfig.enable_background_consolidation`
- `retrieve()` API — raw semantic + BM25 hybrid search
- Real-time decode/encode progress via SSE stream in Studio chat
- Syntax highlighting and improved code block rendering in Studio
- Retrieve API, conversation turn storage, and pre-publish quality fixes

### Fixed
- Various Studio UI fixes (local time display, personas → entities rename, dashboard metrics table)

---

## [0.1.0] - 2026-01-01

### Added
- Initial release: core memory encode/decode pipeline
- C1/C2/C3 retrieval cascade (continuation check → local scan → long-term retrieval)
- SQLite-backed event store and working state
- FAISS vector index
- `MemoryService` public API: `decode()`, `encode()`, `consolidate()`, `retrieve()`
- hippomem daemon + Studio UI
