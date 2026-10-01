import io
import json
import urllib.request

import pytest

from agent import currency


@pytest.fixture(autouse=True)
def fresh_fx_cache(monkeypatch):
    monkeypatch.setattr(currency, "_live", {})


def fake_urlopen(payload, calls):
    def urlopen(url, timeout):
        calls.append(url)
        if isinstance(payload, Exception):
            raise payload
        return io.BytesIO(json.dumps(payload).encode())
    return urlopen


def test_static_rates_by_default(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen(OSError("must not be called"), []))
    assert currency.to_base(42.17, "usd") == 3500.11
    assert currency.to_base(10, "INR") == 10


def test_unknown_currency_raises():
    with pytest.raises(ValueError, match="Unknown currency 'XYZ'"):
        currency.to_base(1, "XYZ")


def test_live_rates_are_inverted_and_fetched_once_a_day(monkeypatch):
    calls = []
    monkeypatch.setenv("FX_SOURCE", "live")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen({"rates": {"USD": 0.0125, "JPY": 1.6}}, calls))
    assert currency.to_base(10, "USD") == 800.0
    assert currency.to_base(16, "JPY") == 10.0  # only available live
    assert currency.to_base(1, "GBP") == 105.0  # missing live -> static
    assert len(calls) == 1


def test_live_fetch_failure_falls_back_to_static(monkeypatch):
    calls = []
    monkeypatch.setenv("FX_SOURCE", "live")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen(OSError("offline"), calls))
    assert currency.to_base(1, "USD") == 83.0
    assert currency.to_base(1, "EUR") == 90.0
    assert len(calls) == 1  # the failure is remembered for the day, not retried per bill
