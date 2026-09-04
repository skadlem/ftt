# Curation API — interface contract (backend ↔ frontend)

Owner: architect | Date: 2026-08-08 | Binding for backend + frontend this wave
Depends on: ADR-002 (fixtures are truth), ADR-003 (shared FastAPI app, bearer token)

Precise enough that backend and frontend build in parallel without talking. If
something here is wrong, change **this file first**, then the code.

## 0. Ground rules

- Router: `backend/app/routers/curation.py`, prefix `/v1/curation`, registered in
  `main.py` **only when `CURATION_TOKEN` is set** (ADR-003).
- Auth: `Authorization: Bearer <CURATION_TOKEN>` on **every** endpoint. Missing or
  wrong → `401 {"detail": "unauthorized"}`.
- Storage: `backend/seed/osm/venues_<slug>.json` only. **No DB session, no
  `psycopg`, no ORM import in this router.**
- Pydantic models at the boundary (charter §7). Everything typed, snake_case.
- Validation errors are `422` with the full violation list — fail loudly, never
  partially apply.

## 1. Endpoints

### `GET /v1/curation/cities`
Bootstrap for the UI's city picker and progress display.
```json
{"cities": [{"slug": "pavlodar", "name_ru": "Павлодар",
             "total": 195, "curated": 12, "remaining": 183}]}
```
`curated` = records with `status == "active"`.

### `GET /v1/curation/candidates`
The review queue. Query params, all optional:

| Param | Type | Default | Meaning |
|---|---|---|---|
| `city` | str | — | city slug; omit = all cities |
| `status` | `unverified\|active\|closed` | `unverified` | filter |
| `category` | str | — | one of CATEGORIES |
| `q` | str | — | case-insensitive substring on `name_ru`/`name_en`/`address` |
| `has_draft` | bool | — | only records carrying an AI draft |
| `limit` | int 1..100 | 25 | page size |
| `offset` | int ≥0 | 0 | page offset |

```json
{"total": 183, "limit": 25, "offset": 0,
 "items": [{"city": "pavlodar", "name_ru": "Кофейня", "name_en": "Kofeynya",
            "category": "cafe", "address": "Павлодар", "lat": 52.28, "lng": 76.95,
            "status": "unverified", "has_draft": true, "completeness": 0.35}]}
```
`completeness` ∈ [0,1]: fraction of the 8 curated fields in §2 that are non-placeholder.
It drives the UI progress ring. Placeholders per current-state.md §7.1:
`atmosphere`/`good_for` empty, `noise_level == 3`, `price_per_person == 0`,
`group_size_max == 4`, `opening_hours` all-null.

### `GET /v1/curation/candidates/{city}/{name_ru}`
Identity is `(city, name_ru)` — the same key `load_seed.py` upserts on. `name_ru`
is URL-encoded. Returns the **full raw fixture record** plus:
```json
{"venue": { ...every fixture field... },
 "draft": {"atmosphere": ["cozy"], "noise_level": 2, "_model": "gemini-3.5-flash-lite",
           "_drafted_at": "2026-08-08T10:00:00Z"} | null}
```
404 if absent. The `draft` block is read from `seed/drafts/<slug>.draft.json`
(ADR-001) and is **advisory only** — the UI shows it as a suggestion the human
accepts or rejects; it is never pre-applied.

### `PATCH /v1/curation/candidates/{city}/{name_ru}`
The single edit endpoint. Body = a **partial** `VenueEditPayload` (§2): only the
keys present are changed. Semantics:
- Validate the merged record with `load_seed.validate_venue()` **before** writing.
- On success write the file atomically (tmp + `os.replace`), return the full
  updated record: `200 {"venue": {...}, "warnings": [...]}`.
- On failure: `422 {"detail": "validation failed", "errors": ["<load_seed message>", ...]}`
  and **nothing is written**.
- `warnings` is non-blocking advice, e.g. a `name_ru` rename (ADR-002 identity
  edge): `"renaming name_ru changes this venue's identity; the previously loaded row will be orphaned"`.

### `POST /v1/curation/candidates/{city}/{name_ru}/verify`
The status flip, as its own endpoint so the UI's primary action is unambiguous.
```json
// request
{"confirm": true}
// response 200
{"venue": {...}, "warnings": []}
```
Sets `status="active"`, `verified_by="founder"`, `verified_at=<UTC ISO8601>`.
- **Refuses with 422 if the record is not curation-complete**: `atmosphere` and
  `good_for` must both be non-empty, and `noise_level`, `price_per_person`,
  `group_size_max`, `seating` must all be set. Rationale: charter §5 N4 requires
  non-empty vibe fields on live venues, and `retrieve.py:123` means `active`
  is what users see. This gate is the point of the whole pipeline.
- Idempotent: verifying an already-active venue is a 200 no-op.
- `POST .../unverify` reverses it (`status="unverified"`), same shape. Mistakes in
  the field must be undoable one-handed.

### `GET /v1/curation/nearby`
Field mode: "what am I standing in front of".

| Param | Type | Required | Notes |
|---|---|---|---|
| `lat`, `lng` | float | yes | the phone's GPS |
| `radius_m` | int 50..5000 | no, default 500 | |
| `status` | str | no, default `unverified` | |
| `limit` | int 1..50 | no, default 20 | |

Returns the `candidates` item shape **plus `distance_m: int`**, sorted ascending.
Implementation: haversine over the in-memory fixture list. City is inferred from
the nearest city center, matching the app's own rule (ARCHITECTURE.md rule 6 —
never a default). If no city center is within 150 km: `422 {"detail": "no city within 150 km"}`.

### `POST /v1/curation/draft/{city}/{name_ru}`  (gated on ADR-001)
Returns an existing draft, or generates one **only if the server is explicitly
configured for drafting**. Same response shape as the `draft` block above.
`503 {"detail": "drafting disabled"}` when not configured.
**Binding:** the response is advisory; the server never applies it. Only a
subsequent `PATCH` from the human writes anything.

## 2. `VenueEditPayload` — every curated field

All fields optional in a `PATCH`. Vocabularies are imported from
`app.config` — **never re-listed in the router**, so a vocab delta is one edit
(see vocab-delta-plan.md).

| Field | Type | Constraint | Validator source |
|---|---|---|---|
| `name_ru` | str | non-empty; unique within city; **identity field, warns** | `_required_text`, `load_seed.py:161` |
| `name_kk`, `name_en` | str | non-empty | `_required_text` |
| `address` | str | non-empty | `_required_text` |
| `district` | str | non-empty | `_required_text` |
| `category` | str | ∈ `CATEGORIES` (10) | `load_seed.py:166` |
| `subcategories` | list[str] | free text, no closed vocab | — |
| `atmosphere` | list[str] | every item ∈ `ATMOSPHERE` | `load_seed.py:173` |
| `good_for` | list[str] | every item ∈ `GOOD_FOR` | `load_seed.py:169` |
| `features` | list[str] | every item ∈ `FEATURES` (43) | `load_seed.py:177` |
| `seating` | str | ∈ `SEATING` = indoor/outdoor/both | `load_seed.py:182` |
| `noise_level` | int | 1..5 inclusive, not bool | `load_seed.py:186` |
| `price_per_person` | int | ≥ 0, KZT (never "$$") | `load_seed.py:190` |
| `group_size_max` | int | ≥ 1 | (UI-side; loader has no check) |
| `laptop_friendly` | bool | — | — |
| `opening_hours` | object | **all 7 keys** mon..sun; each `null` or `["HH:MM","HH:MM"]` | `validate_opening_hours`, `load_seed.py:141` |
| `rating` | float\|null | null or 3.5..5.0 | `load_seed.py:206` |
| `phone`, `instagram` | str\|null | — | — |
| `lat`, `lng` | float | inside the city bbox | `load_seed.py:198` |
| `status` | str | ∈ `STATUS_VALUES`; **only via verify/unverify, rejected in PATCH** | `load_seed.py:209` |
| `verified_by`/`verified_at` | — | **server-set only, rejected in PATCH** | `load_seed.py:211` |
| `partner_tier`/`partner_until` | — | **rejected always, 422** (charter §4 rule 4) | — |

**`features` absence semantics (charter §4):** an empty/absent `features` means
*unverified*, never "no". The UI must offer present / not-checked, and must not
render a third "confirmed absent" state — there is no such value.

## 3. Validation rules reused, not reimplemented

The router imports from `seed/load_seed.py`:
`validate_venue`, `validate_opening_hours`, `validate_time`, and the bbox source
used by `--fixtures`. Charter §4: "New tooling must not fork these."

Because `validate_venue` takes `(venue, index, seen_names, city_slug, bbox)`, the
router calls it with the city's other names as `seen_names` minus the record being
edited, so a venue does not collide with itself. **This is the one integration
subtlety; get it wrong and every save fails as a duplicate.**

The router adds exactly two checks the loader has no opinion on:
`group_size_max >= 1`, and the curation-complete gate on `verify`.

## 4. Errors

| Code | When | Body |
|---|---|---|
| 401 | bad/missing token | `{"detail": "unauthorized"}` |
| 404 | unknown city or `name_ru` | `{"detail": "not found"}` |
| 409 | write lock contention (rare, n=2) | `{"detail": "busy, retry"}` |
| 422 | validation / forbidden field / incomplete verify | `{"detail": "...", "errors": [...]}` |
| 429 | curation rate limit (~60 writes/min) | `{"detail": "slow down"}` |
| 503 | drafting not configured | `{"detail": "drafting disabled"}` |

Frontend contract: `errors[]` strings are **human-readable and safe to show
directly** to a non-technical curator. Backend must keep them so.

## 5. Frontend assumptions it may rely on

- Every write returns the **full** updated record, so the UI never merges state.
- All endpoints are idempotent or safely retryable; a flaky mobile connection can
  retry a `PATCH` or `verify` without side effects.
- No pagination cursors — `limit`/`offset` over a stable file-backed list.
- No websockets, no realtime, no optimistic-concurrency tokens. At n=2 users,
  last-write-wins on a per-venue `PATCH` is the accepted behaviour.
