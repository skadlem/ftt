"""T2c self-tests — brief generator rules, zero API calls."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tasks.generate_briefs import (LEN_MAX, LEN_MIN, parse_json_array,
                                   train_families, validate_briefs)

GOOD = "x" * 600  # inside the length window


def _briefs(n=2, fam="f1", start=1):
    return [{"brief": f"{ch} " + GOOD, "family": fam} for ch in "abc"[:n]]


def test_parse_json_array_plain_and_fenced():
    assert parse_json_array('["a","b"]') == ["a", "b"]
    assert parse_json_array('```json\n["a","b"]\n```') == ["a", "b"]
    assert parse_json_array('noise ["a"] trailing') == ["a"]
    with pytest.raises(ValueError):
        parse_json_array("no array here")


def test_validate_length_window():
    vals = validate_briefs([{"brief": "short", "family": "f"},
                            {"brief": GOOD, "family": "f"},
                            {"brief": "y" * (LEN_MAX + 50), "family": "f"}],
                           {}, set(), lambda f, b: None)
    assert len(vals) == 1 and vals[0]["family"] == "f"


def test_validate_dedupe_vs_eval_and_batch():
    from teacher.sample import norm_sha
    eval_idx = {"core-x": norm_sha(GOOD)}
    vals = validate_briefs([{"brief": GOOD, "family": "f"}], eval_idx, set(),
                           lambda f, b: None)
    assert vals == []
    vals = validate_briefs([{"brief": GOOD, "family": "f"},
                            {"brief": GOOD, "family": "f"}], {}, set(),
                           lambda f, b: None)
    assert len(vals) == 1, "second duplicate must be refused"


def test_family_rule_enforced():
    vals = validate_briefs([{"brief": GOOD, "family": "wrong"}], {}, set(),
                           lambda f, b: f"bad family {f}")
    assert vals == []


def test_train_families_registry_readable():
    tf = train_families()
    assert set(tf) == {"qaida-chat-app", "suited-site-prediction"}
    assert all(v["usage"] == "train" for v in tf.values())
