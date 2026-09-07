#!/usr/bin/env python3
"""G0 orchestration — assemble arms, pair blind, judge live, report per tier.

Prereq (background jobs):
  arms/teacher/<task_id>.md   (API arm, running)
  arms/27b/<task_id>.md       (API arm, running)
  arms/kaggle-8b/<task_id>.md (you run train/kaggle_infer.py MODE=baseline,
                               drop results back in)

Then:
  python3 arms/run_g0.py                 # checks completeness, pairs, judges
  python3 arms/run_g0.py --dry           # build pairs only (no judge spend)

Judge: harness.judge_client.make_live_judge (glm-5.2, non-Qwen vs teacher).
Output: reports/g0-<ts>/{pairs.jsonl,verdicts.jsonl,report.json}
Gate read-out (design doc G0): teacher vs 8B-baseline win-rate, per tier;
alarm if flip-rate >20%; refuses on unfrozen/tampered fixtures.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arms.run_arms import eval_tasks  # noqa: E402
from harness.gates import check_freeze, summarize  # noqa: E402
from harness.judge import JudgeAbort, run as judge_run  # noqa: E402
from harness.pairs import build_pairs  # noqa: E402

ARMS = ("teacher", "27b", "kaggle-8b")


def collect_arms(tasks: list[dict]) -> tuple[dict, list[str]]:
    arms, missing = {}, []
    for t in tasks:
        for name in ARMS:
            f = ROOT / "arms" / name / f"{t['task_id']}.md"
            if f.exists() and f.stat().st_size > 300:
                arms.setdefault(t["task_id"], {})[name] = f.read_text()
            else:
                missing.append(f"{name}/{t['task_id']}")
    return arms, missing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="pairs only, no judge")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--retries", type=int, default=3)
    args = ap.parse_args(argv)

    agg = check_freeze(ROOT / "fixtures")  # raises if tampered/unfrozen
    tasks = eval_tasks(ROOT / "fixtures")
    tiers = {t["task_id"]: t["tier"] for t in tasks}
    arms, missing = collect_arms(tasks)
    if missing:
        print(f"INCOMPLETE arms ({len(missing)} missing): {missing[:6]} …",
              file=sys.stderr)
        print("wait for feeders / run kaggle_infer for kaggle-8b; nothing judged.",
              file=sys.stderr)
        return 2
    out = ROOT / "reports" / f"g0-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True)
    pairs = build_pairs(ROOT / "fixtures" / "core", arms, seed=args.seed)
    # ring tasks live in fixtures/ring — build_pairs scans one dir; include them:
    pairs += build_pairs(ROOT / "fixtures" / "ring", arms, seed=args.seed)
    (out / "pairs.jsonl").write_text("\n".join(json.dumps(p) for p in pairs) + "\n")
    print(f"pairs: {len(pairs)} | freeze: {agg[:12]}… -> {out/'pairs.jsonl'}")
    if args.dry:
        return 0

    from harness.judge_client import make_live_judge
    try:
        summary = judge_run(pairs, make_live_judge(), out / "verdicts.jsonl",
                            retries=args.retries)
    except JudgeAbort as e:
        print(f"JUDGE ABORT (no partials scored): {e}", file=sys.stderr)
        return 1
    rows = summarize(out / "verdicts.jsonl", tiers)
    report = {"aggregate_freeze": agg, "summary": summary, "rows": rows,
              "n_tasks": len(tasks)}
    (out / "report.json").write_text(json.dumps(report, indent=2))
    for r in rows:
        a, b = r["arms"]
        print(f"{a} vs {b}: winrate_a={r['winrate_a']:.2f} "
              f"W-L-T={r['wins_a']}-{r['wins_b']}-{r['ties']} "
              f"p={r['p_sign']:.3f} flips={r['flips']} alarm={r['alarm_flip']}")
        for tier in ("core", "ring"):
            t = r["tiers"][tier]
            print(f"   {tier}: {t['wins_a']}-{t['wins_b']}-{t['ties']}")
    print(f"report -> {out/'report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
