# Suited — Architecture (Wave 1)

Date: 2026-08-26 · Author: planner (architect hat) · Wraps spec v3
(`docs/plans/2026-08-26-suited-mvp-design.md`); decisions live in
`.pmos/decisions/ADR-00{1..4}-*.md`, summarized in §5.

## 1. Module boundaries (data ownership)

| Module | Owns | May read |
|---|---|---|
| `ingest/fehd.py` | fehd.sqlite (licences, events, snapshots) — DO NOT MIGRATE | raw XML archive |
| `ingest/geocode.py` | geocode cache table (lat/lon, precision, source, score) | anything to geocode |
| `ingest/classify.py` | cafe classification of FEHD licences (+ brand list) | fehd.sqlite (read) |
| `ingest/context.py` | raw Overpass packs on disk + parsed POI/road tables | nothing else |
| `ingest/listings.py` + `sources/` | listings table; dedup key lives HERE only | geocode cache |
| `scoring/` | scores/tiers/reasons/provenance. Pure functions: no IO, no clocks | inputs handed to it |
| `db.py` | app schema + helpers; sole writer of app sqlite file | all ingest outputs |
| `cli.py` | verb wiring; the only entry point orchestrating ingest order | everything |
| `web/` | HTTP presentation over db reads | scoring outputs via db |

Boundary rules: scoring never imports ingest modules (inputs arrive as plain
data); web never writes; collectors obey ADR-004's dependency boundary;
fehd.sqlite is read-only to everyone but fehd.py.

## 2. Key interfaces

```python
# ingest/sources/base.py
class ListingSource(Protocol):
    name: str                                  # "hse28" | "squarefoot" | "csv" | "demo"
    def fetch(self) -> Iterable[RawListing]: ...
    # RawListing: source, external_id, name_zh|name_en, address_raw,
    # area_sqft, rent_monthly_hkd, districts_hint, scraped_at

# scoring — factor signature (pure)
def factor_competition(ctx: SiteContext, anchors: Anchors) -> FactorResult:
    ...
# FactorResult: score_0_100, raw_counts: dict[str, float],
#               signals: dict[str, float]   # reasons may cite ONLY these keys
# SiteContext: lat, lon, precision ("building"|"street"), radii caches,
#              cafes_nearby (from classifier), pois, roads, listing fields

@dataclass(frozen=True)
class ScoredListing:
    listing_id: str
    composite: float                 # deterministic given anchor versions
    tier: Literal["strong_fit", "worth_a_look", "poor_fit"]
    excluded: bool | None            # hard-filter reason when excluded
    confidence_flags: list[str]      # sparse_coverage | thin_tag_coverage
    factors: dict[str, FactorResult]
    provenance: Provenance

@dataclass(frozen=True)
class Provenance:
    profile_version: str             # e.g. "cafe-v3"
    weights_version: str
    anchors_version: str             # from profiles/cafe.py ANCHORS table
    context_refresh_dates: dict[str, str]   # per district tile pack
    fehd_snapshot_date: str          # from fehd.sqlite snapshots table
    classifier_eval: str             # P/R line published on /methodology
```

## 3. Data flow

```
[FEHD XML daily]──► ingest/fehd.py ──► fehd.sqlite        (RUNNING, cron bce60644afc3)
                                        │ licences
        ┌───────────────────────────────┘
        ▼
[ALS+Nominatim]──► ingest/geocode.py ──► geocode cache  (ADR-001 gate ≥75)
[OSM Overpass]───► ingest/context.py ──► poi/road tables + raw packs on disk
[fehd licences]──► ingest/classify.py ► cafe flags     (ADR-002 gate P≥.85/R≥.70)
[demo fixtures / portals]──► sources/* ─► listings table (dedup in listings.py)
                                        │
user address ──────────────────────────►│
                                        ▼
        cli calibrate ─► profiles/cafe.py ANCHORS (ADR-003, frozen+versioned)
                                        │
                        scoring/engine.py (+factors, reasons) — pure
                                        ▼
                db.py (app schema) ◄── cli score-address / validate / demo-seed
                                        ▼
                FastAPI+HTMX: /  /report/{id}  /results  /methodology
```

Ordering invariant: demo fixtures land before portal scrapers so scoring and
web are testable without scraper health (spec v2/v3 rule).

## 4. Determinism contract

Same inputs + same `provenance.anchors_version` ⇒ byte-identical report.
Enforced by: pure factor functions; frozen absolute anchors (never
percentile-within-results); hard filters exclude rather than bend scores;
reasons-invariant test; recorded-fixture tests only (no live network in CI).

## 5. ADR index (full text under `.pmos/decisions/`)

- **ADR-001 ALS score gate**: normalize-first; Score <75 ⇒ recorded failed,
  never accepted (probes showed wrong-but-confident 50–64 matches); Nominatim
  fallback capped at street precision; ≤1 req/s + permanent cache.
- **ADR-002 classifier quality gate**: name-token+licence-type classifier must
  hit P≥0.85 / R≥0.70 on a 100-record hand-labelled sample before feeding the
  competition factor; RR is not cafe.
- **ADR-003 anchors-not-percentiles**: fixed absolute anchors via citywide
  `calibrate`, frozen versioned into profiles/cafe.py; determinism beats
  convenience; anchor changes = new version.
- **ADR-004 collector dependency boundary**: cron/unattended ingesters stay
  stdlib-only (extends proven fehd.py convention); failing portal source skips
  gracefully while others supply.

## 6. Failure postures (spec v3 Error Handling)

- Geocode failure → visible unscoreable row, never approximated coordinates.
- Overpass tile → retry ×3, keep last-good pack, fail loudly after.
- Portal source → skip with refresh stamp if another source has data.
- Classifier below gate → classified output withheld from competition factor.
- FEHD truncated register → refused (existing guard, unchanged).

## 7. Open questions for later waves (not blockers)

1. Anchor re-calibration cadence (quarterly? on data refresh?) — needs a
   policy ADR once first recalibration happens.
2. Nominatim vs ALS disagreement handling beyond street cap — defer until
   precision distribution from the bulk run exists.
