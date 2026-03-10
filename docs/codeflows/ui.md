# UI Layer Codeflow

> File refs: `A` = studio/src/App.tsx, `SB` = layout/SessionSidebar.tsx, `DV` = dashboard/DashboardView.tsx, `CL` = layout/ChatLayout.tsx, `ME` = memory/MemoryExplorer.tsx, `SM` = memory/SelfMemoryView.tsx, `PV` = memory/PersonaView.tsx, `TV` = traces/TracesView.tsx, `SV` = settings/SettingsView.tsx

---

## Overview

The Studio UI is a React SPA (Vite + TypeScript) bundled and served by the server at `/`. It provides:

- **Single global layout**: fixed **Session Sidebar** (left) + main content area; routing is client-side via React Router.
- **Session context**: a single `user_id` (default `dev_user`) is used for all API calls; it is held in `chatStore` and consumed by dashboard, memory, traces, and settings.
- **Setup guard**: at `/`, the app calls `GET /health`; if `setup_required` is true, it redirects to `/settings` before showing the dashboard.

**Available pages** (path → layout → primary view):

| Path        | Layout          | Primary view / content |
|------------|------------------|-------------------------|
| `/`        | DashboardLayout  | DashboardView — stats, usage, quick links |
| `/chat`    | ChatLayout       | ChatMessages + ChatComposer |
| `/memory`  | MemoryLayout     | MemoryExplorer — List / Grid / Graph + EventDetailPanel |
| `/self`    | SelfLayout       | SelfMemoryView — self traits by category |
| `/personas`| PersonaLayout    | PersonaView — entities by type (people, places, etc.) |
| `/traces`  | TracesLayout     | TracesView — interactions table + StepDetailPanel |
| `/settings`| SettingsLayout   | SettingsView — Connection, Features, Advanced |

---

## 1. App shell and routing [A]

- **Router**: `BrowserRouter`; base path is `/` (SPA served at root).
- **Layout**: Full-height flex container; `SessionSidebar` (fixed width) + `Routes` in the main area.
- **Setup guard** (route `/`): Renders a wrapper that calls `GET /health`. If `setup_required === true`, redirects to `/settings` with `replace: true`; otherwise renders `DashboardLayout`. While deciding, renders `null` (blank).
- **Routes**: One `Route` per path; each path renders the corresponding layout component. No nested routes; each layout owns its full page content.

---

## 2. Session Sidebar [SB]

- **Role**: Persistent left nav; same on every page.
- **Structure**: Header “hippomem” (uppercase, muted) + vertical list of `NavLink`s.
- **Links** (path, label, icon):
  - `/` → Dashboard (home)
  - `/chat` → Chat (chat)
  - `/memory` → Memory (psychology)
  - `/self` → Self (person)
  - `/personas` → Entities (group)
  - `/traces` → Inspector (bug_report)
  - `/settings` → Settings (settings)
- **Styling**: Active link: `bg-primary/10`, `text-primary`, left border. Inactive: muted text, hover state. Icons via Material Symbols (`material-symbols-outlined`).

---

## 3. Dashboard page (`/`) [DV]

- **View**: `DashboardView` (stats + usage + actions). Uses `chatStore.userId` and `dashboardStore` (`fetchStats`, `stats`, `isLoading`, `error`).
- **Header**: “Dashboard” + `RefreshButton` to refetch stats.
- **Content** (when `stats` is loaded):
  - **Memory section**: Grid of stat cards — Memories (total engrams), Active, Entities — with icons (psychology, bolt, person).
  - **Usage (all time) section**: Table — total memory interactions, total tokens, input tokens, output tokens, estimated cost. Footnote: dedicated Usage page planned (per-operation breakdowns, trends, cost by type).
  - **Action buttons**: “Open Chat” (→ `/chat`), “Memory Explorer” (→ `/memory`), “Inspector” (→ `/traces`).
- **States**: Loading spinner; error message; “No stats yet” when no stats (prompt to use Chat).

---

## 4. Chat page (`/chat`) [CL]

- **Layout**: Column: scrollable `ChatMessages` above, fixed `ChatComposer` at bottom.
- **ChatMessages**:
  - On mount: calls `chatStore.loadMessages()` → `GET /messages?user_id=` → populates chat history from DB on first render. Non-fatal if load fails (starts with empty chat).
  - Renders list of `Message` components (user / assistant). Assistant messages can show optional `memory_context` (retrieved context from decode).
  - Empty state: icon + “Start a conversation…” + note about memory context under assistant replies.
  - **Progress**: Decode phase — “Thinking…” or current decode step (e.g. C1/C2/C3); encode phase — “Saving…” or current encode step. Scroll-to-bottom on new messages; optional “scroll to bottom” button when user has scrolled up.
  - Uses `chatStore`: `messages`, `isLoading`, `streamingMessageId`, `decodeStep`, `encodeStatus`, `encodeStep`, `error`, `retryMessage`, `loadMessages`.
- **ChatComposer**:
  - Textarea (auto-resize, max height), placeholder “Ask something…”. Send on Enter (no shift); attach button (UI only). Send button disabled when empty or loading; shows spinner when loading.
  - Calls `chatStore.sendMessage(content)` (SSE stream to `/chat`).

---

## 5. Memory page (`/memory`) [ME]

- **View**: `MemoryExplorer` — event graph data in three view modes + optional detail panel.
- **Data**: `memoryStore`: `nodes`, `edges`, `selectedEvent`, `fetchGraph(userId)`, `fetchEventDetail(userId, eventId)`, `clearSelection`. On mount, `fetchGraph(userId)`.
- **Header**: “Memory Explorer” + `RefreshButton` (clears selection and refetches graph) + `ViewToggle` (only when `nodes.length > 0`).
- **ViewToggle**: Three modes — **List**, **Grid**, **Graph** (ids: `list`, `grid`, `graph`). Renders `ListView`, `GridView`, or `GraphView` with `nodes`/`edges` and `onSelectEvent` → `fetchEventDetail`.
- **Main area**: Loading spinner; error message; `EmptyState` when no nodes; otherwise list/grid/graph + **EventDetailPanel** (slide-in from right).
- **EventDetailPanel** (when event selected or loading detail): Shows core intent, event kind (summary / episode / entity), timestamps, and related content; close clears selection.

---

## 6. Self page (`/self`) [SM]

- **View**: `SelfMemoryView` — self traits from `GET /memory/self/{user_id}`.
- **Header**: “Self Memory” + subtitle “What hippomem has learned about you”.
- **Content**: Traits grouped by category (Stable Attributes, Goals, Personality, Preferences, Constraints, Projects). Each trait: key, value, optional previous_value (struck through), evidence count, first/last observed dates; unconfirmed traits have an “unconfirmed” badge and reduced opacity.
- **States**: Loading spinner; error; empty state (“No self traits learned yet”, “Chat more to build your self profile”).

---

## 7. Entities page (`/personas`) [PV]

- **View**: `PersonaView` — entities from `GET /memory/entities/{user_id}`.
- **Header**: “Entities” + subtitle “People, places, and things hippomem has learned about”.
- **Content**: Entities grouped by type (People, Pets, Organizations, Places, Projects, Tools, Other). Each **EntityCard**: canonical name, optional summary, list of facts (first 3, then “+N more” expand), reinforcement count, first/last dates.
- **States**: Loading; error; empty state (“No entities learned yet”, “Mention people, places…”).

---

## 8. Inspector page (`/traces`) [TV]

- **View**: `TracesView` — interaction list + optional step detail panel.
- **Data**: `tracesStore`: `interactions`, `selectedInteraction`, `fetchTraces(userId)`, `fetchInteractionDetail(interactionId)`, `clearSelection`.
- **Header**: “Inspector” + `RefreshButton` (+ “back” when a row is selected).
- **Main area**: Table — Timestamp, Operation, Steps (call_count), In tokens, Out tokens, Cost, Latency. Row click → `fetchInteractionDetail(id)`.
- **StepDetailPanel** (slide-in right): Operation, timestamp, step count; token/latency/cost summary; turn_id (copyable); list of `StepBlock`s (per LLM call / step). Close clears selection.
- **Empty**: “No traces yet. Send a message in Chat to generate LLM calls.”

---

## 9. Settings page (`/settings`) [SV]

- **View**: `SettingsView` — load/save config; three sections: Connection, Features, Advanced.
- **Data**: `settingsStore`: `config`, `isLoading`, `isSaving`, `error`, `fetchConfig`, `saveConfig`, `isDirty`. Weights validation: retrieval_semantic + relevance + recency must sum to 1.0; warning banner if not.
- **Header**: “Settings” + **Save** button (disabled when not dirty or weights invalid; shows “Saving…” / “Saved ✓” feedback).
- **ConnectionSection**: API key (masked when saved), base URL, LLM model, chat model, system prompt; tooltips; optional “Fetch models” for OpenRouter; optional validation of key/URL before save.
- **FeaturesSection**: Toggles — Background Consolidation, Memory Clustering (disabled if Background Consolidation off), Entity Extraction, Self Memory; each with tooltip.
- **AdvancedSection**: Collapsible; sliders/number inputs for memory and retrieval params (e.g. max_active_events, continuation_threshold, retrieval weights, decay_rate_per_hour, consolidation_interval_hours). Custom count of non-default values; retrieval weights must sum to 1.0.

---

## 10. Shared UI patterns

- **Page header**: Most pages use a 12px-height header bar: title (left), optional `RefreshButton` and/or view/back controls (right), bottom border. Background `bg-pure-black/80 backdrop-blur-md`.
- **RefreshButton**: Refetches current page data; disabled when loading; shows spinner when `isLoading`.
- **Loading / error / empty**: Pages use a consistent pattern: full-area or centered spinner when loading; red error message when `error`; empty state with icon + short copy when no data.
- **Stores and userId**: `chatStore.userId` is the single source of truth for the current “user” (default `dev_user`). Dashboard, Memory, Self, Entities, and Traces all pass this `userId` into their API calls. Settings and Chat use it implicitly (Chat via `sendMessage` and `loadMessages`, which both use store `userId`).

---

## 11. API usage by page

| Page     | APIs used |
|----------|-----------|
| `/`      | `GET /health` (setup guard), `GET /stats?user_id=` |
| `/chat`  | `POST /chat` (SSE), `GET /messages?user_id=` (initial load) |
| `/memory`| `GET /memory/graph/{user_id}`, `GET /memory/events/{user_id}/{event_uuid}` |
| `/self`  | `GET /memory/self/{user_id}` |
| `/personas` | `GET /memory/entities/{user_id}` |
| `/traces`| `GET /traces?user_id=&limit=50`, `GET /traces/{interaction_id}` |
| `/settings` | `GET /config`, `PATCH /config`, optional `GET /config/models` |

---

## Key design notes

- **Single-user session**: No login; one `userId` per session. All memory/traces/stats are scoped to that id. Changing it would require a store/context change and is not exposed in the current UI.
- **Setup flow**: First-time users hitting `/` are redirected to `/settings` until an API key is saved and the server reports `setup_required: false`.
- **Memory Explorer views**: List and Grid show the same nodes with different layout; Graph uses nodes + edges for D3-style visualization. Selection is shared; detail panel shows full event from `/memory/events/...`.
- **Inspector vs Dashboard**: Inspector shows per-interaction traces (decode/encode/LLM steps); Dashboard shows aggregate stats and usage totals. Both use the same `user_id`.
- **Settings persistence**: Save writes full config via `PATCH /config` and persists to `hippomem_config.json` on the server. Hot/warm reload behavior is server-side (see server codeflow).
