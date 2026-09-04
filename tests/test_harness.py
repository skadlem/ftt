"""T3 self-tests — the 10 cases from the design doc's step 2.

These run BEFORE any gate is trusted. Judge-validation cases use deterministic
fakes: the point is harness correctness, not judge quality (real judge
validation runs on the seed pair set in validate_judge.py, offline).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.extract_final import LENGTH_CAP, extract_final, length_report
from harness.gates import check_freeze, sign_test_p, summarize, verdict_gate
from harness.judge import JudgeAbort, judge_pair, run
from harness.pairs import build_pairs, pair_id

TASKS = ROOT / "fixtures" / "core"


# ---------- fake judges (deterministic stand-ins) ----------

def oracle_judge(prompt: str) -> str:
    """Reads the fake plans we embed: PLAN A wins when it starts 'GOOD'."""
    a = prompt.split("=== PLAN A ===")[1].strip()
    b = prompt.split("=== PLAN B ===")[1].strip()
    if a.startswith("GOOD") and not b.startswith("GOOD"):
        return "A"
    if b.startswith("GOOD") and not a.startswith("GOOD"):
        return "B"
    return "C"


def position_biased_judge(prompt: str) -> str:
    return "A"  # always favors first slot


def flaky_judge_factory(fail_times: int):
    state = {"n": 0}

    def j(prompt: str) -> str:
        state["n"] += 1
        if state["n"] <= fail_times:
            raise TimeoutError("route down")
        return oracle_judge(prompt)
    return j


def malformed_judge(prompt: str) -> str:
    return "PLAN A is clearly better!!"


def _pair(a: str, b: str, tid: str = "t1") -> dict:
    prompt = (f"=== TASK ===\nbrief\n=== PLAN A ===\n{a}\n=== PLAN B ===\n{b}\n"
              "Answer with exactly one token: A, B, or C.\n")
    return {"pair_id": pair_id(tid, "student", "teacher"), "task_id": tid,
            "arms": {"A": "student", "B": "teacher"}, "prompt": prompt}


# ---------- 1. judge validation vs known-good/known-bad [CRITICAL] ----------

def test_oracle_judge_finds_the_good_plan_8_of_8_seed_pairs():
    """Seed pair set: 4 GOOD-vs-BAD (expect GOOD win) + 4 BAD-vs-GOOD
    (symmetry check). Accuracy must be 100% on the oracle path (>=90% bar)."""
    cases = [("GOOD plan", "BAD plan", "A"), ("BAD plan", "GOOD plan", "B")] * 4
    ok = 0
    for a, b, expected in cases:
        v = judge_pair(_pair(a, b), oracle_judge, retries=1, retry_delay=0)
        ok += v["consistent"] and v["verdict"] == expected
    assert ok == len(cases), "judge validation failed — gates must not run"


def test_position_biased_judge_fails_validation():
    """A fully slot-loyal judge is caught by the consistency check itself:
    it says A in both orders, which maps back to contradictory arms — every
    pair flips, flip-rate = 100%, >> the 20% alarm. The gate never runs on
    its verdicts. (A partially biased judge survives on its consistent
    survivors — which is why validation ALSO checks flip-rate, not only
    survivor accuracy; see test_gate rows alarm_flip below.)"""
    cases = [("GOOD plan", "BAD plan"), ("BAD plan", "GOOD plan")] * 4
    flips = sum(1 for a, b in cases
                if not judge_pair(_pair(a, b), position_biased_judge,
                                  retries=1, retry_delay=0)["consistent"])
    assert flips == 8, "slot-loyal judge must flip the entire seed set"


# ---------- 2. two-pass swap + flip-discard ----------

def test_flip_pairs_discarded_and_counted():
    """Position-loyal judge (always first slot) => the swapped pass maps back
    to the other arm => flip detected and discarded."""
    v = judge_pair(_pair("x", "y"), position_biased_judge, retries=1, retry_delay=0)
    assert v["verdict"] == "FLIP" and v["consistent"] is False


# ---------- 3. judge timeout/malformed: loud abort, never silent partial ----------

def test_malformed_verdict_aborts_loudly():
    with pytest.raises(JudgeAbort):
        judge_pair(_pair("a", "b"), malformed_judge, retries=2, retry_delay=0)


def test_transient_failure_heals_then_scores():
    j = flaky_judge_factory(fail_times=1)
    v = judge_pair(_pair("GOOD a", "BAD b"), j, retries=3, retry_delay=0)
    assert v["consistent"] and v["verdict"] == "A"


def test_run_aborts_before_writing_partial_verdicts(tmp_path):
    out = tmp_path / "verdicts.jsonl"
    pairs = [_pair("GOOD 1", "BAD 1", "t1"), _pair("BAD 2", "GOOD 2", "t2")]
    with pytest.raises(JudgeAbort):
        run(pairs, malformed_judge, out, retries=1)
    assert not out.exists(), "silent partial verdicts are the critical failure mode"


# ---------- 4. contamination: train/eval overlap must raise ----------

def test_freeze_guard_missing_freeze_raises(tmp_path):
    (tmp_path / "core" / "t1").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="not frozen"):
        check_freeze(tmp_path)


def test_freeze_guard_real_repo():
    """check_freeze passes on current frozen fixtures..."""
    h = check_freeze(ROOT / "fixtures")
    assert re.match(r"^[0-9a-f]{64}$", h)


def test_freeze_guard_detects_tampering(tmp_path, monkeypatch):
    """...and raises when a file changes after freeze."""
    import shutil
    fx = tmp_path / "fixtures"
    shutil.copytree(ROOT / "fixtures", fx)
    art = fx / "core" / "suited-architecture" / "artifact.md"
    art.write_text(art.read_text() + "\nTAMPERED\n")
    with pytest.raises(RuntimeError, match="changed after freeze"):
        check_freeze(fx)


# ---------- 5. mining rejects dirty/dup/oversized ----------

def test_core_fixtures_are_clean_and_unique():
    ids, hashes = [], []
    for t in sorted(TASKS.iterdir()):
        exp = json.loads((t / "expect.json").read_text())
        art = (t / "artifact.md").read_text()
        assert len(art) >= 300, f"{t.name} dirty"
        assert exp["task_id"] == t.name
        ids.append(exp["task_id"])
        hashes.append(exp["artifact_sha256"])
    assert len(ids) == len(set(ids)) and len(hashes) == len(set(hashes))
    assert len(ids) >= 6, "core must hold every recoverable real task"


# ---------- 6. source-leak + 7. length parity (D12) ----------

def test_extractor_strips_reasoning_and_role_tells():
    raw = ("<thinking>private CoT 12345</thinking>\n"
           "As the architect of this effort, I declare...\n"
           "Reasoning: because reasons\n"
           "## Final plan\nStep 1: do it")
    out = extract_final(raw)
    assert "private CoT" not in out and "As the architect" not in out
    assert "because reasons" not in out
    assert "Step 1: do it" in out


def test_extractor_caps_length_and_reports():
    long = "x" * (LENGTH_CAP + 500)
    out = extract_final(long)
    assert len(out) <= LENGTH_CAP + 20
    assert length_report(out)["truncated"] is True


def test_gated_prompt_format_is_identical_across_arms():
    """All arms run through extract_final before embedding: no arm can smuggle
    CoT or a role tell into the judged view."""
    arms = {"student": "<thinking>cot</thinking>plan body",
            "teacher": "plan body with equal shape"}
    trimmed = {k: extract_final(v) for k, v in arms.items()}
    pairs = build_pairs(TASKS,
                        {t.name: trimmed for t in TASKS.iterdir() if (t / "expect.json").exists()},
                        seed=7)
    for p in pairs:
        a, b = p["prompt"].split("=== PLAN B ===")[0], p["prompt"].split("=== PLAN B ===")[1]
        assert "<thinking>" not in a and "As the " not in a.lower().replace("as the task", "")


# ---------- 8. significance on tiny n ----------

def test_sign_test_small_n_is_conservative():
    assert sign_test_p(0, 0) == 1.0
    assert sign_test_p(6, 0) < 0.05          # unanimous 6-0 clears alpha
    assert sign_test_p(5, 1) > 0.05          # 5-1 at n=6: honest, not significant
    assert sign_test_p(60, 20) < 0.05        # ring-scale works too


# ---------- 9. tiered gate structure (D14) ----------

def test_gate_rows_carry_per_tier_windows(tmp_path):
    vpath = tmp_path / "verdicts.jsonl"
    rows = []
    for i in range(6):                       # core: student wins all
        rows.append({"pair_id": f"c{i}", "task_id": f"core{i}",
                     "arms": {"A": "student", "B": "teacher"},
                     "forward": "A", "reversed": "A", "consistent": True, "verdict": "A"})
    for i in range(6):                       # ring: teacher wins all
        rows.append({"pair_id": f"r{i}", "task_id": f"ring{i}",
                     "arms": {"A": "teacher", "B": "student"},
                     "forward": "A", "reversed": "A", "consistent": True, "verdict": "A"})
    vpath.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    tiers = {f"core{i}": "core" for i in range(6)} | {f"ring{i}": "ring" for i in range(6)}
    summary = summarize(vpath, tiers)
    assert len(summary) == 1
    row = summary[0]
    res = verdict_gate(row, student="student", baseline="b", teacher="teacher")
    assert res["per_tier"]["core"]["student_winrate"] == 1.0
    assert res["per_tier"]["ring"]["student_winrate"] == 0.0
    # D14 divergence: caller sees both tiers and must adjudicate — the data is
    # reported per tier, never averaged away.
    assert res["per_tier"]["core"]["decided"] == 6 and res["per_tier"]["ring"]["decided"] == 6


def test_flip_alarm_flags_underpowered_judging(tmp_path):
    """4 of 5 pairs flipped => flip_rate 0.8 > FLIP_ALARM => alarm_flip True."""
    vpath = tmp_path / "v.jsonl"
    rows = []
    for i in range(4):
        rows.append({"pair_id": f"f{i}", "task_id": "t",
                     "arms": {"A": "student", "B": "teacher"},
                     "forward": "A", "reversed": "B", "consistent": False, "verdict": "FLIP"})
    rows.append({"pair_id": "k", "task_id": "t",
                 "arms": {"A": "student", "B": "teacher"},
                 "forward": "A", "reversed": "A", "consistent": True, "verdict": "A"})
    vpath.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    row = summarize(vpath, {"t": "core"})[0]
    assert row["flip_rate"] == 0.8 and row["alarm_flip"] is True


# ---------- 10. pairs are blind and order-randomized ----------

def test_pairs_blind_and_seeded_reproducible():
    arms = {t.name: {"student": "plan s", "teacher": "plan t", "baseline": "plan b"}
            for t in TASKS.iterdir() if (t / "expect.json").exists()}
    p1 = build_pairs(TASKS, arms, seed=42)
    p2 = build_pairs(TASKS, arms, seed=42)
    assert [x["pair_id"] for x in p1] == [x["pair_id"] for x in p2]
    assert [x["arms"]["A"] for x in p1] == [x["arms"]["A"] for x in p2]
    for p in p1:
        plans = p["prompt"].split("=== PLAN A ===")[1]
        # arm names must not leak into the judged PLAN sections (briefs may
        # contain ordinary English words like "baseline" — only plans matter)
        assert "student" not in plans and "teacher" not in plans and " plan b" not in plans
    # randomization actually happened (not all-same first arm):
    firsts = {p["arms"]["A"] for p in p1}
    assert len(firsts) > 1
