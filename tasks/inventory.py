#!/usr/bin/env python3
"""Inventory real PMOS planner tasks across project .pmos trees.

Outside-voice finding (2026-09-04): the plan assumed ~250 minable tasks; disk
shows only a handful of real planner artifacts. This script is the hard count
BEFORE anything freezes — the output gates whether the eval set can be real.

Candidate sources per project .pmos tree:
  - charter.md            -> the project brief the planner received (task input)
  - out/planner/*.md      -> planner outputs (architecture.md, current-state.md)
  - out/architect/*.md    -> qaida's architect-role equivalent
  - decisions/ADR-*.md    -> plan-outcome decision records (context, not tasks)
  - plans/plan.md         -> approved plan artifact

A "task" = (charter/brief as input, planner artifact as the real output).
Counts tasks per project, flags dirty (empty/placeholder) candidates.
"""
import json
import sys
from pathlib import Path

HOME = Path.home()
PMOS_ROOTS = sorted(HOME.glob("*/.pmos"))  # depth-limited: ~/projects/*//.pmos

MIN_BRIEF_BYTES = 200      # a charter smaller than this is a stub, not a brief
MIN_ARTIFACT_BYTES = 300   # planner output below this is a placeholder


def classify(p: Path):
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"path": str(p), "bytes": 0, "dirty": True, "reason": "unreadable"}
    b = len(text.encode())
    dirty = b < (MIN_BRIEF_BYTES if p.name == "charter.md" else MIN_ARTIFACT_BYTES)
    return {"path": str(p), "bytes": b, "dirty": dirty, "reason": "" if not dirty else "below size floor"}


def inventory_one(root: Path):
    charter = root / "charter.md"
    outs = sorted((root / "out").glob("*/[ac]*.md")) + sorted((root / "out").glob("*/*.md"))
    # dedupe, keep planner/architect role dirs only
    role_dirs = {"planner", "architect"}
    outs = sorted({p for p in (root / "out").glob("*/*.md") if p.parent.name in role_dirs})
    decisions = sorted((root / "decisions").glob("ADR-*.md"))
    plans = sorted((root / "plans").glob("*.md"))
    return {
        "project": root.parent.name,
        "root": str(root),
        "brief": classify(charter) if charter.exists() else None,
        "planner_outputs": [classify(p) for p in outs],
        "decisions": [str(p) for p in decisions],
        "plans": [classify(p) for p in plans],
    }


def main():
    trees = [r for r in PMOS_ROOTS if r.is_dir()]
    rows = [inventory_one(r) for r in trees]
    real_tasks = 0
    for row in rows:
        usable_outputs = [o for o in row["planner_outputs"] if not o["dirty"]]
        has_brief = row["brief"] is not None and not row["brief"]["dirty"]
        n = len(usable_outputs) if has_brief else 0
        # each planner output pairs with the one brief: tasks = outputs when brief ok
        real_tasks += n
        print(f"\n== {row['project']} ==")
        print(f"  brief: {'OK' if has_brief else 'MISSING/DIRTY'}")
        for o in row["planner_outputs"]:
            tag = "dirty" if o["dirty"] else f"{o['bytes']}B"
            print(f"  out: {Path(o['path']).parent.name}/{Path(o['path']).name} ({tag})")
        print(f"  decisions: {len(row['decisions'])} ADRs | plans: {len(row['plans'])}")
        print(f"  => extractable tasks: {n}")
    print(f"\nTOTAL REAL TASKS: {real_tasks}")
    print(f"POWER VERDICT: {'<30 — record constraint on G0/G1 power (per plan step 1)' if real_tasks < 30 else '>=30 — real eval set feasible as designed'}")
    out = Path(__file__).resolve().parent.parent / "fixtures" / "inventory-2026-09-04.json"
    out.write_text(json.dumps({"as_of": "2026-09-04", "total_real_tasks": real_tasks, "rows": rows}, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
