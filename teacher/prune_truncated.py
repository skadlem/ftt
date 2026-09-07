"""Audit + prune truncated teacher traces (old 8000-cap survivors)."""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
keep, drop = [], []
for r in lines:
    p = r["plan"].rstrip()
    truncated = r.get("finish_reason") == "length" or (
        "finish_reason" not in r and len(p) > 30000
        and not p.endswith((".", ")", "!", "?", "`")))
    (drop if truncated else keep).append(r["task_id"])
path.write_text("".join(
    json.dumps(r) + "\n" for r in lines if r["task_id"] not in drop))
print(f"kept: {keep}\ndropped: {drop}")
