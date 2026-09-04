# Task: interfaces

## Framing
You are the architect. Define the module interfaces for the chat feature: function signatures, data shapes, ownership boundaries between client and storage.

## Project charter (input context)

# Project Charter: Qaida Map-First UX Redesign

Status: draft | Owner: PM agent | Updated: 2026-08-10 | Mode: brownfield

## 1. Current state (summarized from current-state.md)

Qaida is a mood-based place discovery app for Kazakhstan (Almaty, Astana, Pavlodar).
Backend: FastAPI + PostgreSQL+pgvector, 244 passing tests. Mobile: Expo SDK 57 / React
Native 0.86.2 / expo-router, typecheck + check_ui.py green (no mobile test suite).

**What exists now:**
- Home screen (`index.tsx`): mood chips + text input + "Find Places" CTA → navigates to
  results. No live search. Voice via expo-speech-recognition (on-device, needs dev build).
- Results screen (`results.tsx`): cards/map toggle via SegmentedControl. MapView is a
  **placeholder** (ScrollView list of venue names). Stable props: `{ venues, center, lang,
  onMarkerPress }` (D5 abstraction — swap is one file).
- No bottom sheet / swipe-up panel anywhere in the codebase. No such dependency exists.
- Anonymous identity only: UUID v4 in expo-secure-store, hashed to session_key. No
  accounts, no personal data stored (ARCHITECTURE rule 5). D22 chose this for KZ data
  localization compliance.
- Rate limiting: token-bucket RateLimiter protects **AI provider quota** (shared bucket,
  llm_rpm=15, embedding_rpm=100). **No per-user / per-session_key API rate limiting**.
- Groups feature is functional (create, join, consensus polling). Consensus uses
  creator's single center_lat/lng — no geographic midpoint computation.
- Intent schema has `max_distance_m` (default 3000). LLM intent parse can already widen
  it. `_MAX_RESULTS = 3` hard-coded in recommend.py (the product identity: "reducing
  choice IS the product").
- i18n: ru/kk/en, 117 keys each. Partner badge structurally enforced in VenueCard (D29).
  AI disclosure text in Settings (Law 230-VIII). Location permission contextual (D7).

## 2. Desired change

Transform the home screen from "mood chips + CTA → results page" to a **map-first
discovery** experience:

1. **Login screen first** (new): optional login/register with "continue as guest" option.
   Guest users are rate-limited to prevent abuse.
2. **Map home screen**: main screen shows a map of interesting places nearby.
3. **Top search bar** with voice search option, overlaid on the map.
4. **Search results**: matching places shown on the map AND in a bottom panel. Panel shows
   top option first; swipe up reveals 3-4 results (more on request). Search radius adapts
   to the query intent (e.g. "camping in nature" → wider radius).
5. **Future seams** (design-only, no implementation): friends system, in-app chats,
   group-midpoint mode (find places close to ALL group members).

## 3. Impact surface (modules/files the change touches → drives roster)

### Backend (Python)
| File / area | Change |
|---|---|
| `app/routers/recommend.py` | `_MAX_RESULTS` may need parameterization (OD-C). max_distance_m widening already works via intent schema (OD-D confirm). |
| `app/ai/rate_limit.py` | New per-session_key limiter for guest abuse prevention (OD-E). New file or extend. |
| `app/routers/` (new) | Auth endpoints (login, register, token issue/refresh) if OD-A decides accounts. |
| `app/models.py` | New User table if OD-A decides accounts. Migration needed. |
| `app/schemas.py` | Auth request/response schemas if accounts. ResultCount or pagination schema if OD-C. |
| `app/config.py` | Guest rate limit settings, auth config (JWT secret, token TTL). |
| `app/main.py` | Auth middleware registration, CORS if needed. |
| `migrations/` | New migration for user table + any schema changes. |

### Mobile (TypeScript)
| File / area | Change |
|---|---|
| `app/_layout.tsx` | Add login screen as initial route. Route guard for auth state. |
| `app/index.tsx` | **Major rewrite**: home becomes map-first with search bar overlay. |
| `src/components/MapView.tsx` | Swap placeholder body with real map SDK (OD-B). Props interface unchanged. |
| `src/components/` (new) | BottomSheet / swipe-up panel component. SearchBar component (if extracted). LoginScreen. |
| `src/store/session.ts` | Extend for auth state (token, is_guest, user_id). |
| `src/api/client.ts` | New auth endpoints. Token attachment to requests. |
| `src/api/types.ts` | Auth types, paginated result types if OD-C. |
| `src/i18n/` | New keys for login, map, bottom sheet, guest prompts (3 languages). |
| `src/hooks/` (new) | `useAuth` hook, possibly `useMapResults` hook. |
| `package.json` | New deps: map SDK (OD-B), bottom-sheet lib (OD: needs ARCHITECTURE rule 8 flag). |

### Touches do-not-touch neighbors
- `VenueCard.tsx` (partner badge D29) — must remain structurally intact. Bottom sheet
  will render VenueCards; badge enforcement must survive.
- `app/routers/recommend.py` (never-throw guarantee rule 3) — any changes to result count
  must not break the error-suppression contract.
- `app/ai/intent.py` / `prompts.py` (LLM-only-parses-intent rule 1) — radius widening
  must stay in the intent schema, not leak venue data into prompts.

## 4. Do-not-touch list (explicit, binding)

| # | What | Why | Source |
|---|---|---|---|
| DN-1 | `VenueCard` partner badge (private PartnerBadge sub-component) | KZ advertising law — badge must be structurally impossible to omit | D29 / HANDOFF |
| DN-2 | AI disclosure text in Settings | Law 230-VIII — verbatim, do not reword | HANDOFF |
| DN-3 | Location permission flow (contextual, never at launch, district fallback) | D7 — never a dead-end | HANDOFF |
| DN-4 | `MapView` props interface `{ venues, center, lang, onMarkerPress }` | D5 — stable contract, swap body only | HANDOFF / current-state |
| DN-5 | 3-language completeness (ru default, kk second, en third) | D33 — all 117 keys must stay complete per language | HANDOFF |
| DN-6 | Never-throw recommend handler (rule 3) | All API errors degrade to cached/stale, never raw errors | ARCHITECTURE |
| DN-7 | Venues never enter LLM prompts (rule 1) | $50K/month cost risk | ARCHITECTURE |
| DN-8 | LLM never states venue facts (rule 2) | Template-based explanations only | ARCHITECTURE |
| DN-9 | No personal data stored without explicit OD-A resolution (rule 5) | KZ data localization law | ARCHITECTURE |
| DN-10 | No new dependencies without explicit flagging (rule 8) | Must be proposed as decisions, not silently added | ARCHITECTURE |
| DN-11 | City resolution from coordinates, never default (rule 6) | Silently serving wrong city is a correctness bug | ARCHITECTURE |

## 5. Success metrics and acceptance criteria

### Observable / testable
- **SM-1**: 244 backend tests remain green (no regressions). New tests for auth + rate
  limiting pass. Baseline must be re-verified before and after each phase.
- **SM-2**: `npm run typecheck` (strict) passes. `scripts/check_ui.py` passes (0.0% delta).
- **SM-3**: Login screen renders as initial screen. "Continue as guest" button works
  (creates/uses existing anonymous session_key). Logged-in users see no rate-limit UX.
- **SM-4**: Home screen shows a real map (not placeholder list). Map renders venue
  markers. Tapping a marker calls `onMarkerPress`.
- **SM-5**: Search bar is at the TOP of the map screen. Voice search button present and
  functional (same expo-speech-recognition hook, degrades to disabled in Expo Go).
- **SM-6**: On search, results appear on the map (markers) AND in a bottom panel. Panel
  shows top result collapsed; swipe up reveals 3-4 results.
- **SM-7**: Guest users are rate-limited (OD-E defines exact limits). After exceeding
  limit, guest gets a clear message (not an error — a "login to continue" prompt).
- **SM-8**: Search radius adapts to query: "camping in nature" query produces results with
  wider max_distance_m than "coffee nearby" (OD-D confirms mechanism).
- **SM-9**: All new user-facing strings have ru/kk/en translations (117+ keys, 3 langs).
- **SM-10**: Partner badge still renders in VenueCard inside bottom sheet (DN-1 intact).
- **SM-11**: AI disclosure text in Settings is verbatim unchanged (DN-2 intact).

### "Existing behavior unchanged" criteria
- **UB-1**: Existing recommend endpoint contract unchanged for backward compat (same
  request/response shape; result count change is OD-C, not assumed).
- **UB-2**: Groups feature (create/join/consensus) unchanged.
- **UB-3**: Venue detail screen, feedback, report flows unchanged.
- **UB-4**: Config endpoint and force-update gate (D27) unchanged.
- **UB-5**: `tw()` styling system used for all new UI (no NativeWind, no tailwind-rn).

## 6. Compatibility constraints

- **ARCHITECTURE.md rules 1-9**: all non-negotiable. Rule 5 (no personal data) and rule 8
  (no new deps without flagging) are especially relevant — see OD-A and OD-B.
- **KZ data localization**: Law on Personal Data — any stored personal data must reside
  on KZ-located servers. Current anonymous-only design avoids this entirely. Adding
  accounts (OD-A) triggers this constraint.
- **expo-router**: file-based routing in `app/`. Login screen = new file in `app/`.
- **expo-secure-store**: already used for session UUID; can store auth tokens too.
- **Dev build requirement**: voice search already needs a dev build (native module). A
  native map SDK (OD-B) also needs a dev build. Both are compatible.
- **Postgres-only caching** (no Redis at this scale): per-session rate limiting must use
  Postgres or in-memory, not Redis.
- **Python 3.12+, FastAPI 0.115+, Pydantic 2.7+**: auth implementation must use these.
- **TypeScript strict mode**: all mobile code fully typed.
- **D27 force-update gate**: must not break. New screens must respect min_supported_version.

## 7. Tech stack and conventions

- **Backend**: Python 3.12+, FastAPI 0.115+, Pydantic v2, SQLAlchemy 2.0, async psycopg.
  Snake_case, full type hints, `from __future__ import annotations`. Tests: pytest,
  asyncio auto mode, no network calls, LLM mocked.
- **Mobile**: Expo SDK 57, React Native 0.86.2, React 19.2.3, expo-router 57, TypeScript
  strict, Zustand 4.5, TanStack React Query 5.62, i18next 24. CamelCase. Screens in
  `app/`, components/hooks/lib in `src/`.
- **Styling**: Custom `tw()` Tailwind-class mapper (NOT NativeWind, NOT tailwind-rn).
  All UI through shared components. Ionicons only. Mood identity colors, WCAG AA.
- **i18n**: `t()` via react-i18next. ru/kk/en, all three must stay complete.
- **Error handling**: Backend recommend never raises (rule 3). Mobile `recommend()`
  returns `{ok, error}` union, never throws. All screens show cached/stale, never raw errors.
- **DB**: PostgreSQL + PostGIS + pgvector + pgcrypto. Migrations are numbered SQL files.
- **Design system**: AppHeader, Card, EmptyState, Icon, IconButton, InputWell, MapView,
  MoodChip, PrimaryButton, ResultsView, SecondaryButton, SegmentedControl, VenueCard.
  New components must follow these patterns.

## 8. Risks (regression risk + mitigation)

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Breaking 244-test baseline with recommend.py changes | High | Re-run full suite before/after each phase. Never modify the never-throw contract. |
| R2 | Map SDK adds heavy native dependency, breaks EAS build | Medium | OD-B evaluates MapLibre Native vs 2GIS MapKit vs Mapbox. Test with `npx expo prebuild` early. |
| R3 | Auth introduces personal data storage → KZ law violation | High | OD-A must be resolved before any auth code. Guest-only path is zero-risk fallback. |
| R4 | Bottom sheet lib is a new dependency (rule 8) | Medium | Flag explicitly. Consider building with Reanimated/GestureHandler (already Expo deps?) before adding a new package. |
| R5 | Result count change (3→N) breaks partner slot logic (rule 4: max 1 per 3) | High | OD-C must decide: backend cap change or client-side pagination. Partner logic tested in test_ranking.py. |
| R6 | Map-first home screen breaks location permission flow (D7) | Medium | Permission still requested contextually after first search action, not at launch. |
| R7 | Guest rate limiting adds statefulness, may break shared AI quota | Low | Guest limiter is per-session_key, separate from the AI provider limiter. |
| R8 | New i18n keys incomplete in one language → D33 violation | Medium | CI must check key completeness. Add keys to all 3 languages in the same commit. |
| R9 | Mobile has no test suite → regressions undetected | Medium | typecheck + check_ui.py as gates. Manual QA per phase. Consider adding snapshot tests. |

## 9. Team (role → responsibility, justified by impact surface)

See `out/pm/roster-proposal.md` for the full minimal roster with justifications.

**Summary**: Architect (map SDK + auth data model decisions), Designer (map-first UX +
bottom sheet + login screen), Frontend (mobile implementation), Backend (auth endpoints +
rate limits + result count/radius), QA (regression verification). Devops considered but
likely not needed (no new infra for MVP — see roster doc).

## Open Decisions (require user input before implementation)

### OD-A: Auth model vs ARCHITECTURE rule 5 ("No personal data is stored")
**STATUS: DEFERRED (2026-08-10, GATE 1)**

User decision: Ship Phase 1-2 first, revisit auth later. Phase 3 is off the immediate roadmap.

When ready to implement:
- **What auth method**: email+password? phone OTP? OAuth (Google/Apple)?
- **What data is stored**: user identifier only? preferences? history?
- **Where data is stored**: KZ data localization (Law on Personal Data) requires KZ-located
  servers for personal data. Current anonymous-only design avoids this entirely.
- **Guest mode**: keeps existing anonymous session_key (zero new data, zero legal risk).
- **Impact**: Blocks Phase 3 entirely. Phase 1-2 do not depend on this.

### OD-B: Real map SDK choice
**STATUS: USER PREFERS OSM (2026-08-10, GATE 1) — architect to evaluate**

User wants OpenStreetMap. Architect to evaluate:
- **Option A: OpenStreetMap + MapLibre Native** (user preference). Open-source, offline tiles possible, global coverage. Question: KZ POI/tile quality sufficient?
- **Option B: 2GIS MapKit** (KZ provider). Better local data, may have better venue/POI coverage in Kazakhstan. Question: SDK maturity, licensing, offline support.
- **Option C: Mapbox** (feature-rich, usage limits). Probably overkill for MVP.

**Constraint**: Must remain offline-degradable per rule 3 spirit (app always returns
results even if map tiles fail to load — the map is a view, not a dependency for results).
**Architecture**: MapView.tsx swap is one file. Props interface is stable (D5).
**Impact**: Blocks Phase 2 map implementation. Phase 1 (bottom sheet) can proceed without it.
**New dependency**: Must be flagged per rule 8.

### OD-C: Result count — reconcile product identity with vision
- **Current**: `_MAX_RESULTS = 3` hard-coded in recommend.py. "Reducing choice IS the
  product."
- **Vision**: swipeable list of 3-4+ results, "unless the user wants more."
- **Options**: (a) Backend returns more (change _MAX_RESULTS to configurable via
  request param, default 3, allow up to N). (b) Backend stays at 3, client paginates by
  requesting more with offset. (c) Backend returns 3, client shows 3-4 from a richer
  candidate set (already retrieves 50, scores, slices to 3).
- **Risk**: Partner slot rule (max 1 per 3) must scale correctly for N results.
- **Impact**: Blocks Phase 2 bottom panel content.

### OD-D: Adaptive search radius
- **Current**: Intent schema has `max_distance_m` (default 3000). LLM intent parse can
  already widen it from text (prompts.py instructs LLM: "3000 unless user explicitly
  states a distance").
- **Question**: Does the existing LLM prompt already handle "camping for the weekend in
  nature" → wider radius? Or does the prompt need product tuning to recognize
  excursion-type queries and widen automatically?
- **Action**: Architect to review `app/ai/prompts.py` system prompt and test with
  camping-type queries against the mock intent parser. If it already works, no change
  needed. If not, tune the prompt (no new code path, just better instructions).
- **Impact**: Low effort, but must be confirmed before Phase 2 acceptance.

### OD-E: Guest rate limiting strategy
- **Current**: No per-user/per-session rate limiting. AI provider limiter is a shared
  token bucket (15 RPM, 100 embedding RPM, $40/month budget).
- **Needed**: Per-session_key API limits for guests (e.g. N recommends/day for guests
  vs unlimited for logged-in).
- **Options**: (a) In-memory dict (simplest, lost on restart). (b) Postgres table
  (durable, adds a write per request). (c) Extend existing RateLimiter with per-key
  buckets.
- **Question**: What are the exact limits? (e.g. 10 recommends/day for guests?)
- **Impact**: Blocks Phase 3 guest rate limiting task.

### OD-F: Bottom sheet dependency (rule 8 flag)
- **Question**: Use `@gorhom/bottom-sheet` (industry standard, Reanimated-based) or build
  a custom sheet with Reanimated + GestureHandler?
- **Check**: Are react-native-reanimated and react-native-gesture-handler already in
  package.json? If yes, a custom sheet adds zero new deps. If no, `@gorhom/bottom-sheet`
  brings them both.
- **Impact**: Blocks Phase 1 bottom sheet component.

