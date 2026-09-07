#!/usr/bin/env python3
"""T2c/T4b — generate task briefs for the eval RING and the TRAIN pool.

Two modes, one teacher route (qwen3.8-max, OpenAI-compatible):

  --mode ring  fixtures/ring/<id>/{brief.md,expect.json}
      New families only (must NOT appear in families.json train registry).
      D14: ring is family-disjoint from the train pool by construction.
  --mode train --out tasks/train_pool.jsonl
      Variants of REAL core seeds, tagged with the seed's family. Colliding
      with any frozen eval brief (core or ring) is refused before writing.

Every brief passes: length window, normalized-hash dedupe vs eval index and
vs the batch, and family rules. Teacher call injectable for tests.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from teacher.sample import BASE_URL, MODEL, norm_sha, load_eval_index  # noqa: E402

LEN_MIN, LEN_MAX = 400, 4000

RING_PROMPT = ("Generate {n} distinct, realistic software-project task briefs for the "
               "domain family '{family}'. Each brief: 800-2500 characters, self-contained "
               "(context, goal, constraints, what exists already), written to a planner "
               "agent as a user request. Families must differ from each other. Reply "
               "ONLY with a JSON array of {n} strings, no commentary.")

TRAIN_PROMPT = ("You are expanding a training task pool for a software planner. Below is "
                "a REAL project brief (truncated) from family '{family}'. Generate {n} NEW "
                "task briefs in the SAME family: similar software structure and planning "
                "challenges, but different product, features, and constraints. Each 800-"
                "2500 characters, self-contained. Do NOT restate or lightly reword the "
                "given brief. Reply ONLY with a JSON array of {n} strings.\n\n--- seed "
                "brief (truncated) ---\n{seed}")


def parse_json_array(text: str) -> list:
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"\[[\s\S]*\]", t)
    if not m:
        raise ValueError(f"no JSON array in reply: {text[:120]!r}")
    arr = json.loads(m.group(0))
    if not isinstance(arr, list) or not arr:
        raise ValueError("empty/non-list array")
    return arr


def call_teacher(api_key: str, prompt: str, timeout: float = 240.0) -> str:
    import urllib.request
    body = json.dumps({"model": MODEL,
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": 4000, "temperature": 0.9}).encode()
    req = urllib.request.Request(f"{BASE_URL}/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {api_key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read())["choices"][0]["message"]["content"]


def train_families() -> dict:
    reg = json.loads((ROOT / "fixtures" / "families.json").read_text())
    return {k: v for k, v in reg.items() if k != "_rule"}


def validate_briefs(raws: list, eval_idx: dict, seen: set, family_rule) -> list[dict]:
    out = []
    for item in outs_iter(raws):
        brief, fam = item
        brief = brief.strip()
        if not (LEN_MIN <= len(brief) <= LEN_MAX):
            print(f"REFUSE {fam}: length {len(brief)} outside [{LEN_MIN},{LEN_MAX}]",
                  file=sys.stderr)
            continue
        h = norm_sha(brief)
        if h in eval_idx.values():
            print(f"REFUSE {fam}: collides with frozen eval brief", file=sys.stderr)
            continue
        if h in seen:
            print(f"REFUSE {fam}: duplicate within batch", file=sys.stderr)
            continue
        err = family_rule(fam, brief)
        if err:
            print(f"REFUSE {fam}: {err}", file=sys.stderr)
            continue
        seen.add(h)
        out.append({"family": fam, "brief": brief})
    return out


def outs_iter(raws: list):
    for item in raws:
        if isinstance(item, dict):
            yield item.get("brief", ""), item.get("family", "?")
        else:
            yield str(item), None


def gen(api_key, prompt, family_default, call=call_teacher) -> list:
    arr = parse_json_array(call(api_key, prompt))
    return [(it.get("brief", "") if isinstance(it, dict) else str(it),
             (it.get("family") if isinstance(it, dict) else None) or family_default)
            for it in arr]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["ring", "train"])
    ap.add_argument("--families", default="", help="comma list (ring mode)")
    ap.add_argument("--per-family", type=int, default=2)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    key = os.environ.get("QWEN_TOKEN_PLAN_API_KEY", "")
    if not key:
        print("ERROR: QWEN_TOKEN_PLAN_API_KEY not in env", file=sys.stderr)
        return 3
    eval_idx = load_eval_index(ROOT / "fixtures")
    seen: set[str] = set()
    tf = train_families()

    if args.mode == "ring":
        fams = [f.strip() for f in args.families.split(",") if f.strip()]
        overlap = set(fams) & set(tf)
        if overlap:
            print(f"ERROR: ring families must be absent from train registry: {overlap}",
                  file=sys.stderr)
            return 2
        ring_dir = ROOT / "fixtures" / "ring"
        ring_dir.mkdir(exist_ok=True)
        written = 0
        for fam in fams:
            pairs = gen(key, RING_PROMPT.format(n=args.per_family, family=fam), fam)
            vals = validate_briefs([{"brief": b, "family": f} for b, f in pairs],
                                   eval_idx, seen,
                                   lambda f, b: None if f == fam else f"tag {f} != ring family {fam}")
            for v in vals:
                tid = f"ring-{fam}-{written:02d}"
                d = ring_dir / tid
                d.mkdir(exist_ok=True)
                (d / "brief.md").write_text(v["brief"] + "\n")
                (d / "expect.json").write_text(json.dumps({
                    "task_id": tid, "family": fam, "source": "synthetic-ring",
                    "brief_sha256": hashlib.sha256((v["brief"] + "\n").encode()).hexdigest(),
                }, indent=2) + "\n")
                eval_idx[tid] = norm_sha(v["brief"] + "\n")  # later briefs can't copy it
                written += 1
        print(f"ring tasks written: {written}")
        return 0

    # train mode: variants of real seeds
    seeds = []
    for exp in sorted((ROOT / "fixtures" / "core").glob("*/expect.json")):
        d = json.loads(exp.read_text())
        seeds.append((d["task_id"], d["family"],
                      (exp.parent / "brief.md").read_text()[:1500]))
    pool_path = args.out or (ROOT / "tasks" / "train_pool.jsonl")
    existing = ([json.loads(l)["id"] for l in pool_path.read_text().splitlines()]
                if pool_path.exists() else [])
    n = 0
    with pool_path.open("a") as fh:
        for seed_id, fam, seed_text in seeds:
            pairs = gen(key, TRAIN_PROMPT.format(n=args.per_family, family=fam,
                                                 seed=seed_text), fam)
            def rule(f, b, fam=fam):
                return None if f == fam else f"variant tagged {f}, seed family {fam}"
            for v in validate_briefs([{"brief": b, "family": f} for b, f in pairs],
                                     eval_idx, seen, rule):
                tid = f"syn-{fam}-{n:02d}"
                fh.write(json.dumps({"id": tid, "family": fam, "seed_task_id": seed_id,
                                     "brief": v["brief"]}) + "\n")
                n += 1
    print(f"train tasks written: {n} (total {len(existing) + n}) -> {pool_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
