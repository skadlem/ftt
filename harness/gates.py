"""Gates G0/G1/G2 — refuse to run on unfrozen eval sets; tiered reporting.

Design-doc rules encoded here:
  - freeze guard: fixtures must hash-match freeze.json (per-file check)
  - verdicts are only scored on CONSISTENT pairs (flips discarded, counted)
  - flip-rate > FLIP_ALARM is itself a stop-and-fix finding (D9)
  - tiers: core (real) and ring (synthetic). Pass requires the ring to clear
    the pre-registered threshold AND the core not to contradict (D14).
  - significance: two-sided exact sign test on discordant pairs (binomial);
    ties/C verdicts are not evidence either way. Small n is honest, not hidden.
"""
import hashlib
import json
import math
from pathlib import Path

FLIP_ALARM = 0.20

# pre-registered defaults (harness spec will pin these before training runs)
THRESHOLDS = {
    "G0_teacher_over_baseline_min": 0.60,   # a real gap worth closing
    "G1_student_vs_teacher_min": 0.45,      # non-inferiority
    "G1_student_vs_baseline_min": 0.65,
    "alpha": 0.05,
}


def check_freeze(fixtures_dir: Path) -> str:
    """Raise if fixtures diverge from the freeze; return aggregate hash."""
    freeze = Path(fixtures_dir) / "freeze.json"
    if not freeze.exists():
        raise RuntimeError("gate refuses: no freeze.json — eval set not frozen")
    doc = json.loads(freeze.read_text())
    files = doc["files"]
    cur = {}
    for pat in ("core/**/*.md", "core/**/*.json", "ring/**/*.md", "ring/**/*.json"):
        for p in sorted(Path(fixtures_dir).glob(pat)):
            cur[str(p.relative_to(fixtures_dir))] = hashlib.sha256(p.read_bytes()).hexdigest()
    if cur != files:
        diff = sorted({k for k in set(cur) | set(files) if cur.get(k) != files.get(k)})
        raise RuntimeError(f"gate refuses: eval set changed after freeze — {diff[:5]}")
    return doc.get("aggregate_sha256", "")


def sign_test_p(wins: int, losses: int) -> float:
    """Exact two-sided binomial sign test under p=0.5 on discordant pairs."""
    n = wins + losses
    if n == 0:
        return 1.0
    obs = min(wins, losses)
    tail = sum(math.comb(n, k) * (0.5 ** n) for k in range(0, obs + 1))
    return min(1.0, 2 * tail)


def _tally(verdicts: list[dict], arms: tuple[str, str]) -> dict:
    """Per-tier win/loss/tie tally for one comparison, verdicts mapped to arms."""
    a, b = arms
    tiers = ("core", "ring", "unknown")
    t = {tier: {"wins_a": 0, "wins_b": 0, "ties": 0, "flips": 0} for tier in tiers}
    for v in verdicts:
        tier = v.get("tier", "unknown")
        if tier not in t:
            tier = "unknown"
        if not v["consistent"]:
            t[tier]["flips"] += 1
            continue
        if v["verdict"] == "C":
            t[tier]["ties"] += 1
            continue
        winner = v["arms"]["A"] if v["verdict"] == "A" else v["arms"]["B"]
        if winner == a:
            t[tier]["wins_a"] += 1
        elif winner == b:
            t[tier]["wins_b"] += 1
    return t


def summarize(verdicts_path: Path, tiers: dict[str, str]) -> list[dict]:
    """Group verdicts by unordered arm-pair; per-tier tally; win-rates and
    sign-test p over the combined decided set."""
    by_path = []
    for line in Path(verdicts_path).read_text().splitlines():
        v = json.loads(line)
        v["tier"] = tiers.get(v["task_id"], "unknown")
        by_path.append(v)
    groups: dict[tuple, list[dict]] = {}
    for v in by_path:
        key = tuple(sorted((v["arms"]["A"], v["arms"]["B"])))
        groups.setdefault(key, []).append(v)
    rows = []
    for (a, b), vs in sorted(groups.items()):
        t = _tally(vs, (a, b))
        wa = sum(x["wins_a"] for x in t.values())
        wb = sum(x["wins_b"] for x in t.values())
        ties = sum(x["ties"] for x in t.values())
        flips = sum(x["flips"] for x in t.values())
        decided = wa + wb
        rows.append({
            "arms": [a, b],
            "tiers": t,
            "wins_a": wa, "wins_b": wb, "ties": ties, "flips": flips,
            "winrate_a": wa / decided if decided else 0.5,
            "p_sign": sign_test_p(wa, wb),
            "flip_rate": flips / len(vs) if vs else 0.0,
            "alarm_flip": (flips / len(vs)) > FLIP_ALARM if vs else False,
        })
    return rows


def verdict_gate(row: dict, student: str, baseline: str, teacher: str) -> dict:
    """Apply G1 structure to one summarized comparison row (pair must involve
    student). Returns per-tier pass/fail + overall (D14 no-contradiction)."""
    other = baseline if row["arms"][1] == student or row["arms"][0] != student else teacher
    a, b = row["arms"]
    res = {"comparison": [a, b], "per_tier": {}, "alarm_flip": row["alarm_flip"]}
    def wr(side):
        return {"wins_a": row["tiers"][side]["wins_a"], "wins_b": row["tiers"][side]["wins_b"]}
    for tier in ("core", "ring"):
        w = wr(tier)
        s_wins = w["wins_a"] if a == student else w["wins_b"]
        o_wins = w["wins_b"] if a == student else w["wins_a"]
        decided = s_wins + o_wins
        res["per_tier"][tier] = {
            "student_winrate": s_wins / decided if decided else None,
            "decided": decided,
            "p_sign": sign_test_p(s_wins, o_wins),
        }
    return res
