"""Trimmed final-plan extraction (D12 length-bias control).

The gated comparison scores a format-normalized FINAL-PLAN view: reasoning
traces stripped, source tells removed, length capped and reported. All arms
pass through THIS extractor, so teacher/baseline/student arrive in the same
format and the judge cannot reward verbosity or role style.

Contract:
  extract_final(text) -> str   normalized, <= LENGTH_CAP chars
  length_report(text) -> dict  {"chars": n, "truncated": bool}

Strip rules (conservative, format-based, not model-based):
  -  /  blocks and anything between an opening/closing thinking tag
  - lines starting with "Thinking:" / "Reasoning:" / "Plan steps (draft):"
  - fenced code blocks are KEPT (they are plan content, not reasoning)
  - role tells: "As the (architect|planner|reviewer|implementer)..." prefixes
"""
import re

LENGTH_CAP = 4000

# reasoning blocks: <thinking>..</thinking> or  ..
_BLOCK = re.compile(
    r"<(?:thinking|thought|reasoning)>.*?</(?:thinking|thought|reasoning)>",
    re.IGNORECASE | re.DOTALL,
)
# self-closing / unclosed opener: drop from tag to end-of-line
_OPENER = re.compile(r"<(?:thinking|thought|reasoning)>[^\n]*", re.IGNORECASE)
_LEAD_LINE = re.compile(r"^(?:Thinking|Reasoning|Plan steps \(draft\)):\s.*$", re.IGNORECASE | re.MULTILINE)
_ROLE_TELL = re.compile(r"^(?:As the |I am the )(?:architect|planner|reviewer|implementer)[^\n]*$",
                        re.IGNORECASE | re.MULTILINE)


def extract_final(text: str) -> str:
    out = _BLOCK.sub("", text)
    out = _OPENER.sub("", out)
    out = _LEAD_LINE.sub("", out)
    out = _ROLE_TELL.sub("", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    if len(out) > LENGTH_CAP:
        out = out[:LENGTH_CAP].rstrip() + "\n…[capped]"
    return out


def length_report(text: str) -> dict:
    return {"chars": len(text), "truncated": "…[capped]" in text}
