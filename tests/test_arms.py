"""G0 arms self-tests — fake transport, no API spend."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arms.run_arms import ARMS, eval_tasks, export_kaggle_tasks, run


def fake_call_factory(once_fail=False, truncated=False):
    state = {"n": 0}

    def call(cfg, brief):
        state["n"] += 1
        if truncated:
            raise ValueError("finish_reason=length: truncated plan")
        if once_fail and state["n"] == 1:
            raise TimeoutError("blip")
        return {"plan": "X" * 400, "reasoning": "r"}
    return call


def test_run_writes_plans_and_is_resumable(tmp_path, monkeypatch):
    monkeypatch.setattr("arms.run_arms.ROOT", tmp_path)
    tasks = [{"task_id": "t1", "tier": "core", "brief": "b1"},
             {"task_id": "t2", "tier": "ring", "brief": "b2"}]
    assert run("teacher", tasks, call=fake_call_factory()) == 0
    d = tmp_path / "arms" / "teacher"
    assert (d / "t1.md").read_text().startswith("XXXX")
    call2 = fake_call_factory()
    assert run("teacher", tasks, call=call2) == 0  # all skipped, 0 calls

def test_transient_failure_retries_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("arms.run_arms.ROOT", tmp_path)
    tasks = [{"task_id": "t1", "tier": "core", "brief": "b"}]
    assert run("teacher", tasks, retry_delay=0,
               call=fake_call_factory(once_fail=True)) == 0


def test_truncation_poison_fails_loud(tmp_path, monkeypatch):
    monkeypatch.setattr("arms.run_arms.ROOT", tmp_path)
    tasks = [{"task_id": "t1", "tier": "core", "brief": "b"}]
    rc = run("teacher", tasks, retries=2, retry_delay=0,
             call=fake_call_factory(truncated=True))
    assert rc == 1
    assert not (tmp_path / "arms" / "teacher" / "t1.md").exists()


def test_eval_tasks_reads_frozen_fixtures():
    tasks = eval_tasks(ROOT / "fixtures")
    tiers = {t["tier"] for t in tasks}
    assert "core" in tiers
    assert len(tasks) >= 12, "6 core + 6 ring must load"


def test_export_kaggle_bundle(tmp_path):
    tasks = eval_tasks(ROOT / "fixtures")
    out = tmp_path / "g0_tasks.jsonl"
    export_kaggle_tasks(tasks, out)
    lines = out.read_text().splitlines()
    assert len(lines) == len(tasks)
    import json
    assert json.loads(lines[0])["task_id"] == tasks[0]["task_id"]


def test_arm_endpoints_pinned():
    assert "token-plan" in ARMS["teacher"]["url"]
    assert ARMS["27b"]["model"] == "Qwen3.8-27B"  # NOT Qwen/... — probe-verified
