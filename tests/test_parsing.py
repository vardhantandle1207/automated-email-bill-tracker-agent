from datetime import date

from agent.parsing import dates_mentioned, find_issues, money_mentions, regex_extract, vendor_key


def test_vendor_key():
    assert vendor_key("Amazon Web Services") == "amazonwebservices"
    assert vendor_key(None) == ""


def test_money_mentions_read_markers_and_thousands(emails):
    assert (1240.5, "INR") in [m[:2] for m in money_mentions(emails["electricity.txt"])]
    assert (42.17, "USD") in [m[:2] for m in money_mentions(emails["aws.txt"])]
    assert (649.0, "INR") in [m[:2] for m in money_mentions(emails["netflix.txt"])]


def test_ambiguous_numeric_date_yields_both_readings():
    found = {d for d, _ in dates_mentioned("Due date: 12-10-2026")}
    assert found == {date(2026, 10, 12), date(2026, 12, 10)}


def test_named_month_dates():
    found = {d for d, _ in dates_mentioned("Payment due: October 15, 2026\nPaid on 28 September 2026")}
    assert found == {date(2026, 10, 15), date(2026, 9, 28)}


def test_find_issues_accepts_a_correct_record(emails):
    record = {"vendor": "TSSPDCL", "amount": 1240.5, "currency": "INR", "due_date": "2026-10-12"}
    assert find_issues(record, emails["electricity.txt"]) == []


def test_find_issues_names_each_wrong_field(emails):
    record = {"vendor": "BESCOM", "amount": 214.0, "currency": "USD", "due_date": "2026-11-12"}
    issues = find_issues(record, emails["electricity.txt"])
    assert [i.split()[0] for i in issues] == ["amount", "currency", "vendor", "due_date"]


def test_find_issues_flags_missing_due_date(emails):
    record = {"vendor": "Netflix", "amount": 649.0, "currency": "INR", "due_date": None}
    assert any("due_date is null" in i for i in find_issues(record, emails["netflix.txt"]))


def test_regex_extract_reads_autopay(emails):
    assert regex_extract(emails["aws.txt"])["autopay"] is True
    assert regex_extract(emails["electricity.txt"])["autopay"] is False
    assert regex_extract(emails["netflix.txt"])["autopay"] is False


def test_regex_extract_fields(emails):
    rec = regex_extract(emails["electricity.txt"])
    assert (rec["vendor"], rec["amount"], rec["currency"], rec["due_date"], rec["paid"]) == (
        "TSSPDCL", 1240.5, "INR", "2026-10-12", False)
    assert rec["amount_base"] == 1240.5
