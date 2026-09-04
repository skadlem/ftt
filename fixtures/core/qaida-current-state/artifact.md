# Qaida — Current-State Map

Brownfield audit. Maps what EXISTS (not what should exist). Drives the charter and roster.

---

## Module Map

### Mobile (`mobile/`) — Expo SDK 57 / React Native 0.86.2 / expo-router

| Area | Files | Responsibility |
|------|-------|---------------|
| **Screens** (`app/`) | `_layout.tsx`, `index.tsx`, `results.tsx`, `venue/[id].tsx`, `group/[token].tsx`, `settings.tsx` | 5 screens + root layout. Stack navigator (expo-router). Header hidden globally; each screen renders its own `AppHeader`. |
| **Components** (`src/components/`) | AppHeader, Card, EmptyState, Icon, IconButton, InputWell, MapView, MoodChip, MoodChips, PrimaryButton, ResultsView, SecondaryButton, SegmentedControl, StaleBanner, UpdateScreen, VenueCard, moodColors | Shared design-system library. All UI goes through these. VenueCard renders the legally-required partner badge (private sub-component, structurally impossible to omit). |
| **API client** (`src/api/`) | `client.ts`, `types.ts` | Typed fetch wrapper. 8s timeout, 1 retry on network errors. `recommend()` never throws (returns `{ok, data}` or `{ok:false, error}`). All endpoints typed. |
| **State** (`src/store/`) | `session.ts`, `prefs.ts`, `cache.ts` | Zustand stores. `session.ts` = anonymous UUID in SecureStore. `prefs.ts` = language, hidePartners, recentlyShown. `cache.ts` = last results cache (AsyncStorage). |
| **Hooks** (`src/hooks/`) | `useLocation.ts` | expo-location. Contextual permission (never on launch). City auto-detected from coords. District fallback when denied. 3 cities hardcoded. |
| **Speech** (`src/speech.ts`) | `useSpeech` hook | expo-speech-recognition v56.0.1. On-device, $0. Dynamic import, degrades to disabled button. Needs dev build (native module). |
| **i18n** (`src/i18n/`) | `index.ts`, `languages.ts` | i18next + react-i18next. ru/kk/en, 117 keys each. ru default, kk second, en third. |
| **Styling** (`src/lib/`) | `tw.ts`, `format.ts`, `routeParams.ts`, `version.ts` | `tw()` = Tailwind-like class mapper (NOT NativeWind; custom implementation). No tailwind config at runtime. Design tokens: palette, spacing, sizes, text. |

### Backend (`backend/`) — FastAPI / Python 3.12+ / PostgreSQL+pgvector

| Area | Files | Responsibility |
|------|-------|---------------|
| **Routers** (`app/routers/`) | `recommend.py`, `venues.py`, `feedback.py`, `config_router.py`, `groups.py` | 5 routers. `recommend.py` = main pipeline (POST /v1/recommend). `groups.py` = group consensus. |
| **AI layer** (`app/ai/`) | `intent.py`, `providers.py`, `embeddings.py`, `prompts.py`, `normalize.py`, `rules.py`, `chips.py`, `weather.py`, `budget.py`, `rate_limit.py` | Intent routing: chip → cache → rule → LLM (2s timeout, degrade gracefully). Providers: OpenAI-compatible (Gemini). Embeddings: 768-dim pgvector. Budget tracking ($40/month cap). |
| **Ranking** (`app/ranking/`) | `scorer.py`, `explain.py`, `partner.py`, `retrieve.py`, `relax.py`, `hours.py` | Deterministic weighted scoring. Template-based explanations (ru/kk/en). Partner slot rules (max 1 per 3). Open-hours logic. |
| **Models** (`app/models.py`) | Venue, City, QueryEvent, ResultEvent, FeedbackEvent, GapEvent, IntentCache, EmbeddingCache, WeatherCache, Group, GroupMember | SQLAlchemy ORM. Event tables partitioned by month. |
| **Schemas** (`app/schemas.py`) | Intent, VenuePublic, ResultCard, RecommendRequest/Response, FeedbackRequest, ReportRequest, ConfigResponse, GroupCreateRequest, GroupJoinRequest, GroupResponse | Pydantic v2 with vocabulary validators. |
| **Logging** (`app/logging_/events.py`) | make_session_key, normalize_session_key, log_query_event, log_result_events, log_feedback_event, log_gap_event, encode_geohash | Anonymous event logging. geohash-5 only (no raw coords persisted). |
| **Config** (`app/config.py`) | Settings (pydantic-settings), closed vocabularies | All env vars declared here. Weights from config, never hardcoded. |
| **DB** (`app/db.py`) | SQLAlchemy engine, AsyncDbSession dependency | Async PostgreSQL. |

---

## Tech Stack + Versions

- **Mobile**: Expo SDK 57.0.11, React Native 0.86.2, React 19.2.3, expo-router 57, TypeScript ~6.0.3 (strict), Zustand 4.5, TanStack React Query 5.62, i18next 24, expo-speech-recognition 56.0.1, expo-location 57, expo-secure-store 57
- **Backend**: Python 3.12+, FastAPI 0.115+, Pydantic 2.7+, SQLAlchemy 2.0.30+, pgvector, psycopg 3.2+, GeoAlchemy2, httpx, pygeohash
- **DB**: PostgreSQL + PostGIS + pgvector + pgcrypto
- **Styling**: Custom `tw()` Tailwind-class mapper (NOT NativeWind, NOT tailwind-rn)

---

## Conventions

- **Naming**: Backend snake_case Python (full type hints). Mobile camelCase TS (strict mode). Screens in `app/` (expo-router file-based). Components/hooks/lib in `src/`.
- **Error handling**: Backend recommend handler NEVER raises (rule 3). Mobile `recommend()` returns `{ok, error}` union, never throws. All screens show cached/stale data, never raw errors.
- **Test layout**: `backend/tests/test_*.py`, pytest-asyncio auto mode. No mobile tests (typecheck + check_ui.py only).
- **i18n**: All user-facing strings via `t()` (react-i18next). 3 languages must stay complete.
- **Design system**: All UI through shared components. Ionicons only (no text-glyph icons). Mood identity colors, WCAG AA verified.
- **Partner badge**: Structurally enforced inside VenueCard (private PartnerBadge, not exported). KZ advertising law.
- **AI rule**: Venues NEVER enter LLM prompts. LLM only parses text → JSON intent. Explanations are template-based, traceable to DB columns.

---

## Test Suite State

- **244 test functions** across **21 test files** (backend only)
- **0 mobile tests** (typecheck + `scripts/check_ui.py` static checks only)
- Largest: `test_ranking.py` (38), `test_api.py` (30), `test_intent_routing.py` (29), `test_seed_data.py` (24)
- Coverage: ranking, API endpoints, intent routing, rate limiting, budget, weather, partitions, seed data, CI workflow, doc drift, recently-shown wiring, golden set, mock embeddings
- Mock eval floor: 94.5% (frozen clock, hermetic mock embeddings)
- No end-to-end / integration tests for groups feature specifically

---

## Top Integration Points

1. **POST /v1/recommend** — the main discovery endpoint. Mobile → backend. Chip+text+lat/lng+session_key → 3 ranked venues with reasons.
2. **GET /v1/config** — remote config (feature flags, min version, scoring weights). Mobile polls at launch for force-update gate (D27).
3. **Groups deep link** — `https://qaida.app/g/{TOKEN}` → `app/group/[token].tsx`. Join with mood intent → backend consensus → poll every 10s.
4. **Session key** — anonymous UUID (expo-secure-store) sent on every recommend/groups request. Backend hashes with salt → `session_key`.
5. **Venue detail** — `app/venue/[id].tsx` → `GET /v1/venues/{id}`. Feedback/report via POST.

---

## Areas Relevant to New UX Vision

### a. Login / Auth

**Exists**: Anonymous identity only. `session.ts` generates a UUID v4 on first launch, persists in `expo-secure-store`. Backend `make_session_key()` hashes UUID + salt. No login, no personal data, no accounts. D22 (TECH_DECISIONS) explicitly chose this for KZ data localization compliance.

**Missing**: No user accounts, no profile, no persistent preferences across devices, no social identity. Groups are identified by session_key only (a device can't transfer its group membership).

### b. Map

**Exists**: `MapView.tsx` is a **placeholder** — renders a `ScrollView` list of venue names with a colored dot, inside a styled container. The component interface (`{ venues, center, lang, onMarkerPress }`) is the stable contract (D5). Results screen has a cards/map `SegmentedControl` toggle.

**Needed for real map**: Swap the placeholder body with a native map SDK. The TODO in the file says "MapLibre Native module (or swap to 2GIS MapKit later)." Props interface is already stable — swapping is a one-file change. No map SDK dependency exists in `package.json` yet.

### c. Search Bar + Voice

**Exists**: Home screen (`index.tsx`) has a `TextInput` + voice button (Pressable with a circle/square shape indicator). `useSpeech()` hook wraps expo-speech-recognition. Voice is on-device ($0), only transcribed text goes to backend. Needs a dev build (native module). In Expo Go, voice shows as unsupported.

The search flow: user picks mood chips (optional) + types free text (optional) + presses "Find Places" → `router.push('/results', { chips, text, lat, lng, lang })`. Results screen calls `recommend()`. No live search / autocomplete. The CTA requires at least one signal (chip or text).

### d. Bottom Sheet / Swipe-Up Panel

**Does NOT exist.** No bottom sheet, no swipe-up panel, no modal pattern anywhere in the codebase. All screens use `ScrollView` or static `View` layouts. There is no `react-native-bottom-sheet`, `@gorhom/bottom-sheet`, or similar dependency. The closest pattern is the `SegmentedControl` toggle between cards and map on the results screen. The location permission prompt is an inline card, not a sheet.

### e. Groups (Consensus)

**Exists and is functional.** Full implementation:

- **Backend** (`groups.py`): POST /v1/groups (create), POST /v1/groups/{token}/join, GET /v1/groups/{token}. Token = `secrets.token_urlsafe(16)`, 24h TTL. Consensus algorithm: intersect hard constraints (min budget, intersection of categories → fallback to union, min max_distance_m), union soft preferences (moods, good_for, atmosphere). Runs the same recommend pipeline with `commit=False, log_events=False`.
- **Consensus caching**: Group row stores `consensus_json` + `consensus_member_count`. GET is cheap (serves cache) unless membership changed.
- **Mobile** (`group/[token].tsx`): Deep-link entry. Member picks a mood chip → joins with intent. Polls every 10s after joining. Shows consensus venue (first result) in a Card. Share button (native Share API).
- **DB models**: `Group` (token, city_id, creator_key, center_lat/lng, status, resolved_venue_id, consensus cache fields). `GroupMember` (group_token, session_key, intent_json, joined_at).

**Relevant to "show where to go for a group so it's close to all"**: The consensus currently uses a SINGLE `center_lat/lng` (the creator's location). It does NOT compute a geographic midpoint of all members. The `max_distance_m` is the min of all members' values. To support "close to all," the backend would need to: (1) collect each member's location, (2) compute a centroid or minimax point, (3) use that as the search center instead of the creator's coords. The infrastructure exists (GroupMember.intent_json could carry lat/lng; the recommend pipeline already accepts lat/lng), but the consensus algorithm doesn't do geographic optimization yet.

### f. Rate Limiting

**Exists**: `backend/app/ai/rate_limit.py` — token-bucket `RateLimiter` class. Async-safe (single asyncio lock). Configurable RPM + burst capacity. `acquire(timeout)` returns False on timeout so callers degrade instead of queueing.

**Configured limits** (in `config.py` Settings):
- `llm_rpm`: **15.0** (Gemini flash-lite free-tier quota)
- `embedding_rpm`: **100.0** (Gemini embedding quota)
- `ai_monthly_budget_usd`: **$40.0** (monthly spend cap, tracked by `budget.py`)

**No per-user rate limiting.** The rate limiter protects the AI provider quota (shared bucket across all users), not individual user abuse. There is no API-level rate limiting middleware (no slowapi, no per-session_key limits). A single anonymous session_key can hammer the API freely.
