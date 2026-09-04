"""Build blind comparison pairs from arms + frozen fixtures.

Pair = (task_id, arm_a_plan, arm_b_plan) with provenance (which arm is which)
held ONLY in the sidecar; the judge prompt sees no ids, no styles, no order
hints. Order is randomized with a pinned seed so a run is reproducible and
auditable (two-pass swap re-uses the pair, order reversed).
"""
import hashlib
import json
import random
from pathlib import Path

BLIND_PROMPT = """You are comparing two plans for the same software task.
Judge ONLY plan quality: correctness of decomposition, identification of real
constraints, risks surfaced, feasibility, and testability of the plan.
Do not reward length, confidence, or style. If they are equally good or
equally bad, answer C.

=== TASK ===
{brief}

=== PLAN A ===
{a}

=== PLAN B ===
{b}

Answer with exactly one token: A, B, or C.
"""


def pair_id(task_id: str, arm_a: str, arm_b: str) -> str:
    return hashlib.sha256(f"{task_id}|{arm_a}|{arm_b}".encode()).hexdigest()[:16]


def build_pairs(tasks_dir: Path, arms: dict[str, dict[str, str]],
                seed: int) -> list[dict]:
    """tasks_dir: fixtures/core. arms: {task_id: {arm_name: plan_text}}.
    Produces every unordered arm-vs-arm comparison for each task once
    (baseline-vs-teacher and baseline-vs-student; teacher-vs-student too).
    Returns pair records with the blind prompt and the sidecar mapping."""
    rng = random.Random(seed)
    pairs = []
    for task in sorted(tasks_dir.iterdir()):
        if not (task / "expect.json").exists():
            continue
        tid = task.name
        brief = (task / "brief.md").read_text()
        names = sorted(n for n in arms.get(tid, {}) if arms[tid][n].strip())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                pa, pb = arms[tid][a], arms[tid][b]
                first, second = (a, b) if rng.random() < 0.5 else (b, a)
                fp, sp = (pa, pb) if (first, second) == (a, b) else (pb, pa)
                pairs.append({
                    "pair_id": pair_id(tid, a, b),
                    "task_id": tid,
                    "arms": {"A": first, "B": second},
                    "prompt": BLIND_PROMPT.format(brief=brief, a=fp, b=sp),
                })
    return pairs


def write_pairs(pairs: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pairs.jsonl").write_text(
        "\n".join(json.dumps(p) for p in pairs) + "\n")
