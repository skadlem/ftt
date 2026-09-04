"""Judge invocation: two-pass order-swap, flip-discard, verdict store.

judge callable: (prompt: str) -> "A" | "B" | "C" — may raise.
Production wires this to the non-Qwen route (glm/kimi); tests inject fakes.

Semantics per design doc (D4/D9/D12):
  - every pair judged forward and reversed
  - verdicts that disagree after undoing the swap => FLIP, discarded (counted)
  - agreement => the verdict; malformed/timeout after retries => ABORT_RUN
    (a partial verdict set must never be scored — silent partials are the
    documented critical failure mode)
"""
import json
import time
from collections import Counter
from pathlib import Path


class JudgeAbort(RuntimeError):
    pass


def _swap(prompt: str, task: str) -> str:
    """Return the same prompt with PLAN A and PLAN B bodies exchanged."""
    i1, i2 = prompt.index("=== PLAN A ==="), prompt.index("=== PLAN B ===")
    i3 = prompt.index("Answer with exactly one token")
    a = prompt[i1 + len("=== PLAN A ==="):i2]
    b = prompt[i2 + len("=== PLAN B ==="):i3]
    return prompt[:i1 + len("=== PLAN A ===")] + b + "=== PLAN B ===" + a + prompt[i3:]


def _flip(v: str) -> str:
    return {"A": "B", "B": "A"}.get(v, v)


def _validate(raw: str) -> str:
    t = (raw or "").strip().upper()
    if t not in {"A", "B", "C"}:
        raise ValueError(f"malformed verdict: {raw!r}")
    return t


def judge_pair(pair: dict, judge, retries: int = 3, retry_delay: float = 1.0) -> dict:
    fw = rv = None
    last_err = None
    for _ in range(retries):
        try:
            fw = _validate(judge(pair["prompt"]))
            rv = _validate(judge(_swap(pair["prompt"], pair["task_id"])))
            last_err = None
            break  # success: clear any prior error so a healed pair is NOT aborted
        except Exception as e:  # noqa: BLE001 — transport-agnostic
            last_err = e
            time.sleep(retry_delay)
    if last_err is not None or fw is None or rv is None:
        raise JudgeAbort(f"pair {pair['pair_id']} failed after {retries} retries: {last_err}")
    consistent = (_flip(rv) == fw)
    return {"pair_id": pair["pair_id"], "task_id": pair["task_id"],
            "arms": pair["arms"], "forward": fw, "reversed": rv,
            "consistent": consistent, "verdict": fw if consistent else "FLIP"}


def run(pairs: list[dict], judge, out_path: Path, retries: int = 3) -> dict:
    """Judge all pairs; write verdicts JSONL; return summary. ABORT on any
    pair that cannot be judged (no silent partials)."""
    verdicts = []
    for p in pairs:
        verdicts.append(judge_pair(p, judge, retries=retries))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(json.dumps(v) for v in verdicts) + "\n")
    n = len(verdicts)
    flips = sum(1 for v in verdicts if not v["consistent"])
    return {"n_pairs": n, "n_flips": flips, "flip_rate": flips / n if n else 0.0,
            "verdicts": str(out_path)}
