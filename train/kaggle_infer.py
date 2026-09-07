# Kaggle-side inference — G0 8B baseline arm & G1 student arm
#
# Purpose (two modes, one script):
#   MODE=baseline  BASE_ID=<pinned 8B open-weight id>, ADAPTER=None
#                  -> prompt-only architect plans (the baseline every gate beats)
#   MODE=student   BASE_ID=<same>, ADAPTER=adapter/ (downloaded QLoRA output)
#                  -> G1 student plans
#
# Consumes the bundle written by:
#   python3 arms/run_arms.py --arm 27b --export-kaggle-tasks arms/g0_tasks.jsonl
# Upload arms/g0_tasks.jsonl next to this script. Output: plans/<task_id>.md
# plus plans_manifest.json — download the whole plans/ dir and place as
#   arms/kaggle-8b/<task_id>.md  in the ftt repo.
#
# Runs on T4/L4 (16GB): 8B @ 4-bit = ~5GB weights, ample KV headroom for
# long plan generation (unlike 27B, which is why 27B rides the API arm).

import json
import os
from pathlib import Path

MODE = "baseline"            # or "student"
BASE_ID = "REPLACE_ME"       # same pin as training (open question in design doc)
ADAPTER = "adapter" if MODE == "student" else None
TASKS_FILE = "arms/g0_tasks.jsonl"
OUT_DIR = Path("plans")
MAX_NEW = 6000
SYSTEM = ("You are the planner in a multi-agent software team. Given a task "
          "brief, produce a complete implementation plan: decomposition into "
          "steps, ordering and dependencies, risks with mitigations, and a "
          "testability check per step. Be concrete about files and interfaces.")

os.environ["HF_HOME"] = "/kaggle/working/hf"
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                         bnb_4bit_compute_dtype=torch.bfloat16,
                         bnb_4bit_use_double_quant=True)
tok = AutoTokenizer.from_pretrained(BASE_ID)
model = AutoModelForCausalLM.from_pretrained(BASE_ID, quantization_config=bnb,
                                             device_map="auto")
if ADAPTER:
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, ADAPTER).merge_and_unload()
    # merged student: same serving shape as baseline -> no format advantage in judging

tasks = [json.loads(l) for l in Path(TASKS_FILE).read_text().splitlines() if l.strip()]
OUT_DIR.mkdir(exist_ok=True)
manifest = {}
for t in tasks:
    out = OUT_DIR / f"{t['task_id']}.md"
    if out.exists():
        manifest[t["task_id"]] = "skipped"
        continue
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": t["brief"]}]
    inp = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    ids = tok(inp, return_tensors="pt").to(model.device)
    gen = model.generate(**ids, max_new_tokens=MAX_NEW, do_sample=False,
                         temperature=1.0,  # greedy: deterministic baseline
                         pad_token_id=tok.pad_token_id or tok.eos_token_id)
    text = tok.decode(gen[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
    # truncation honesty: if we hit MAX_NEW, mark it — gates must see the flag
    truncated = gen[0].shape[1] - ids["input_ids"].shape[1] >= MAX_NEW
    out.write_text(text.rstrip() + ("\n\n<!-- TRUNCATED_AT_MAX_NEW -->" if truncated else ""))
    manifest[t["task_id"]] = "ok" if not truncated else "truncated"
(Path(OUT_DIR) / "plans_manifest.json").write_text(json.dumps(
    {"mode": MODE, "base": BASE_ID, "adapter": ADAPTER, "results": manifest}, indent=2))
print(json.dumps(manifest))
