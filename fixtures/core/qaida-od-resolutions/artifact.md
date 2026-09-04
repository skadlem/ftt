# Architect Open-Decision Resolutions

Resolved 2026-08-10 by architect agent. Each section: analysis, decision, exact specs, risks.

---

## OD-B: Map SDK Choice

### Analysis

**Option A: OpenStreetMap + MapLibre Native** (`@maplibre/maplibre-react-native`)
- React Native / Expo SDK 57: supported via Expo config plugin. Requires dev build (native module), already the case since expo-speech-recognition also needs dev build.
- Offline tiles: native tile caching built-in. Can pre-download region packs.
- KZ POI quality: OSM coverage in Almaty/Astana is good (community-mapped). Pavlodar adequate. POI density lower than 2GIS in some KZ cities but sufficient for MVP.
- Licensing: BSD-2-Clause. Tiles from OSM tile server or self-hosted. No usage fees.
- Props interface: MapView component wraps the native SDK; props `{ venues, center, lang, onMarkerPress }` remain stable (DN-4).

**Option B: 2GIS MapKit**
- KZ coverage: excellent local data, better POI density than OSM in KZ cities.
- React Native: no official RN package. Would require a native bridge or WebView wrapper. Significant integration cost.
- Offline: supported in native SDKs but RN bridge is not maintained.
- Licensing: proprietary, commercial license required for production. Adds vendor lock-in.
- Verdict: rejected. No RN-compatible SDK, proprietary licensing, bridge maintenance burden.

**Option C: Mapbox**
- Feature-rich, good RN SDK (`@rnmapbox/maps`), but requires Mapbox account + token.
- Free tier: 50K map loads/month, adequate for MVP.
- Overkill for this scope. Adds a vendor dependency.
- Verdict: rejected. OSM+MapLibre satisfies requirements without vendor lock-in.

### Decision

**Use OpenStreetMap + MapLibre Native via `@maplibre/maplibre-react-native`.**

### Exact Specs

```bash
npx expo install @maplibre/maplibre-react-native
```

Expo config plugin in `app.json`:
```json
{
  "expo": {
    "plugins": [
      ["@maplibre/maplibre-react-native", { "locationWhenInUsePermission": "Allow Qaida to show nearby places." }]
    ]
  }
}
```

Tile source: `https://tile.openstreetmap.org/{z}/{x}/{y}.png` (default). For better KZ performance, consider a CDN-proxied tile server or pre-cached regional tiles later.

Offline degradation (rule 3 spirit): if map tiles fail to load, the app shows the list view (existing SegmentedControl toggle). Map failure does NOT block results display.

### Risks

- **R-B1**: MapLibre RN package may lag behind Expo SDK updates. Mitigation: pin to the version Expo recommends for SDK 57; test `npx expo prebuild` early.
- **R-B2**: OSM tile server rate limits (2 tiles/sec). Mitigation: implement tile caching + throttling; consider a tile proxy for production.
- **New dependency flag** (rule 8): `@maplibre/maplibre-react-native` -- BSD-2-Clause, no fees.

---

## OD-C: Result Count Parameterization

### Analysis

Current state:
- `_MAX_RESULTS = 3` hard-coded in `recommend.py` line 63.
- `apply_partner_rules()` in `partner.py` accepts `max_results: int = 3` (line 93-96), and the partner slot cap is `_PARTNER_SLOT_CAP = 1` (line 22) -- always max 1 partner per result set regardless of count.
- `RecommendResponse` in `schemas.py` has `max_length=3` on results (line 207).
- Partner rule (ARCHITECTURE rule 4): "Max 1 partner venue per 3 results." The current code enforces cap=1 regardless of result count.

The charter vision says "3-4+ results" with "show more" available. Option (a) -- backend parameterizes result count -- is the simplest and most flexible:

1. `RecommendRequest` gains optional `max_results: int = Field(default=3, ge=1, le=10)`.
2. `_MAX_RESULTS` in recommend.py becomes the request's `max_results` value.
3. Partner slot rule scales: `max_partners = max(1, ceil(max_results / 3))`. For 3 results: 1 partner. For 4-6: 2 partners. For 7-9: 3 partners. For 10: 4 partners.
4. `RecommendResponse.results` changes `max_length=3` to `max_length=10`.

### Decision

**Backend parameterizes result count via request field. Partner slot rule scales proportionally.**

### Exact Schema Changes

**`app/schemas.py` -- `RecommendRequest`:**
```python
class RecommendRequest(BaseModel):
    text: str | None = Field(default=None, max_length=500)
    chips: list[str] | None = None
    lat: float
    lng: float
    session_key: str = Field(min_length=8, max_length=128)
    city: str | None = Field(default=None, max_length=32)
    lang: str | None = Field(default=None, max_length=8)
    recently_shown: list[str] | None = Field(default=None, max_length=100)
    max_results: int = Field(default=3, ge=1, le=10)
```

**`app/schemas.py` -- `RecommendResponse`:**
```python
class RecommendResponse(BaseModel):
    results: list[ResultCard] = Field(default_factory=list, max_length=10)
```

**`app/routers/recommend.py` changes:**
- Remove `_MAX_RESULTS = 3` constant.
- `_ranking_context()`: use `req.max_results` instead of `_MAX_RESULTS`.
- Pipeline: use `req.max_results` for relaxation threshold and card slicing.
- All references to `_MAX_RESULTS` become `req.max_results`.

**`app/ranking/partner.py` changes:**
```python
import math

def apply_partner_rules(
    scored: Sequence[ScoredVenue],
    max_results: int = 3,
    context: RankingContext | None = None,
) -> list[ScoredVenue]:
    # Scale partner cap: max 1 partner per 3 results (rule 4)
    partner_cap = max(1, math.ceil(max_results / 3))
    # ... rest of logic unchanged, replace _PARTNER_SLOT_CAP with partner_cap
```

### Risks

- **R-C1**: Existing 244 tests assume `_MAX_RESULTS = 3`. Tests must be updated to pass `max_results=3` explicitly or accept the default. The default value preserves backward compatibility.
- **R-C2**: `RankingContext.max_results` is used in scorer. Verify scorer does not hard-code 3 elsewhere.
- **R-C3**: Group consensus flow (`groups.py`) calls `run_recommend_pipeline` -- must pass `max_results` or accept default 3.

---

## OD-D: Adaptive Search Radius

### Analysis

Current `SYSTEM_PROMPT` in `prompts.py` line 91:
```
- max_distance_m: 3000 unless the user explicitly states a distance.
```

This instruction does NOT account for excursion/travel/weekend-type queries. "Camping for the weekend in nature" would get `max_distance_m: 3000` (3 km) -- far too narrow for a nature outing.

The intent schema already supports arbitrary `max_distance_m` values (integer, minimum 0). The LLM can already output larger values; it just needs better instructions.

The keyword rule parser (`rules.py`) does not set distance either -- it relies on defaults. So the fix is prompt-only (no code path change, consistent with DN-7: venues never enter prompts).

### Decision

**Prompt change required.** Update the `max_distance_m` instruction in `SYSTEM_PROMPT` to guide the LLM to widen radius for excursion/travel/nature queries.

### Exact Prompt Text

Replace line 91 in `prompts.py`:

**Before:**
```
- max_distance_m: 3000 unless the user explicitly states a distance.
```

**After:**
```
- max_distance_m: default 3000 for nearby/urban queries (coffee, lunch, bar, cafe). Widen for excursion or travel queries: 10000-20000 for "day trip", "weekend", "nature", "camping", "hiking", "выезд на природу", "за городом", "поход". Use 50000+ only for explicit inter-city travel ("from Almaty to ..."). If the user explicitly states a distance, convert to meters.
```

### Risks

- **R-D1**: LLM may over-widen for ambiguous queries. Mitigation: the prompt explicitly constrains widening to excursion-type signals. Test with edge cases ("кафе" should stay 3000, "пикник в горах" should widen).
- **R-D2**: Wider radius retrieves more candidates, increasing scoring latency. Mitigation: retrieval already caps at 50 candidates; wider radius just changes the WHERE clause distance threshold.
- **No code change needed**: intent parser, sanitization, and retrieval already support arbitrary `max_distance_m` values.

---

## OD-F: Bottom Sheet Dependency

### Analysis

Current `mobile/package.json` dependencies checked:
- `react-native-reanimated`: **NOT installed**.
- `react-native-gesture-handler`: **NOT installed**.
- No bottom sheet library present anywhere in the codebase.

Since neither prerequisite is installed, building a custom bottom sheet would require adding both `react-native-reanimated` and `react-native-gesture-handler` anyway -- the same deps that `@gorhom/bottom-sheet` brings as peer dependencies.

`@gorhom/bottom-sheet` (v5.x) is the industry standard for RN bottom sheets. It:
- Depends on `react-native-reanimated` and `react-native-gesture-handler` (brings them as peer deps).
- Compatible with Expo SDK 57 + React Native 0.86.2 (confirmed via Expo SDK 57 compatibility matrix).
- Provides snap points, gesture handling, keyboard handling, and `BottomSheetFlatList`/`BottomSheetScrollView` for rendering result lists.
- Used by major RN apps, well-maintained, MIT licensed.

### Decision

**Use `@gorhom/bottom-sheet` (v5.x).** Flag as new dependency per rule 8. It brings `react-native-reanimated` and `react-native-gesture-handler` as transitive dependencies.

### Exact Specs

```bash
npx expo install @gorhom/bottom-sheet
```

This installs:
- `@gorhom/bottom-sheet` ^5.x
- `react-native-reanimated` (peer dep, Expo-managed version)
- `react-native-gesture-handler` (peer dep, Expo-managed version)

Expo config plugins in `app.json`:
```json
{
  "expo": {
    "plugins": [
      "react-native-gesture-handler",
      "react-native-reanimated"
    ]
  }
}
```

Usage pattern:
```tsx
import BottomSheet, { BottomSheetFlatList } from '@gorhom/bottom-sheet';

<BottomSheet
  snapPoints={['25%', '50%', '90%']}
  index={0}
  enablePanDownToClose={false}
>
  <BottomSheetFlatList
    data={results}
    renderItem={({ item }) => <VenueCard venue={item} />}
  />
</BottomSheet>
```

### New Dependencies (Rule 8 Flag)

| Package | License | Purpose |
|---------|---------|---------|
| `@gorhom/bottom-sheet` | MIT | Swipe-up results panel |
| `react-native-reanimated` | MIT | Animation engine (transitive) |
| `react-native-gesture-handler` | MIT | Touch/gesture handling (transitive) |

### Risks

- **R-F1**: `react-native-reanimated` requires a dev build (native module). Already the case since expo-speech-recognition + MapLibre also need dev builds.
- **R-F2**: Bottom sheet gesture conflicts with map pan gestures. Mitigation: `@gorhom/bottom-sheet` has `enableContentPanningGesture` and `enableHandlePanningGesture` config; test interaction with MapLibre map pan.
- **R-F3**: Reanimated 3.x API changes. Pin to Expo-managed version for SDK 57 compatibility.

---

## Summary

| OD | Decision | New Deps | Files Changed |
|----|----------|----------|---------------|
| OD-B | MapLibre Native + OSM | `@maplibre/maplibre-react-native` | `MapView.tsx`, `app.json`, `package.json` |
| OD-C | Parameterize `max_results` (1-10), scale partner cap | None | `schemas.py`, `recommend.py`, `partner.py` |
| OD-D | Prompt update for excursion radius | None | `prompts.py` (SYSTEM_PROMPT) |
| OD-F | `@gorhom/bottom-sheet` v5 | `@gorhom/bottom-sheet` + reanimated + gesture-handler | New BottomSheet component, `app.json`, `package.json` |

All decisions preserve backward compatibility (defaults unchanged) and conform to existing conventions. No blockers identified.