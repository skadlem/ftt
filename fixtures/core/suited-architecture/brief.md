# Task: architecture

## Framing
You are the planner. Design the architecture for the site-report wedge: components, data flow, failure handling, the smallest buildable version.

## Project charter (input context)

# Project Charter: suited (change to an existing project)

Status: amended (Gate 2) | Owner: PM agent | Updated: 2026-08-26 | Mode: brownfield

## 0. Forcing questions (answered BEFORE drafting)

1. **Demand reality**: User-selected wedge, externally reviewed design (spec v3),
   all load-bearing data claims verified live on 2026-08-26 (FEHD 17,223
   licences; ALS probes incl. failure-mode evidence; RR≈cafe disproven).
   Source: spec v3 "What Changed From v2".
2. **Status quo**: Today there is only the FEHD collector (running, cron
   bce60644afc3) accumulating snapshots. Nothing scores an address; commercial
   search answers "available & affordable", never "will this location make
   money?" — the gap spec v3 opens with.
3. **Desperate specificity**: someone with 2–3 candidate sites from an agent
   who wants them compared (spec v3 Product Inversion, "first user sharpened").
4. **Narrowest wedge**: HK / cafe vertical / primary flow = Site Report for any
   pasted address; ranked shortlist over listings demoted to secondary
   discovery. Everything else (network routing, Huff, churn fitting, census,
   traffic) queued in spec v3 Out of Scope.
5. **Alternatives considered**: (a) portal-scrape-first marketplace (v2 shape)
   — rejected by Product Inversion: FEHD+ALS cover every address day one
   regardless of scraper health; (b) OSM-only competitor data — rejected: 1,136
   `amenity=cafe` vs 17,223 FEHD licences (~4× coverage); (c) no-code/manual
   reports — rejected: determinism + published methodology require code.
6. **Premises challenged**: verified by discovery (current-state.md): FEHD
   register full-census claim, ALS probe behavior incl. wrong-but-confident
   50–64 scores, RR≠cafe token counts. Still believed (not yet verifiable):
   single snapshot ⇒ churn value unproven until history accumulates; ALS rate
   limits undocumented.

## 1. Current state

Summarized from `.pmos/out/planner/current-state.md`. Running: stdlib-only FEHD
collector (`suited/ingest/fehd.py`, fetch/rebuild/status CLI, archive-as-truth,
rebuild determinism tested), daily cron bce60644afc3, fehd.sqlite with 17,223
licences, 6 green tests. Everything else in spec v3 is unbuilt. Stack: Python
3.14.4; app layer will be FastAPI + HTMX + SQLite (no JS framework/build step).

## 2. Desired change (next build phase per spec v3)

- R-001: `ingest/geocode.py` — address normalization → ALS lookup gated at
  Score ≥75 → Nominatim fallback capped at street precision; ≤1 req/s;
  permanent cache storing lat/lon, precision (building|street|failed), source,
  score; unresolved addresses stay visibly unscoreable.
- R-002: `ingest/classify.py` — cafe vs other-food classifier over FEHD
  licences (name tokens + licence type; RR not cafe; chain brand list) on a
  STAGED gate measured on a 100-record hand-labelled sample: below precision
  ≥0.75 / recall ≥0.60 the output may not be consumed at all; between the soft
  gate and precision ≥0.85 / recall ≥0.70 it may feed scoring only with a
  `weak_classifier` flag on every consumer and no user-facing publication; at or
  above the hard gate the flag clears. Cross-checked against the OSM
  `amenity=cafe` extract as a silver set (precision on the covered subset only —
  its recall is uninformative at 1,136 features against a 17k register). Results
  and gate status published on /methodology. (Amended at Gate 2, A5.)
- R-003: `ingest/context.py` — OSM Overpass pull tiled by district bbox,
  non-food POIs (offices w/ building:levels, MTR entrances/exits, bus stops,
  schools, residential, malls) + roads; retry ×3/tile; raw packs cached on
  disk, last-good pack retained on refresh failure.
- R-004: `ingest/listings.py` + `ingest/sources/base.py` — ListingSource
  protocol, dedup key (normalized address + floor/unit + ±5% area + ±5% rent,
  every collapse logged for audit), CSV/demo-seed fixtures implemented FIRST so
  scoring work is unblocked from scraper health. (Amended at Gate 2, A7: floor/
  unit added to the key; tolerance deliberately kept at ±5%.)
- R-005: portal sources `ingest/sources/hse28.py`, `squarefoot.py` — polite
  scrapers tested against saved HTML only, skipped gracefully when failing
  while other sources have data, visible refresh stamps.
- R-006: `scoring/` — pure deterministic engine; seven weighted factors
  (25/20/15/10/15/10/5); fixed absolute anchors frozen into versioned
  `profiles/cafe.py` via `cli calibrate`, calibrated in TWO independently
  versioned halves — non-rent anchors from register/context data, rent and size
  anchors only from real portal listings, never demo-seed (Gate 2, A1); hard
  filters exclude rather than penalize (`precision=failed` excludes;
  `precision=street` is scored with a `low_geocode_precision` flag and degraded
  distance factors, Gate 2, A6); confidence flags (sparse <15 tracked POIs/800m,
  thin tag coverage <50% building:levels/400m, low_geocode_precision,
  weak_classifier); tier presentation; reasons invariant (bullets cite only
  signals that fed the score); provenance stamps carrying profile version, BOTH
  anchor versions, context refresh dates and FEHD snapshot date.
- R-007: `db.py` — app schema + helpers; fehd.sqlite stays standalone.
- R-008: `cli.py` — verbs `refresh-context`, `scrape-listings`, `demo-seed`,
  `calibrate`, `validate`, `score-address`, `run`.
- R-009: `web/` — FastAPI + HTMX server-rendered `/` (address + listing entry
  points), `/report/{id}` site report, `/results` ranked shortlist,
  `/methodology` (formulas, anchors, radii, weights, classifier P/R,
  validation results, freshness/licensing notes).
- R-010: validation gates wired into `cli validate`: discrimination test
  (survivors' median composite ≥15 pts above closed set; no closed set in top
  3) and rank-stability test (±5-pt weight perturbation ×200, top-10 Jaccard
  median ≥0.7 else tiers-only presentation).
- R-012: district assignment — every geocoded address resolves to exactly one
  of the 18 HK districts (point-in-polygon over the OSM admin boundaries pulled
  by R-003; the FEHD register's own district column preferred for licence rows),
  or to none, in which case it is excluded from rent scoring rather than
  defaulted. Required by the rent-vs-district percentile on `/report/{id}` and
  by rent anchor calibration. (Added at Gate 2 — gap found in external review.)
- R-011: tests throughout per spec v3 Testing section: recorded ALS/Nominatim
  fixtures (no live calls in CI), saved-HTML source tests, curve-edge factor
  tests, reasons-invariant test, dedup fixture test, demo-seed integration.

Out of scope (explicit, from spec v3): network-distance routing, Huff gravity
rework, churn weight fitting, census/traffic datasets, user accounts, saved
searches, landlord readouts, non-cafe types, LLM layer, map view, revenue
modelling. Post-charter features arrive as change requests.

## 3. Impact surface

New modules (greenfield inside brownfield repo): `suited/db.py`,
`suited/cli.py`, `suited/ingest/{geocode,classify,context,listings}.py`,
`suited/ingest/sources/*`, `suited/scoring/{engine,factors,reasons}.py`,
`suited/scoring/profiles/cafe.py`, `suited/web/**`, `tests/test_<module>.py`.
Untouched/binding: `suited/ingest/fehd.py` (fetch/rebuild/status verb shapes —
cron watchdog calls them), `tests/test_fehd.py`, `data/fehd/raw/` archive
layout (committed source of truth), `docs/plans/` conventions.

## 4. Do-not-touch list

- `ingest/fehd.py` behavior, CLI verbs, and its sqlite schema (app consumers
  read; never migrate fehd.sqlite).
- `data/fehd/raw/*.xml.gz` — append-only archive; derived tables must remain
  rebuildable from it alone.
- Cron job bce60644afc3 + `~/.hermes/scripts/suited-fehd-snapshot.sh`
  (load-bearing: churn roadmap needs uninterrupted daily snapshots).
- Existing 6 tests in `tests/test_fehd.py` must keep passing unchanged.

## 5. Success metrics and acceptance criteria

Observable criteria are defined per-task in `.pmos/plans/plan.md` (A-NNN).
Charter-level gates: classifier soft gate met before scoring consumes its
output and hard gate met before any user-facing publication (R-002);
discrimination + rank-stability results recorded under `docs/validation/`
(R-010); geocode precision distribution reported from the full-register bulk
run, unresolved count visible not hidden (R-001); rent anchors demonstrably free
of demo-seed rows (R-006); existing suite stays green (§4).

## 6. Compatibility constraints

- fehd.sqlite schema and `python -m suited.ingest.fehd` verbs stable.
- App DB is a separate sqlite file managed by `db.py`.
- No JS framework, no build step; HTMX over server-rendered templates.
- Geocoders: ≤1 req/s ALS/Nominatim, identifying User-Agent with contact email,
  permanent but re-runnable cache (`geocoded_at` + `cache_version`), no live
  network in tests (recorded fixtures only — guard active from T-002 onward).
- App DB opened with `journal_mode=wal` and `busy_timeout=30000`; the web layer
  opens read-only connections (cron ingesters and web reads share the file).
- Coordinates stored WGS84, verified against recorded landmark truth.
- Scoring outputs carry provenance stamps: profile/weight/anchor versions +
  context refresh dates + FEHD snapshot date.
- Determinism: same inputs + same anchor versions ⇒ identical composites.

## 7. Tech stack and conventions (from discovery)

Python 3.14.4. Collectors follow the established pattern: refuse-loudly error
handling, archive/raw-bytes-as-truth, CLI-per-module extended by top-level
`cli.py`, snake_case, behavioral sentence test names, flat `tests/` dir with
pytest and synthetic fixtures, docs-as-decisions under `docs/plans/`. New app
code: FastAPI + HTMX + SQLite; scoring = pure functions.

## 8. Risks

- ALS throttling during first bulk run of 17k addresses (undocumented limits)
  — mitigation: ≤1 req/s throttle + monitoring during bulk run + permanent
  cache makes retries cheap.
- Classifier errors propagate into competition scores — mitigation: binding
  0.85/0.70 gate (R-002) blocks consumption until passed.
- Scraper breakage/ToS — mitigation: fixtures-first ordering (R-004 before
  R-005), graceful skip when other sources have data, polite rates; discovery
  flow degrades alone (Product Inversion).
- Zero churn history (single snapshot) — accepted: churn features already
  deferred by spec v3; cron protection in §4.
- Regression risk to running collector — mitigation: §4 do-not-touch +
  existing 6-test baseline must stay green + read-only watchdog (T-022) that
  detects missed cron days and FEHD XML schema drift without importing fehd.py.
- Real building-precision yield of ALS over the register is unknown until the
  bulk run — mitigation: T-019 measures and publishes the distribution; a yield
  below 85% triggers a review checkpoint on distance-factor coverage caveats
  rather than a task failure.

## 9. Team

See `.pmos/out/pm/roster-proposal.md`: planner (PM+architect), implementer,
reviewer/QA — minimal roster sized by impact surface (all-new modules around
one protected running collector).

