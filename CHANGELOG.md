# Changelog

All notable changes to hippomem are documented here.

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
- C1/C2/C3 retrieval cascade (continuation check → synthesis → context building)
- SQLite-backed event store and working state
- FAISS vector index
- `MemoryService` public API: `decode()`, `encode()`, `consolidate()`, `retrieve()`
- hippomem daemon + Studio UI
