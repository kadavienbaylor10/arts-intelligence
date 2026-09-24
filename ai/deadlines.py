"""Backward milestone planning from a deadline (pure logic)."""
from datetime import date, timedelta

# (name, share of the total runway)  -- shares sum to 1.0
STANDARD_PLAN = [
    ("Research", 0.10),
    ("Identify partners", 0.08),
    ("Contact partners", 0.10),
    ("Concept development", 0.17),
    ("Budget", 0.10),
    ("Draft application", 0.15),
    ("Partner review", 0.12),
    ("Final review", 0.10),
    ("Submission preparation", 0.08),
]
MIN_WORKDAYS_WITH_PARTNERS = 15
SUBMIT_BUFFER_DAYS = 2   # aim to be ready 2 calendar days early
MAX_LEAD_DAYS = 90       # long runways: start the plan ~3 months out, not a year out


def workdays_between(start: date, end: date) -> int:
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def add_workdays(start: date, n: int) -> date:
    d = start
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def plan(deadline: date, today: date, needs_partners: bool = True):
    """Return (milestones, compressed). Each milestone: dict(name, due_date, sequence)."""
    today = max(today, deadline - timedelta(days=MAX_LEAD_DAYS))
    target = deadline - timedelta(days=SUBMIT_BUFFER_DAYS)
    runway = workdays_between(today, target)
    compressed = runway < (MIN_WORKDAYS_WITH_PARTNERS if needs_partners else 7)
    steps = STANDARD_PLAN if needs_partners else [s for s in STANDARD_PLAN
                                                  if s[0] not in ("Identify partners", "Contact partners", "Partner review")]
    total_share = sum(s for _, s in steps)
    out, used = [], 0.0
    for i, (name, share) in enumerate(steps, start=1):
        used += share / total_share
        offset = max(1, round(runway * used)) if runway > 0 else 0
        due = add_workdays(today, offset) if runway > 0 else today
        out.append({"name": name, "due_date": min(due, target if runway > 0 else deadline), "sequence": i})
    out.append({"name": "DEADLINE", "due_date": deadline, "sequence": len(out) + 1})
    return out, compressed
