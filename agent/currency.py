"""Currency normalization to a single base currency (INR).

Two rate sources, chosen by FX_SOURCE:
  - static (default): the fixed `_STATIC_RATES` table. Deterministic, offline,
    and what eval.py and data/history_seed.json assume.
  - live: daily ECB reference rates from the free Frankfurter API, fetched once
    per process per day and kept in memory. If the fetch fails, or a currency is
    missing from it, the static table is used for that day.

The `to_base` signature is the same either way, so nothing downstream changes.
"""

import json
import logging
import os
import urllib.request
from datetime import date
from typing import Optional

BASE_CURRENCY = "INR"

_STATIC_RATES = {
    "INR": 1.0,
    "USD": 83.0,
    "EUR": 90.0,
    "GBP": 105.0,
}
_FX_URL = "https://api.frankfurter.dev/v1/latest?base={base}"
_live: dict[date, Optional[dict[str, float]]] = {}  # {day: rates to base, or None if that day's fetch failed}

log = logging.getLogger(__name__)


def _live_rates() -> Optional[dict[str, float]]:
    """Today's rates as {currency: base units per 1 unit}, fetched at most once a day."""
    today = date.today()
    if today not in _live:
        _live.clear()
        try:
            with urllib.request.urlopen(_FX_URL.format(base=BASE_CURRENCY), timeout=10) as resp:
                quoted = json.load(resp)["rates"]  # units of each currency per 1 base unit
            _live[today] = {BASE_CURRENCY: 1.0, **{c: 1 / r for c, r in quoted.items() if r}}
        except (OSError, ValueError, KeyError) as exc:  # network, bad JSON, or unexpected shape
            log.warning("Live FX fetch failed (%s); using static rates today", exc)
            _live[today] = None
    return _live[today]


def to_base(amount: float, currency: str) -> float:
    """Convert an amount in `currency` to the base currency (INR)."""
    code = currency.upper()
    live = _live_rates() if os.environ.get("FX_SOURCE") == "live" else None
    rate = (live or {}).get(code) or _STATIC_RATES.get(code)
    if rate is None:
        raise ValueError(f"Unknown currency {currency!r}; add it to _STATIC_RATES")
    return round(amount * rate, 2)
