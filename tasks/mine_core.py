#!/usr/bin/env python3
"""T2b — mine the REAL planner-task core from PMOS working trees + git history.

Output layout (eval_project.py fixture pattern adapted for plan quality):

  fixtures/core/<task-id>/
    expect.json    {task_id, family, source: real, project, artifact, provenance, brief_sha256}
    brief.md       what the planner was given (charter extract + task framing)
    artifact.md    the real planner output (gold reference for pair construction)

Also writes fixtures/families.json — the FAMILY REGISTRY. Per D14, train-pool
generators may only derive from `train` families; the eval RING must draw from
families marked `ring-only` or newly declared ones that appear nowhere in train.

Recovery: files deleted from working tree are pulled via `git show <commit>:<path>`.
Provenance (commit or working-tree) is recorded — auditable, never assumed.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

FTT = Path(__file__).resolve().parent.parent
FIXTURES = FTT / "fixtures"
CORE = FIXTURES / "core"

# (project, artifact path within repo, task framing for the brief, provenance commit or None=working tree)
# task ids are stable slugs. Families: one per project domain (train-eligible).
TASKS = [
    ("qaida", ".pmos/out/architect/current-state.md",
     "You are the architect. Produce a current-state analysis of the existing codebase: modules, data flow, dependencies, and the constraints a new feature must respect.",
     None, "qaida-chat-app"),
    ("qaida", ".pmos/out/architect/od-resolutions.md",
     "You are the architect. Resolve the open design questions for the chat feature: pick resolutions, justify each against existing constraints, list rejected alternatives.",
     None, "qaida-chat-app"),
    ("qaida", ".pmos/out/architect/interfaces.md",
     "You are the architect. Define the module interfaces for the chat feature: function signatures, data shapes, ownership boundaries between client and storage.",
     "0841869", "qaida-chat-app"),
    ("qaida", ".pmos/out/architect/vocab-delta-plan.md",
     "You are the architect. Plan the vocabulary-migration delta: what changes, in what order, with what compatibility guarantees.",
     "0841869", "qaida-chat-app"),
    ("suited", ".pmos/out/planner/current-state.md",
     "You are the planner. Produce a current-state analysis of the collection pipeline: what runs today, what data exists, what the site-report wedge must reuse.",
     None, "suited-site-prediction"),
    ("suited", ".pmos/out/planner/architecture.md",
     "You are the planner. Design the architecture for the site-report wedge: components, data flow, failure handling, the smallest buildable version.",
     None, "suited-site-prediction"),
]


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_artifact(project: str, rel: str, commit: str | None) -> tuple[bytes, str]:
    repo = Path.home() / project
    if commit:
        r = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{rel}"],
                           capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(f"git show failed for {project}:{rel}@{commit}: {r.stderr[:200]}")
        return r.stdout, f"git:{commit}"
    p = repo / rel
    if not p.exists():
        raise RuntimeError(f"missing working-tree artifact {p}")
    return p.read_bytes(), "working-tree"


def read_charter(project: str) -> str:
    p = Path.home() / project / ".pmos" / "charter.md"
    return p.read_text(errors="replace") if p.exists() else ""


def main() -> int:
    CORE.mkdir(parents=True, exist_ok=True)
    families: dict[str, dict] = {}
    written, skipped = [], []
    for project, rel, framing, commit, family in TASKS:
        task_id = f"{project}-{Path(rel).stem}"
        d = CORE / task_id
        try:
            raw, prov = read_artifact(project, rel, commit)
        except RuntimeError as e:
            skipped.append({"task_id": task_id, "reason": str(e)})
            continue
        if len(raw) < 300:
            skipped.append({"task_id": task_id, "reason": "artifact below 300B floor (dirty)"})
            continue
        charter = read_charter(project)
        brief = (f"# Task: {Path(rel).stem}\n\n## Framing\n{framing}\n\n"
                 f"## Project charter (input context)\n\n{charter}\n")
        d.mkdir(exist_ok=True)
        (d / "artifact.md").write_bytes(raw)
        (d / "brief.md").write_text(brief)
        expect = {
            "task_id": task_id,
            "family": family,
            "source": "real",
            "project": project,
            "artifact_rel": rel,
            "provenance": prov,
            "artifact_sha256": sha256(raw),
            "brief_sha256": sha256(brief.encode()),
        }
        (d / "expect.json").write_text(json.dumps(expect, indent=2) + "\n")
        written.append(task_id)
        f = families.setdefault(family, {"usage": "train", "projects": set()})
        f["projects"].add(project)

    fam_out = {k: {"usage": v["usage"], "projects": sorted(v["projects"])} for k, v in families.items()}
    fam_out["_rule"] = {
        "rule": ("train pool derives ONLY from families listed here; eval ring must use "
                 "families absent from the train generation run (D14 family-disjointness)")
    }
    (FIXTURES / "families.json").write_text(json.dumps(fam_out, indent=2) + "\n")

    report = {"written": written, "skipped": skipped, "core_n": len(written)}
    (FIXTURES / "inventory-core.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
