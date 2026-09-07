# QLoRA round template — 8B planner from ftt teacher traces
#
# Run on Kaggle (T4/L4, 16GB) or Colab. ONE tuning round = one data revision +
# one run here (design-doc kill-condition unit). Budget: ~4-6h on T4 for
# ~200-500 traces. Checkpoints to /kaggle/working AND download the adapter —
# Kaggle wipes working dir between sessions.
#
# Input: ../traces/traces.jsonl  records {"task_id","family","plan","reasoning"}
# Upload as traces.jsonl to the Kaggle dataset alongside this notebook.

import json, os, re
from pathlib import Path

# ------------------ 0. env ------------------
os.environ["HF_HOME"] = "/kaggle/working/hf"
USE_4BIT = True                      # 16GB tier: QLoRA only. Never flip to LoRA here.

# ------------------ 1. pins (fill before running) ------------------
BASE_ID = "REPLACE_ME"               # open HF ID, same family as teacher (see Open Questions)
MAX_LEN = 8192                       # plan + reasoning traces are long; verify vs data
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj",
                  "gate_proj", "up_proj", "down_proj"]

# ------------------ 2. data ------------------
def build_example(rec):
    """Role-tuned planner SFT example: system + brief -> reasoning + plan.
    Keep reasoning IN (the whole point of D-C: student learns process)."""
    brief = rec.get("brief") or ""
    parts = []
    if rec.get("reasoning"):
        parts.append(rec["reasoning"].strip())
    parts.append(rec["plan"].strip())
    return {"prompt": f"<system: planner role>\n{brief}",
            "completion": "\n\n".join(parts)}

def load_traces(path="traces.jsonl"):
    rows = []
    for line in Path(path).read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # torn last line from a killed sampler — expected, skip
    return rows

def load_briefs(pool="tasks/train_pool.jsonl"):
    # train_pool.jsonl carries {"id","brief"} — join so examples are
    # (prompt=brief, completion=reasoning+plan). Sampler records may already
    # embed brief; this covers the older schema.
    return {json.loads(l)["id"]: json.loads(l)["brief"]
            for l in Path(pool).read_text().splitlines() if l.strip()}

def tokenize(ex, tok):
    messages = [{"role": "user", "content": ex["prompt"]},
                {"role": "assistant", "content": ex["completion"]}]
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    return tok(text, truncation=True, max_length=MAX_LEN, padding="max_length")

# ------------------ 3. model ------------------
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, TaskType
from trl import SFTTrainer, SFTConfig

bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                         bnb_4bit_compute_dtype=torch.bfloat16,
                         bnb_4bit_use_double_quant=True)
tok = AutoTokenizer.from_pretrained(BASE_ID)
tok.padding_side = "right"           # explicit; mask correctness depends on it
if tok.pad_token is None:
    tok.pad_token = tok.eos_token
model = AutoModelForCausalLM.from_pretrained(BASE_ID, quantization_config=bnb,
                                             device_map="auto")
model.config.use_cache = False
model.enable_input_require_grads()   # required for grad flow through 4-bit base

peft = LoraConfig(r=16, lora_alpha=32, target_modules=TARGET_MODULES,
                  lora_dropout=0.05, bias="none", task_type=TaskType.CAUSAL_LM)
model = get_peft_model(model, peft)
model.print_trainable_parameters()  # record in run notes: ~0.1-0.3% of params

# ------------------ 4. train ------------------
traces = load_traces()
briefs = load_briefs() if Path("tasks/train_pool.jsonl").exists() else {}
examples = [build_example({**t, "brief": briefs.get(t["task_id"], "")}) for t in traces]
assert examples, "no traces — upload traces.jsonl first"
print(f"examples: {len(examples)}")

cfg = SFTConfig(
    output_dir="/kaggle/working/adapter",
    num_train_epochs=2,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,
    learning_rate=2e-4,             # QLoRA-class default; halve if loss oscillates
    lr_scheduler_type="cosine",
    warmup_ratio=0.03,
    bf16=True,
    optim="paged_adamw_8bit",       # 16GB tier only
    gradient_checkpointing=True,
    logging_steps=10,
    save_strategy="steps", save_steps=100,        # checkpoint cadence per plan
    report_to="none",
    max_seq_length=MAX_LEN,
    remove_unused_columns=False,
    dataset_text_field=None,
)
trainer = SFTTrainer(model=model, tokenizer=tok,
                     train_dataset=[tokenize(e, tok) for e in examples],
                     args=cfg)
trainer.train()

# ------------------ 5. save + prove ------------------
trainer.save_model("/kaggle/working/adapter")
tok.save_pretrained("/kaggle/working/adapter")
# smoke-generate BEFORE ending the session (quota kill protection):
inp = tok(examples[0]["prompt"], return_tensors="pt").to(model.device)
out = model.generate(**inp, max_new_tokens=200, do_sample=False)
print(tok.decode(out[0], skip_special_tokens=True)[:1200])
# THEN download adapter/ (zip it) — Kaggle wipes /kaggle/working between runs.
# Log to run notes: BASE_ID, examples n, trainable params, final loss,
# wall-clock, git SHA of ftt at sample time (kill-condition bookkeeping).
