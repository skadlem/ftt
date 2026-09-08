#!/usr/bin/env python3
"""G0 arms — generate plan text per eval task per API arm (teacher, 27B).

Writes arms/<arm>/<task_id>.md (skips existing = resumable). 8B baseline is
NOT here: it runs on Kaggle; --export-kaggle-tasks writes the task bundle the
notebook consumes, and results land back in arms/kaggle-8b/<task_id>.md.

Arms config (verified live 2026-09-07):
  teacher  qwen3.8-max @ token-plan   (reasoning_content field; 16k cap)
  27b      Qwen3.8-27B @ Hetzner      (reasoning field; needs generous max_tokens)
Both gated by finish_reason != length (same truncation poison rule as sampler).
"""
import argparse
import json
import os
import random
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.retry import backoff_sleep  # noqa: E402

PLAN_SYSTEM = ("You are the planner in a multi-agent software team. Given a task "
               "brief, produce a complete implementation plan: decomposition into "
               "steps, ordering and dependencies, risks with mitigations, and a "
               "testability check per step. Be concrete about files and interfaces.")

ARMS = {
    "teacher": {
        "url": "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
        "key_env": "QWEN_TOKEN_PLAN_API_KEY", "model": "qwen3.8-max",
        "max_tokens": 16000, "extra": {},
    },
    "27b": {
        "url": "https://inference.hetzner.com/api/v1/chat/completions",
        "key_env": "HETZNER_API_KEY", "model": "Qwen3.8-27B",
        "max_tokens": 16000, "extra": {},
    },
}


def call_arm(cfg: dict, brief: str, timeout: float = 600.0) -> dict:
    body = json.dumps({"model": cfg["model"],
                       "messages": [{"role": "system", "content": PLAN_SYSTEM},
                                    {"role": "user", "content": brief}],
                       "max_tokens": cfg["max_tokens"],
                       "temperature": 0.2,   # baselines: deterministic-ish
                       **cfg.get("extra", {})}).encode()
    req = urllib.request.Request(cfg["url"], data=body,
                                 headers={"Authorization": f"Bearer {os.environ[cfg['key_env']]}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        resp = json.loads(r.read())
    ch0 = resp["choices"][0]
    msg = ch0.get("message") or {}
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
    if not content:
        raise ValueError(f"empty content (finish={ch0.get('finish_reason')})")
    if ch0.get("finish_reason") == "length":
        raise ValueError("finish_reason=length: truncated plan")
    return {"plan": content, "reasoning": reasoning}


def eval_tasks(fixtures_dir: Path) -> list[dict]:
    out = []
    for sub in ("core", "ring"):
        for d in sorted((fixtures_dir / sub).glob("*")):
            if (d / "expect.json").exists():
                out.append({"task_id": d.name,
                            "tier": sub,
                            "brief": (d / "brief.md").read_text()})
    return out


def export_kaggle_tasks(tasks: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(t) for t in tasks) + "\n")


def run(arm: str, tasks: list[dict], retries: int = 3, retry_delay: float = 10.0,
        jitter: tuple[float, float] | None = (15.0, 45.0),
        call=call_arm) -> int:
    cfg = ARMS[arm]
    out_dir = ROOT / "arms" / arm
    out_dir.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    failed: list[str] = []
    for t in tasks:
        f = out_dir / f"{t['task_id']}.md"
        if f.exists() and f.stat().st_size > 300:
            continue  # resumable
        err = None
        for attempt in range(retries):
            try:
                r = call(cfg, t["brief"])
                tmp = f.with_suffix(".tmp")
                tmp.write_text(r["plan"])
                os.replace(tmp, f)  # atomic: never a half-written arm plan
                n_ok += 1
                err = None
                break
            except Exception as e:  # noqa: BLE001
                err = e
                backoff_sleep(e, attempt, retry_delay)
        if err is not None:
            # one dead task must not block the other 11; the wrapper re-runs,
            # resume skips completed files
            print(f"FAIL {arm}/{t['task_id']} after {retries} tries: {err}",
                  file=sys.stderr)
            failed.append(t["task_id"])
            continue
        if jitter:  # don't hammer a flaky route
            time.sleep(random.uniform(*jitter))
    if failed:
        print(f"failed this pass: {failed}; re-run to retry", file=sys.stderr)
        return 1
    print(f"arm={arm} generated={n_ok} skipped={len(tasks)-n_ok}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=list(ARMS))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--export-kaggle-tasks", type=Path, default=None)
    args = ap.parse_args(argv)
    tasks = eval_tasks(ROOT / "fixtures")
    if args.export_kaggle_tasks:
        export_kaggle_tasks(tasks, args.export_kaggle_tasks)
        print(f"kaggle task bundle: {args.export_kaggle_tasks} ({len(tasks)} tasks)")
        return 0
    if args.limit:
        tasks = tasks[: args.limit]
    return run(args.arm, tasks)


if __name__ == "__main__":
    sys.exit(main())
