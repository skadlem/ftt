"""429-aware backoff shared by the API feeders.

Overnight lesson 2026-09-08: token-plan went account-wide 429 while feeders
hammered one route; a 5s retry loop turns a cooldown into a longer ban.
Rate-limit errors now back off from a 120s floor with doubling; everything
else keeps the caller's fast base. Deterministic when base=0 and jitter=None
so unit tests stay instant.
"""
import random
import time

RATE_LIMIT_FLOOR_S = 120.0
RATE_LIMIT_CAP_S = 900.0


def is_rate_limit(err: Exception) -> bool:
    s = str(err)
    return "429" in s or "Too Many Requests" in s or "Rate limit" in s


def backoff_sleep(err: Exception, attempt: int, base_delay: float,
                  jitter: tuple[float, float] | None = None,
                  rate_floor: float = RATE_LIMIT_FLOOR_S,
                  cap: float = RATE_LIMIT_CAP_S) -> None:
    wait = base_delay * (2 ** attempt)
    if is_rate_limit(err):
        wait = max(wait, rate_floor * (2 ** attempt))
    wait = min(wait, cap)
    if jitter:
        wait += random.uniform(*jitter)
    time.sleep(wait)
