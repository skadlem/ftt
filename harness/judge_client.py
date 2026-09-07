"""Live judge + arm transport glue: glm-5.2 (non-Qwen family vs teacher).

Wire into harness.judge.run(pairs, make_live_judge(), out_path).
Verified live 2026-09-07: token-plan glm-5.2 emits clean single-token content
when given a verdict question + generous max_tokens (it is a reasoning model:
tiny budgets starve the visible answer — probe showed content='' at 8 tokens,
content='A' at 512).
"""
import json
import os
import urllib.request

JUDGE_URL = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
JUDGE_MODEL = "glm-5.2"


def make_live_judge(model: str = JUDGE_MODEL, timeout: float = 240.0):
    key = os.environ.get("QWEN_TOKEN_PLAN_API_KEY", "")
    if not key:
        raise RuntimeError("QWEN_TOKEN_PLAN_API_KEY not in env")

    def judge(prompt: str) -> str:
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.0,
        }).encode()
        req = urllib.request.Request(JUDGE_URL, data=body, headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            resp = json.loads(r.read())
        msg = resp["choices"][0]["message"]
        return (msg.get("content") or "").strip()

    return judge
