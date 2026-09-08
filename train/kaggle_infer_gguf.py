"""Kaggle-side inference — 8B baseline arm AND future student arm, GGUF path.

Why GGUF and not transformers: the full Qwen3.5-9B bf16 is 4 shards / ~19GB,
over Kaggle /kaggle/working disk once env + outputs are counted. The Q4_K_M
GGUF is ~5.8GB and serves both arms identically (student arrives as a GGUF
after the T6 merge step, so baseline-vs-student is apples-to-apples).

Modes (MODE constant below):
  baseline  student=None  -> prompt-only architect plans (G0 baseline, run NOW)
  student   GGUF=adapter gguf from T6 -> G1 student plans (run AFTER training)

Consumes: arms/g0_tasks.jsonl (12 tasks, from repo).
Produces: plans/<task_id>.md + plans/plans_manifest.json
Return path: download plans/, unzip into arms/kaggle-8b/ in the ftt repo.
"""
import json
import os
from pathlib import Path

MODE = "baseline"            # or "student"
REPO = "unsloth/Qwen3.5-9B-GGUF"
STUDENT_GGUF = ""            # MODE=student: local path to the T6-exported gguf
TASKS_FILE = "g0_tasks.jsonl"
OUT_DIR = Path("plans")
N_CTX = 8192
MAX_NEW = 6000
SYSTEM = ("You are the planner in a multi-agent software team. Given a task "
          "brief, produce a complete implementation plan: decomposition into "
          "steps, ordering and dependencies, risks with mitigations, and a "
          "testability check per step. Be concrete about files and interfaces.")

# --- resolve + download the quant (no hardcoded filename) ---
from huggingface_hub import hf_hub_download, list_repo_files  # noqa: E402

candidates = [f for f in list_repo_files(REPO) if "Q4_K_M" in f and f.endswith(".gguf")]
assert candidates, f"no Q4_K_M gguf in {REPO}"
print("quant candidates:", candidates)
gguf_path = STUDENT_GGUF if MODE == "student" and STUDENT_GGUF else hf_hub_download(
    REPO, filename=sorted(candidates)[0])
print("using:", gguf_path)

# --- serve ---
from llama_cpp import Llama  # noqa: E402  (pip: llama-cpp-python CUDA wheel, see notebook)

llm = Llama(model_path=gguf_path, n_ctx=N_CTX, n_gpu_layers=-1, verbose=False)

tasks = [json.loads(l) for l in Path(TASKS_FILE).read_text().splitlines() if l.strip()]
OUT_DIR.mkdir(exist_ok=True)
manifest = {}
for t in tasks:
    out = OUT_DIR / f"{t['task_id']}.md"
    if out.exists() and out.stat().st_size > 300:
        manifest[t["task_id"]] = "skipped"
        continue
    r = llm.create_chat_completion(
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": t["brief"]}],
        temperature=0.0,  # greedy: deterministic baseline
        max_tokens=MAX_NEW)
    text = r["choices"][0]["message"]["content"].strip()
    truncated = r["choices"][0].get("finish_reason") == "length"
    out.write_text(text + ("\n\n<!-- TRUNCATED_AT_MAX_NEW -->" if truncated else ""))
    manifest[t["task_id"]] = "ok" if not truncated else "truncated"
    print(t["task_id"], manifest[t["task_id"]], f"({len(text)} chars)", flush=True)

(OUT_DIR / "plans_manifest.json").write_text(json.dumps(
    {"mode": MODE, "model": gguf_path, "results": manifest}, indent=2))
print(json.dumps(manifest))
