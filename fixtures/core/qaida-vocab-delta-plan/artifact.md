# Vocabulary delta plan — landing D-2 (`romantic`, `kid_friendly`, `birthday`)

Owner: architect | Date: 2026-08-08 | Decision: phase0 D-2 = Option A
Scope: `ATMOSPHERE += romantic, kid_friendly` and `GOOD_FOR += birthday`.

## 0. Why this must land FIRST — the D11 one-way door

`TECH_DECISIONS.md` D10 rates the venue attribute vocabulary 🚪🚪:
*"re-curating 2 000 venues is the one thing you can't cheaply redo"*.

The mechanism is concrete. A curator tagging 2526 venues with a vocabulary
missing `romantic` will substitute `intimate`, and those substitutions are
indistinguishable afterwards from deliberate `intimate` judgements. Adding
`romantic` later does not fix them; it requires **re-reviewing every venue**.

**Therefore: the entire delta below must be merged and green before the first
venue is tagged.** This is the hard ordering constraint of the whole project. The
delta itself is ~15 lines of code; the cost of getting the order wrong is ~420 h.

## 1. Files that change, in order

Everything lands in **one commit**. Splitting it breaks the build in the middle:
`test_seed_data.py` deliberately duplicates the vocabularies, so config and guard
must move together (charter §8 risk row: "Vocab delta + guard updates land in the
same commit").

### 1. `backend/app/config.py` — the source of truth

```python
# GOOD_FOR, config.py:45
GOOD_FOR: list[str] = ["date", "friends", "solo", "work", "family", "party", "birthday"]

# ATMOSPHERE, config.py:47-58 — append before the closing bracket
    "spacious",
    "romantic",
    "kid_friendly",
]
```

**Append, never reorder.** Nothing indexes these lists positionally today, but
append-only keeps that true for free.

Placement note: `kid_friendly` in ATMOSPHERE is a judgement ("this place feels
right with kids"), distinct from the existing `kid_room`/`playground` FEATURES
which are verifiable facilities. That is exactly the VIBE_VOCABULARY §8 split
rule, and it is worth a one-line comment in `config.py` so the next reader does
not "fix" it.

### 2. `backend/app/ranking/explain.py` — labels

**Measured fact: there is no `_GOOD_FOR_LABELS` table.** `explain.py` labels
`atmosphere` only (`_ATMOSPHERE_LABELS`, :18-55; used by `_atmosphere_phrase`, :107).
So:
- `birthday` needs **no label work at all** — `good_for` is a filter/scoring
  field with no explain phrase. Do not add a labels table for it (YAGNI).
- `romantic` and `kid_friendly` need **one entry each in all three languages**.

An unlabeled atmosphere tag does not crash — `_atmosphere_phrase` filters with
`if t in labels` (:111) — it **silently drops the explanation phrase**. That
silence is the risk: the venue still ranks, the reason just vanishes. Hence the
guard in step 4.

```python
"ru": {... "romantic": "Романтично", "kid_friendly": "С детьми"}
"kk": {... "romantic": "Романтикалы", "kid_friendly": "Балалармен"}   # ← NEEDS NATIVE CHECK
"en": {... "romantic": "Romantic",   "kid_friendly": "Kid-friendly"}
```

### 3. `ARCHITECTURE.md` — the vocabulary table (:231, :233-234)

```python
GOOD_FOR = ["date","friends","solo","work","family","party","birthday"]

ATMOSPHERE = ["cozy","loud","trendy","quiet","outdoor","scenic",
              "traditional","modern","intimate","spacious",
              "romantic","kid_friendly"]
```
The heading above it reads *"Closed vocabularies (do not extend without saying so)"* —
D-2 plus this plan is the saying-so. Reference D-2 in a one-line note under the block.

### 4. `backend/tests/test_seed_data.py` — the guards (:26, :28-31)

These lists are duplicated **on purpose** (file header: *"if the contract changes,
this test must change with it"*). Update them to match §1.1 exactly.

Then add two new tests. The second is the one that actually earns its keep:

```python
def test_vocab_guard_matches_config() -> None:
    """The duplicated lists above must equal config.py. Duplication is the
    point; silent divergence is not."""
    from app.config import ATMOSPHERE as CFG_ATMO, GOOD_FOR as CFG_GF
    assert sorted(ATMOSPHERE) == sorted(CFG_ATMO)
    assert sorted(GOOD_FOR) == sorted(CFG_GF)

def test_every_atmosphere_tag_has_labels_in_every_language() -> None:
    """An unlabeled atmosphere tag silently drops its explanation phrase."""
    from app.config import ATMOSPHERE
    from app.ranking.explain import _ATMOSPHERE_LABELS
    for lang in ("ru", "kk", "en"):
        missing = [t for t in ATMOSPHERE if t not in _ATMOSPHERE_LABELS[lang]]
        assert not missing, f"{lang}: unlabeled atmosphere tags {missing}"
```

The second test makes the *next* vocab addition impossible to get half-right.
That is the whole reason to write it now rather than after.

### 5. `backend/verify_contract.py` — no change needed

It only asserts the vocabulary names exist in config (`verify_contract.py:51-52`),
not their contents. It stays green.

### 6. `docs/VIBE_VOCABULARY.md` — flip status

Change the three tags from "approved in doc, not in config" to landed, dated,
citing D-2. This closes the session4 handoff §3 item.

### Not changed

- **No migration.** `atmosphere`/`good_for` are already `text[]` (migration 001).
  Charter §4: migrations 001/003 untouched.
- **No mobile change.** `VenuePublic` already carries `good_for`/`atmosphere` as
  string arrays; new values need no client update. `check_contract_drift.py` stays clean.
- **`MOODS` unchanged.** `romantic` is already a user-side mood (`config.py:36`).
  This delta makes the *venue side* able to answer it — that is the point, and it
  is why these two `romantic`s are not a duplication bug.
- **No eval baseline change.** New tags are unused until tagging starts, so
  precision@3 cannot move. Re-run B2 anyway as a regression check.

## 2. Verification after the commit

```bat
cd backend
..\.venv\Scripts\python.exe -m pytest tests -q                  :: 223 + 2 new = 225
..\.venv\Scripts\python.exe evals\run_eval.py --check --mock    :: >= 0.9455, expect unchanged
..\.venv\Scripts\python.exe verify_contract.py                  :: PASS
..\.venv\Scripts\python.exe seed\load_seed.py --dry-run --fixtures seed/osm
cd .. && .venv\Scripts\python.exe check_contract_drift.py
```
Expected: all green, eval **exactly** unchanged. A moved eval number here means
something was touched that should not have been.

## 3. BLOCKING USER ACTION — kk labels

`docs/VIBE_VOCABULARY.md` §3 marks Kazakh labels best-effort. The two proposed
above (`Романтикалы`, `Балалармен`) are **unverified** and will be shown to real
users in the app's explanation strings.

- **Blocks:** the start of bulk tagging. It does not block the code merge — land
  the delta with the placeholder kk labels so the vocabulary is closed and
  curation tooling can be built, then correct the two strings before tagging.
  A label correction is a one-line, zero-risk commit; a vocabulary correction
  after tagging is not.
- **Ask:** a native Kazakh speaker confirms or corrects those two strings.
- **Recommendation:** ask now, in parallel with backend work. It is a 5-minute
  question with a multi-week critical path behind it.

## 4. Ordering summary

1. Native-speaker kk check requested (async, non-blocking).
2. Vocab delta commit (§1.1–1.4, 1.6) → verification §2 green.
3. kk labels corrected if the speaker disagrees.
4. **Only then**: build curation tooling and begin tagging.

Step 4 must not start before step 2 is merged. Everything else in this project is
recoverable; tagging against a stale vocabulary is not.
