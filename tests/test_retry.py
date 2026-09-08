"""429-aware backoff: slow on rate limits, instant otherwise."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import harness.retry as R  # noqa: E402
from harness.retry import backoff_sleep  # noqa: E402


def test_rate_limit_error_hits_floor(monkeypatch):
    slept = []
    monkeypatch.setattr(R.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(R.random, "uniform", lambda a, b: 0.0)
    backoff_sleep(ValueError("HTTP Error 429: Too Many Requests"), 0, 0.0,
                  jitter=None)
    assert slept and slept[0] >= 120.0


def test_rate_limit_backoff_doubles(monkeypatch):
    slept = []
    monkeypatch.setattr(R.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(R.random, "uniform", lambda a, b: 0.0)
    backoff_sleep(ValueError("429"), 2, 0.0, jitter=None)
    assert slept == [480.0]


def test_plain_error_with_zero_base_sleeps_zero(monkeypatch):
    slept = []
    monkeypatch.setattr(R.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(R.random, "uniform", lambda a, b: 0.0)
    backoff_sleep(TimeoutError("boom"), 0, 0.0, jitter=None)
    assert slept == [0.0]


def test_plain_backoff_grows_and_caps(monkeypatch):
    slept = []
    monkeypatch.setattr(R.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(R.random, "uniform", lambda a, b: 0.0)
    backoff_sleep(TimeoutError("x"), 3, 5.0, jitter=None)
    assert slept == [40.0]
    backoff_sleep(TimeoutError("x"), 10, 5.0, jitter=None, cap=100.0)
    assert slept[1] == 100.0
