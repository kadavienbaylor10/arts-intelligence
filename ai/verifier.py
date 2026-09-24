"""Validity rules. Pure logic: given what we know about an opportunity, decide its status.

A record is ACTIVE only when ALL of these hold:
  1. the application deadline is CONFIRMED from a P1 (official) source,
  2. the deadline is in the future,
  3. the cycle is current (or no cycle label conflicts with the present),
  4. the page shows no cancellation / closed language.
Anything short of that stays REQUIRES_VERIFICATION, UPCOMING, CLOSED, EXPIRED or CANCELED.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re


@dataclass
class Evidence:
    deadline: datetime | None          # application deadline (UTC-aware)
    deadline_confidence: str           # CONFIRMED | PROBABLE | INFERRED | UNKNOWN
    source_tier: str                   # P1_OFFICIAL | P2_... | P3_... | P4_...
    cycle_label: str | None
    page_says_canceled: bool = False
    page_says_closed: bool = False
    is_recurring: bool | None = None
    is_capital_signal: bool = False


def cycle_is_current(label: str | None, now: datetime) -> bool | None:
    """True/False if the label names years we can compare; None if unknowable."""
    if not label:
        return None
    years = []
    for m in re.finditer(r"(?:FY\s?'?)(\d{2,4})|\b(20\d{2})\b", label, re.I):
        y = m.group(1) or m.group(2)
        y = int(y)
        if y < 100:
            y += 2000
        years.append(y)
    if not years:
        return None
    # A fiscal year can run up to ~1 year ahead of the calendar year.
    return max(years) >= now.year


def decide(ev: Evidence, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if ev.page_says_canceled:
        return "CANCELED"
    if ev.is_capital_signal:
        return "UPCOMING"  # a signal is never an ACTIVE call
    if ev.deadline and ev.deadline < now:
        return "EXPIRED"
    if ev.page_says_closed:
        return "UPCOMING" if ev.is_recurring else "CLOSED"
    current = cycle_is_current(ev.cycle_label, now)
    if (ev.deadline and ev.deadline > now
            and ev.deadline_confidence == "CONFIRMED"
            and ev.source_tier == "P1_OFFICIAL"
            and current is not False):
        return "ACTIVE"
    if current is False:
        return "UPCOMING" if ev.is_recurring else "EXPIRED"
    return "REQUIRES_VERIFICATION"


def next_review(status: str, deadline: datetime | None, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    if status in ("EXPIRED", "CANCELED"):
        return None
    if status == "REQUIRES_VERIFICATION":
        return now + timedelta(days=3)
    if status in ("UPCOMING", "CLOSED"):
        return now + timedelta(days=30)
    # ACTIVE: weekly, and always re-check 14 and 3 days before the deadline
    candidates = [now + timedelta(days=7)]
    if deadline:
        for d in (14, 3):
            t = deadline - timedelta(days=d)
            if t > now + timedelta(hours=12):
                candidates.append(t)
    return min(candidates)
