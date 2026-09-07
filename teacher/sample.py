#!/usr/bin/env python3
"""T4 — qwen3.8-max teacher trace sampler (resumable, disjointness-guarded).

Route probe 2026-09-04: OpenAI-compatible chat/completions at
https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
emits `message.reasoning_content` (separate from `content`) +
reasoning_tokens in usage — reasoning-inclusive traces are REAL here.

Design-doc rules encoded:
  - checkpoint per trace: traces.jsonl append + flush after EVERY trace, so a
    rate-limit kill or crash never loses completed work (resume skips done ids)
  - write-time disjointness: a task whose id or brief-hash collides with the
    frozen eval set (core + ring) is refused BEFORE any API call is spent
  - family provenance recorded (family, seed_task_id) — auditable train/ring split
  - transient transport errors: retry with backoff; exhausted => exit non-zero
    loudly, partial file kept (resume continues)

API key from env: QWEN_TOKEN_PLAN_API_KEY (never logged, never stored).

Usage:
  python3 teacher/sample.py --tasks train_tasks.jsonl --out traces/
  python3 teacher/sample.py --tasks train_tasks.jsonl --out traces/ --resume
Tasks JSONL lines: {"id": str, "family": str, "seed_task_id": str, "brief": str}
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3.8-max"
SYSTEM = ("You are the planner in a multi-agent software team. Given a task "
          "brief, produce a complete implementation plan: decomposition into "
          "steps, ordering and dependencies, risks with mitigations, and a "
          "testability check per step. Be concrete about files and interfaces.")


def norm_sha(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()


def load_eval_index(fixtures_dir: Path) -> dict[str, str]:
    """id -> brief_hash for frozen eval tasks (core + ring if present)."""
    idx = {}
    for sub in ("core", "ring"):
        for exp in (fixtures_dir / sub).glob("*/expect.json") if (fixtures_dir / sub).is_dir() else []:
            d = json.loads(exp.read_text())
            brief = exp.parent / "brief.md"
            idx[d["task_id"]] = norm_sha(brief.read_text()) if brief.exists() else ""
    return idx


def check_disjoint(task: dict, eval_idx: dict[str, str]) -> str | None:
    if task["id"] in eval_idx:
        return f"id collision with eval task {task['id']}"
    h = norm_sha(task["brief"])
    for eid, eh in eval_idx.items():
        if eh and eh == h:
            return f"brief-hash collision with eval task {eid}"
    return None


def chat(api_key: str, brief: str, timeout: float = 300.0,
         max_tokens: int = 8000) -> dict:
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": brief}],
        "max_tokens": max_tokens,
        "temperature": 0.6,
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed host)
        resp = json.loads(r.read())
    msg = resp["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or "").strip()
    if not content:
        raise ValueError("empty content from teacher")
    usage = resp.get("usage", {})
    return {"content": content, "reasoning": reasoning,
            "reasoning_tokens": usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)}


def sample(tasks: list[dict], out_dir: Path, eval_idx: dict[str, str],
           api_key: str, retries: int = 4, retry_delay: float = 5.0,
           call=chat) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    traces_path = out_dir / "traces.jsonl"
    done = set()
    if traces_path.exists():
        for line in traces_path.read_text().splitlines():
            try:
                done.add(json.loads(line)["task_id"])
            except json.JSONDecodeError:
                pass  # torn final line from a kill — ignored, task will resample
    n_ok = n_refused = 0
    with traces_path.open("a") as fh:
        # kill-proof resume: a torn last line (no newline) must be terminated
        # BEFORE appending, or the new record merges into garbage and corrupts
        # a completed trace.
        if traces_path.exists() and traces_path.stat().st_size > 0:
            with traces_path.open("rb") as rb:
                rb.seek(-1, 2)
                if rb.read(1) != b"\n":
                    fh.write("\n")
        for t in tasks:
            if t["id"] in done:
                continue
            clash = check_disjoint(t, eval_idx)
            if clash:
                print(f"REFUSED {t['id']}: {clash}", file=sys.stderr)
                n_refused += 1
                continue
            err = None
            for attempt in range(retries):
                try:
                    r = call(api_key, t["brief"])
                    rec = {"task_id": t["id"], "family": t.get("family", ""),
                           "seed_task_id": t.get("seed_task_id", ""),
                           "model": MODEL, "plan": r["content"],
                           "reasoning": r["reasoning"],
                           "reasoning_tokens": r["reasoning_tokens"]}
                    fh.write(json.dumps(rec) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())  # kill-proof: durable per trace
                    n_ok += 1
                    err = None
                    break
                except (urllib.error.URLError, urllib.error.HTTPError,
                        ValueError, TimeoutError, json.JSONDecodeError) as e:
                    err = e
                    time.sleep(retry_delay * (2 ** attempt))
            if err is not None:
                print(f"ABORT: {t['id']} failed after {retries} attempts: {err}",
                      file=sys.stderr)
                print("partial traces kept; re-run with --resume", file=sys.stderr)
                return 1
    print(f"sampled={n_ok} skipped={len(done)} refused={n_refused} out={traces_path}")
    return 0 if n_refused == 0 else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--fixtures", type=Path,
                    default=Path(__file__).resolve().parent.parent / "fixtures")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)
    key = os.environ.get("QWEN_TOKEN_PLAN_API_KEY", "")
    if not key:
        print("ERROR: QWEN_TOKEN_PLAN_API_KEY not in env", file=sys.stderr)
        return 3
    tasks = [json.loads(l) for l in args.tasks.read_text().splitlines() if l.strip()]
    if args.limit:
        tasks = tasks[: args.limit]
    return sample(tasks, args.out, load_eval_index(args.fixtures), key)


if __name__ == "__main__":
    sys.exit(main())
