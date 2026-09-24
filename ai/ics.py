"""Build an iCalendar feed (subscribe-able in Google/Apple/Outlook). Pure logic."""
from datetime import datetime, timezone


def _esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_ics(events, now: datetime | None = None) -> str:
    """events: iterable of dicts with uid, summary, description, url, and either
    start_utc (datetime) for timed deadlines or all_day (date) for milestones."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//arts-intelligence//EN",
             "X-WR-CALNAME:Arts Opportunities", "CALSCALE:GREGORIAN"]
    for e in events:
        lines += ["BEGIN:VEVENT", f"UID:{e['uid']}", f"DTSTAMP:{stamp}"]
        if e.get("start_utc"):
            lines.append("DTSTART:" + e["start_utc"].astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        else:
            lines.append("DTSTART;VALUE=DATE:" + e["all_day"].strftime("%Y%m%d"))
        lines.append("SUMMARY:" + _esc(e["summary"]))
        if e.get("description"):
            lines.append("DESCRIPTION:" + _esc(e["description"]))
        if e.get("url"):
            lines.append("URL:" + e["url"])
        if e.get("start_utc"):  # alarms 7 days and 1 day before real deadlines
            for trig in ("-P7D", "-P1D"):
                lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:{trig}",
                          "DESCRIPTION:" + _esc(e["summary"]), "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
