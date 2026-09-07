"""T4 self-tests — teacher sampler: resume, disjointness, torn-line, abort."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from teacher.sample import chat, check_disjoint, load_eval_index, norm_sha, sample

EVAL_IDX = {"qaida-interfaces": norm_sha("define the module interfaces")}


def _task(tid="syn-a1", brief="build a cache layer", **kw):
    return {"id": tid, "family": "cache", "seed_task_id": "qaida-current-state",
            "brief": brief, **kw}


class FakeCall:
    def __init__(self, fail_first=0, fail_always=False):
        self.n = 0
        self.fail_first = fail_first
        self.fail_always = fail_always

    def __call__(self, key, brief):
        self.n += 1
        if self.fail_always or self.n <= self.fail_first:
            raise TimeoutError("simulated rate-limit kill")
        return {"content": f"PLAN[{brief[:8]}]", "reasoning": "cot", "reasoning_tokens": 5}


def test_sample_writes_per_trace_records(tmp_path):
    rc = sample([_task("s1"), _task("s2")], tmp_path, EVAL_IDX, "k", call=FakeCall())
    assert rc == 0
    lines = (tmp_path / "traces.jsonl").read_text().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["task_id"] == "s1" and rec["plan"].startswith("PLAN")
    assert rec["reasoning"] == "cot" and rec["model"] == "qwen3.8-max"


def test_resume_skips_done_and_keeps_partial(tmp_path):
    """Kill mid-run (transient abort), resume completes the rest — no dupes."""
    first = [_task("r1"), _task("r2"), _task("r3")]
    rc = sample(first[:2], tmp_path, EVAL_IDX, "k", retries=1, retry_delay=0,
                call=FakeCall(fail_always=True))
    assert rc == 1, "must abort loudly on exhausted retries"
    assert not (tmp_path / "traces.jsonl").exists() or \
        (tmp_path / "traces.jsonl").read_text().strip() == ""  # nothing lost: none completed
    # r1 succeeds, r2 kills:
    class OneOkOneDie:
        n = 0
        def __call__(self, key, brief):
            self.n += 1
            if self.n == 1:
                return {"content": "ok1", "reasoning": "", "reasoning_tokens": 0}
            raise TimeoutError("kill")
    rc = sample(first[:2], tmp_path, EVAL_IDX, "k", retries=1, retry_delay=0, call=OneOkOneDie())
    assert rc == 1
    assert (tmp_path / "traces.jsonl").read_text().count("\n") == 1  # r1 checkpointed
    rc = sample(first, tmp_path, EVAL_IDX, "k", retries=2, retry_delay=0, call=FakeCall())
    assert rc == 0
    ids = [json.loads(l)["task_id"] for l in (tmp_path / "traces.jsonl").read_text().splitlines()]
    assert ids == ["r1", "r2", "r3"], f"resume order/dupes wrong: {ids}"


def test_torn_last_line_recovered(tmp_path):
    """A kill mid-write leaves: valid t1 line + torn fragment (no newline).
    Resume must (a) not corrupt the valid record and (b) complete the missing
    task. The torn fragment is garbage — it must not merge with new records."""
    (tmp_path / "traces.jsonl").write_text('{"task_id": "t1", "plan": "p1"}\n{"task_i')
    rc = sample([_task("t1"), _task("t2")], tmp_path, EVAL_IDX, "k", call=FakeCall())
    assert rc == 0
    good = []
    for l in (tmp_path / "traces.jsonl").read_text().splitlines():
        try:
            good.append(json.loads(l)["task_id"])
        except json.JSONDecodeError:
            pass  # the torn fragment, now terminated — survives as unparseable junk
    assert "t1" in good and "t2" in good
    # t1's record intact (not merged with the fragment or t2):
    assert any('"plan": "p1"' in l for l in (tmp_path / "traces.jsonl").read_text().splitlines())


def test_disjointness_refused_before_any_api_spend(tmp_path):
    """Eval-id or normalized-brief collision => refused, zero API calls."""
    call = FakeCall()
    rc = sample([_task("qaida-interfaces", "anything")], tmp_path, EVAL_IDX, "k", call=call)
    assert rc == 2 and call.n == 0, "must refuse by id WITHOUT calling the teacher"
    rc = sample([_task("x9", "define the module interfaces")], tmp_path, EVAL_IDX, "k", call=call)
    assert rc == 2 and call.n == 0, "must refuse on normalized brief-hash collision"
    assert not (tmp_path / "traces.jsonl").read_text().strip(), \
        "refused tasks must write zero records (file may exist empty)"


def test_load_eval_index_reads_real_core_fixtures():
    idx = load_eval_index(ROOT / "fixtures")
    assert "suited-architecture" in idx and idx["suited-architecture"], \
        "frozen core briefs must be hash-indexed"
