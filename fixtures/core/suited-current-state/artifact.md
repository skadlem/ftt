# Suited — Current State (Wave 0 Discovery, Planner)

Date: 2026-08-26 · Author: planner (PM+architect) · Brownfield baseline before Wave 1.

Sources: spec v3 (`docs/plans/2026-08-26-suited-mvp-design.md`), collector notes
(`docs/plans/2026-08-26-fehd-collector-notes.md`), `.pmos/log.md`, KB
(`.pmos/kb.sqlite3`, roles pm/architect/shared), graphify queries against
`graphify-out/graph.json` (45 nodes / 73 edges / 15 communities).

Graphify queries run (recorded per shared rule #2):
1. "What modules exist and what does each do? (module map)"
2. "How does the FEHD collector ingest/fehd.py work: entry points, data flow, error handling?"
3. "What tests exist in tests/test_fehd.py and what do they cover?"
4. "What is in the data/fehd directory (raw archive, sqlite) and how is it produced/consumed?"
5. "What CLI entry points, error handling guards, and coding conventions does fehd.py use?"

## 1. Module Map

Only two source modules + one test module exist today. Everything else in the
spec is **not yet built**.

| Path | State | Responsibility |
|---|---|---|
| `suited/ingest/fehd.py` (245 LOC) | RUNNING | Daily FEHD register collector. Functions (from graph): `connect()` L61 (sqlite setup), `parse()` L69 → `(generation date, {licno: record})`, `archive()` L94 / `read_archived()` L102 (gzip archive IO), `apply_snapshot()` L106 (fold snapshot into derived tables, emit open/close events), `fetch()` L157 (download+archive+apply), `rebuild()` L190 (re-derive all tables from raw archive, oldest first), `status()` L220 (coverage/counts). CLI via `python -m suited.ingest.fehd {fetch,rebuild,status}` at ~L238. |
| `suited/__init__.py`, `suited/ingest/__init__.py` | present | Package markers only. |
| `tests/test_fehd.py` (120 LOC) | 6 tests | Fixtures `register()` L14, `archive()` L28, `events()` L43; tests below §4. |
| `data/fehd/raw/LP_Restaurants_EN_<date>.xml.gz` | committed | Raw archive = source of truth. 1 snapshot so far (2026-08-26). |
| `data/fehd/fehd.sqlite` (3.1 MB) | gitignored, rebuildable | Derived tables (verified live): `licences` (17,223 rows: licno, type, district, name, address, info, expiry, first_seen, last_seen), `licence_events` (0 rows: licno, event, observed_on, type, district, name, address), `snapshots` (1 row: taken_on, fetched_at, path, sha256, licence_count). |
| `docs/plans/` | committed | Spec v3 (authoritative design) + FEHD collector ops notes. |

Automation: Hermes cron `suited-fehd-daily-snapshot` (id **bce60644afc3**),
daily 10:00 UTC+05 (~13:00 HKT, after upstream ~09:00 HKT refresh), via
`~/.hermes/scripts/suited-fehd-snapshot.sh`. Watchdog pattern: silent on no-op,
verbose on fresh data or failure. Known gap: no live delivery channel; output
only in `cronjob(action='list')`.

## 2. Tech Stack + Versions

- **Python 3.14.4** (verified: `python3 --version`).
- **Collector constraint: stdlib-only** (`urllib`/`gzip`/`sqlite3`/`xml`) — by
  design, so the cron job can never be blocked by app dependency churn.
- Rest of app (spec v3, not yet installed): FastAPI + HTMX server-rendered UI +
  SQLite; no JS framework, no build step.
- Tooling present: pytest (test runner), graphify index (`graphify-out/`),
  PMOS template at `/home/madiyar/pm-agent-team`.

## 3. Conventions Observed (existing code)

- Naming: `snake_case` functions; test names are full behavioral sentences
  (`test_first_snapshot_is_a_baseline_not_thousands_of_openings`,
  `test_a_truncated_register_is_refused_rather_than_archived`). Keep this style.
- Error handling philosophy: **refuse loudly rather than degrade silently** —
  truncated/empty registers are never archived (would fabricate mass closure);
  first snapshot is a baseline (no synthetic opening storm); closures carry
  last-known details forward; lapse-and-return yields two distinct events
  (bug fixed 2026-08-26). Spec extends this: ALS score-gate ≥75 marks failures
  instead of accepting wrong-but-confident matches; Overpass retry ×3/tile,
  keep last-good pack; failing listing sources skipped if others have data.
- Archive-as-truth: raw bytes committed to git; every derived table must be
  rebuildable from the archive alone (`rebuild()` determinism is tested).
- CLI-per-module: `python -m suited.ingest.fehd <verb>`; spec continues this
  with a top-level `cli.py` (`refresh-context / scrape-listings / demo-seed /
  calibrate / validate / score-address / run`).
- Tests colocated in flat `tests/` dir, pytest, no live network in tests
  (synthetic fixtures only); spec mandates recorded ALS/Nominatim response
  fixtures and saved-HTML-only source tests.
- Docs-as-decisions: every subsystem gets an ops/design note under
  `docs/plans/`; dirty-tree policy allows committing agent-authored paths
  (`.pmos/`, `docs/plans/`, authored source) but NOT user's uncommitted work;
  `data/fehd/` stays committed by established convention.

## 4. Test Suite State (fresh verification)

Command: `python3 -m pytest tests/ -q` from `/home/madiyar/suited`. Real output:

```
......                                                                   [100%]
6 passed in 0.02s
EXIT=0
```

Coverage (from graph): baseline semantics (first snapshot ≠ thousands of
openings), open/close detection between days, closed licence keeps last-known
details, first/last_seen track snapshot runs, deterministic rebuild from
archive, truncated-register refusal. Event derivation is treated as the
collector's whole point and gets the tests accordingly.

## 5. Top Integration Points & Areas Relevant to the Goal

Goal: score any HK address for cafe revenue fit; primary flow = Site Report,
secondary = ranked shortlist over listings.

Integration seams the next phases must respect:

1. **fehd.sqlite stays standalone.** App schema lives in a separate `db.py`
   (spec: "app schema + helpers (fehd.sqlite stays standalone)"). Consumers
   read classified cafes + churn from FEHD side; do not migrate its schema.
2. **FEHD addresses feed the geocoder.** 17,223 free-text addresses must pass
   through `ingest/geocode.py`: normalize-first → ALS with Score ≥75 gate →
   Nominatim fallback (street cap), ≤1 req/s, permanent cache. Expect a few %
   unresolved — they stay visibly unscoreable, never approximated away.
3. **Classifier gates competition factor.** `ingest/classify.py` (name tokens +
   licence type; RR is NOT cafe — evidence: "COFFEE" 419 RR vs 80 RL) must hit
   precision ≥0.85 / recall ≥0.70 on a 100-record hand-labelled sample before
   feeding scoring; results published on `/methodology`.
4. **Scoring determinism contract.** Fixed absolute anchors via `cli calibrate`,
   frozen into versioned `profiles/cafe.py`; hard filters exclude, never bend
   scores; provenance stamps incl. FEHD snapshot date; reasons-invariant.
5. **Snapshot cadence.** Churn signal needs ≥6 months of daily snapshots —
   protecting the cron job (bce60644afc3) is load-bearing for the roadmap.
6. **Cron watchdog script** `~/.hermes/scripts/suited-fehd-snapshot.sh` calls
   the same module CLI that tests cover — keep `fetch/rebuild/status` verbs
   stable.

## 6. Impact Surface — Next Build Phase

Per spec v3 Project Layout, the following modules are NEW (nothing exists yet;
each is greenfield inside the brownfield repo):

| Module | Purpose (spec) | Depends on |
|---|---|---|
| `ingest/geocode.py` | normalize → ALS (≥75 gate) → Nominatim; cache lat/lon + precision/source/score | FEHD addresses; new cache table |
| `ingest/classify.py` | cafe vs other-food classifier + chain brand list | fehd.sqlite licences table |
| `ingest/context.py` | Overpass pull, tiled by district bbox, non-food POIs + roads, raw cache on disk | new |
| `ingest/listings.py` + `ingest/sources/{base,hse28,squarefoot,csv}.py` | ListingSource protocol, dedup key (addr + ±5% area + ±5% rent) | geocode.py (precision-gated) |
| `scoring/{engine,factors,reasons}.py`, `scoring/profiles/cafe.py` | pure deterministic functions, anchors, tiers | classify, context, geocode, listings |
| `web/` (FastAPI + HTMX, templates/static) | `/`, `/report/{id}`, `/results`, `/methodology` | scoring |
| `db.py` | app schema + helpers (separate from fehd.sqlite) | all ingest outputs |
| `cli.py` | refresh-context / scrape-listings / demo-seed / calibrate / validate / score-address / run | everything |

Untouched/stable: `ingest/fehd.py` (running; changes only if upstream format
breaks), `tests/test_fehd.py`, `data/fehd/` layout. New tests will follow the
existing `tests/test_<module>.py` pattern; geocoder/scorer tests use recorded
fixtures, no live calls in CI.

Validation obligations carried into the charter: discrimination test,
rank-stability test (±5-pt ×200, Jaccard ≥0.7 else tiers-only), classifier
quality gate (0.85/0.70).

## 7. Risks / Notes for Charter

- Single snapshot only — zero churn history; churn features deferred by design.
- ALS rate limits undocumented; first bulk geocode of 17k addresses needs
  throttling monitoring (spec Open Risks).
- Classifier errors propagate into competition scores — quality gate binding.
- Host constraint: worker spawns inherit coordinator model (stealth/ox-alpha)
  until delegation.model pinned — recorded in `.pmos/log.md`.
