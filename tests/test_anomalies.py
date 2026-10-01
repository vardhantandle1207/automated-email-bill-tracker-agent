from datetime import date

from agent.tools import detect_anomalies

TODAY = date(2026, 10, 20)
HISTORY = [
    {"due_date": "2026-07-12", "amount_base": 870.0},
    {"due_date": "2026-08-12", "amount_base": 940.0},
    {"due_date": "2026-09-12", "amount_base": 890.0},
]


def bill(**kw):
    return {"vendor": "TSSPDCL", "amount_base": 900.0, "due_date": "2026-10-25", "paid": False} | kw


def test_overdue_when_past_due_and_unpaid():
    result = detect_anomalies(bill(due_date="2026-10-12"), [], TODAY)
    assert result["overdue"] and result["flagged"]
    assert result["reasons"] == ["Overdue: due 2026-10-12 is 8 days before 2026-10-20 and not marked paid or autopay"]


def test_not_overdue_when_paid_or_autopay():
    assert not detect_anomalies(bill(due_date="2026-10-12", paid=True), [], TODAY)["overdue"]
    assert not detect_anomalies(bill(due_date="2026-10-12", autopay=True), [], TODAY)["overdue"]


def test_not_overdue_without_due_date():
    assert not detect_anomalies(bill(due_date=None), [], TODAY)["flagged"]


def test_above_trend_quotes_its_numbers():
    result = detect_anomalies(bill(amount_base=1240.5, due_date="2026-10-12", paid=True), HISTORY, TODAY)
    assert result["above_trend"] and not result["overdue"]
    assert result["reasons"] == ["₹1,240.50 is 38% above 3-month avg of ₹900 (3 bills; threshold 20%)"]


def test_within_threshold_is_not_flagged():
    assert not detect_anomalies(bill(amount_base=1070.0), HISTORY, TODAY)["above_trend"]  # +18.9%


def test_needs_minimum_history():
    assert not detect_anomalies(bill(amount_base=5000.0), HISTORY[-1:], TODAY)["above_trend"]


def test_window_ignores_old_and_same_month_bills():
    old = [{"due_date": "2026-01-12", "amount_base": 100.0}, {"due_date": "2026-02-12", "amount_base": 100.0}]
    same_month = [{"due_date": "2026-10-01", "amount_base": 100.0}]
    assert not detect_anomalies(bill(amount_base=900.0), old + same_month + HISTORY, TODAY)["above_trend"]
