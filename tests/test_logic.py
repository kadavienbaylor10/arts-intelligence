from datetime import date, datetime, timedelta, timezone

from ai import deadlines, verifier
from ai.extractor import verify_quotes, TEXT_FIELDS
from ai.ics import build_ics
from ai.textutil import fingerprint, locate_quote

NOW = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)


def ev(**kw):
    base = dict(deadline=NOW + timedelta(days=40), deadline_confidence="CONFIRMED",
                source_tier="P1_OFFICIAL", cycle_label="FY2027")
    base.update(kw)
    return verifier.Evidence(**base)


def test_active_requires_all_conditions():
    assert verifier.decide(ev(), NOW) == "ACTIVE"
    assert verifier.decide(ev(source_tier="P3_SECONDARY_DB"), NOW) == "REQUIRES_VERIFICATION"
    assert verifier.decide(ev(deadline_confidence="PROBABLE"), NOW) == "REQUIRES_VERIFICATION"
    assert verifier.decide(ev(deadline=None), NOW) == "REQUIRES_VERIFICATION"


def test_old_cycle_page_is_not_active():
    # An old page that still shows a future-looking date for a past cycle must not be ACTIVE
    assert verifier.decide(ev(cycle_label="FY2024", is_recurring=True), NOW) == "UPCOMING"
    assert verifier.decide(ev(cycle_label="FY2024", is_recurring=False), NOW) == "EXPIRED"


def test_closed_canceled_expired_and_signals():
    assert verifier.decide(ev(page_says_canceled=True), NOW) == "CANCELED"
    assert verifier.decide(ev(deadline=NOW - timedelta(days=1)), NOW) == "EXPIRED"
    assert verifier.decide(ev(page_says_closed=True, is_recurring=True, deadline=None), NOW) == "UPCOMING"
    assert verifier.decide(ev(is_capital_signal=True), NOW) == "UPCOMING"


def test_review_schedule():
    assert verifier.next_review("EXPIRED", None, NOW) is None
    r = verifier.next_review("ACTIVE", NOW + timedelta(days=10), NOW)
    assert r == NOW + timedelta(days=7) or r < NOW + timedelta(days=7)


def test_milestone_plan_orders_and_ends_on_deadline():
    ms, compressed = deadlines.plan(date(2026, 11, 30), date(2026, 9, 24))
    assert not compressed
    assert ms[-1]["name"] == "DEADLINE" and ms[-1]["due_date"] == date(2026, 11, 30)
    dates = [m["due_date"] for m in ms]
    assert dates == sorted(dates)
    assert ms[-2]["due_date"] <= date(2026, 11, 28)  # 2-day buffer


def test_short_runway_is_flagged():
    _, compressed = deadlines.plan(date(2026, 10, 5), date(2026, 9, 24))
    assert compressed


def test_quote_check_rejects_fabricated_values():
    page = "Applications due March 3, 2027 at 5 p.m. CT. Awards up to $25,000 with a 1:1 cash match."
    opp = {f: {"value": None, "quote": None, "confidence": "UNKNOWN"} for f in TEXT_FIELDS}
    opp["application_deadline"] = {"value": "2027-03-03T17:00", "quote": "Applications due  March 3, 2027", "confidence": "CONFIRMED"}
    opp["funding_max"] = {"value": "50000", "quote": "Awards up to $50,000", "confidence": "CONFIRMED"}
    out = verify_quotes(opp, page)
    assert out["application_deadline"]["confidence"] == "CONFIRMED"
    assert out["funding_max"]["confidence"] == "UNKNOWN" and out["funding_max"]["value"] is None


def test_locate_quote_handles_curly_quotes():
    assert locate_quote("artist’s fee", "The artist's fee is fixed.") is not None
    assert locate_quote("not there", "The artist's fee is fixed.") is None


def test_fingerprint_stable_across_cosmetic_changes():
    assert fingerprint("Texas Commission on the Arts", "Arts Respond Project", "FY2027") == \
           fingerprint("texas commission on the arts", "Arts Respond Project Grant", "FY 2027".replace(" ", ""))


def test_ics_output():
    body = build_ics([{"uid": "a", "summary": "Deadline, test", "start_utc": NOW}], NOW)
    assert "BEGIN:VCALENDAR" in body and "SUMMARY:Deadline\\, test" in body and "TRIGGER:-P7D" in body


def test_long_runway_starts_90_days_out():
    ms, _ = deadlines.plan(date(2027, 10, 8), date(2026, 9, 24))
    assert ms[0]["due_date"] >= date(2027, 7, 10)


def test_html_cleanup_and_links():
    from ai.fetcher import html_to_text_and_links
    html = ("<html><nav>Menu</nav><script>x=1</script><main><h1>Arts Project Grant</h1>"
            "<p>Deadline: March 1</p><a href='/guidelines.pdf'>Guidelines</a></main></html>")
    text, links = html_to_text_and_links(html, "https://arts.example.gov/grants/")
    assert "Arts Project Grant" in text and "Menu" not in text and "x=1" not in text
    assert links == [{"url": "https://arts.example.gov/guidelines.pdf", "label": "Guidelines"}]
