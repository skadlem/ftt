#!/usr/bin/env python3
"""T2b — freeze the eval core: sha256 every fixture file into freeze.json.

Gates (harness/gates.py) refuse to run unless the current fixtures hash-match
this freeze. Additive-only: core tasks may be ADDED before a freeze refresh,
never mutated or removed, so G0 and G1 always compare against the same set.
"""
import hashlib
import json
import sys
from pathlib import Path

FTT = Path(__file__).resolve().parent.parent
FIXTURES = FTT / "fixtures"
GLOB = ["core/**/*.md", "core/**/*.json", "ring/**/*.md", "ring/**/*.json"]


def hash_tree() -> dict[str, str]:
    out = {}
    for pat in GLOB:
        for p in sorted(FIXTURES.glob(pat)):
            out[str(p.relative_to(FIXTURES))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main() -> int:
    files = hash_tree()
    if not files:
        print("ERROR: nothing to freeze", file=sys.stderr)
        return 1
    freeze = FIXTURES / "freeze.json"
    prev = json.loads(freeze.read_text()) if freeze.exists() else None
    if prev:
        def ids_of(filemap: dict[str, str]) -> set[str]:
            return {json.loads((FIXTURES / f).read_text())["task_id"]
                    for f in filemap if f.endswith("expect.json")}
        removed = ids_of(prev["files"]) - ids_of(files)
        if removed:
            print(f"ERROR: freeze is additive-only; refusing to drop tasks: {sorted(removed)}",
                  file=sys.stderr)
            return 2
    doc = {"frozen_at": "2026-09-04", "files": files,
           "aggregate_sha256": hashlib.sha256(
               "\n".join(f"{k}:{v}" for k, v in sorted(files.items())).encode()).hexdigest()}
    freeze.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"froze {len(files)} files, aggregate {doc['aggregate_sha256'][:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
