"""Daily email digest: gather what changed, render HTML, send via Resend."""
from datetime import datetime, timezone
from html import escape

BUCKETS = [("this_week", "Deadlines in the next 7 days"),
           ("next_30", "Deadlines in 8–30 days"),
           ("next_90", "Deadlines in 31–90 days")]

STATUS_NOTE = {
    "ACTIVE": "confirmed open",
    "REQUIRES_VERIFICATION": "verify before relying on details",
    "UPCOMING": "expected / not open yet",
}


def gather(conn):
    """Collect digest data from the database (last 24 hours + upcoming deadlines)."""
    new = conn.execute("""
        SELECT o.id, o.name, o.validity, o.funding_max, o.source_url, o.opportunity_type,
               p.name AS place, p.state_code, org.name AS issuer,
               (SELECT min(d.due_at) FROM deadlines d WHERE d.opportunity_id = o.id AND d.kind='application') AS due_at,
               (SELECT d.local_timezone FROM deadlines d WHERE d.opportunity_id = o.id AND d.kind='application'
                ORDER BY d.due_at LIMIT 1) AS local_timezone
        FROM opportunities o
        LEFT JOIN places p ON p.id = o.place_id
        LEFT JOIN organizations org ON org.id = o.issuer_org_id
        WHERE o.discovered_at > now() - interval '1 day' AND o.duplicate_of IS NULL
          AND o.validity NOT IN ('EXPIRED','CANCELED','CLOSED')
        ORDER BY (o.validity = 'ACTIVE') DESC, o.funding_max DESC NULLS LAST, o.name""").fetchall()
    deadlines = conn.execute("""
        SELECT v.*, o.source_url FROM v_upcoming_deadlines v JOIN opportunities o ON o.id = v.id
        WHERE v.bucket IN ('this_week','next_30','next_90') ORDER BY v.due_at""").fetchall()
    changes = conn.execute("""
        SELECT c.id, c.field_name, c.old_value, c.new_value, o.name, o.source_url
        FROM opportunity_changes c JOIN opportunities o ON o.id = c.opportunity_id
        WHERE NOT c.alerted AND c.field_name IN
          ('name','funding_min','funding_max','match_requirement','applicant_eligibility','artist_eligibility',
           'validity','cycle_label','source_url')
        ORDER BY c.detected_at DESC LIMIT 50""").fetchall()
    failing = conn.execute("""
        SELECT name, url, last_error, consecutive_failures FROM sources
        WHERE consecutive_failures > 0 AND last_fetched_at > now() - interval '1 day'
        ORDER BY consecutive_failures DESC, name""").fetchall()
    cost = conn.execute("""SELECT coalesce(sum(est_cost_usd),0) AS usd FROM job_runs
                           WHERE job = 'extract' AND started_at > now() - interval '1 day'""").fetchone()["usd"]
    totals = conn.execute("""SELECT count(*) FILTER (WHERE validity='ACTIVE') AS active,
                                    count(*) FILTER (WHERE validity='REQUIRES_VERIFICATION') AS verify,
                                    count(*) AS total
                             FROM opportunities WHERE duplicate_of IS NULL""").fetchone()
    return {"new": new, "deadlines": deadlines, "changes": changes, "failing": failing,
            "cost": float(cost or 0), "totals": totals}


def _money(v):
    return f"${v:,.0f}" if v else ""


def _date(dt, tz=None):
    """Show the deadline in the call's own time zone (deadlines are stored in UTC)."""
    if not dt:
        return "no deadline found"
    if tz:
        from zoneinfo import ZoneInfo
        try:
            dt = dt.astimezone(ZoneInfo(tz))
        except Exception:  # noqa: BLE001
            pass
    return dt.strftime("%b %d, %Y")


def _link(name, url):
    return f'<a href="{escape(url or "#")}">{escape(name or "(untitled)")}</a>'


def render(data, today=None):
    """Return (subject, html). Pure function: no I/O."""
    today = today or datetime.now(timezone.utc)
    n_new, n_week = len(data["new"]), sum(1 for d in data["deadlines"] if d["bucket"] == "this_week")
    subject = f"Arts opportunities {today:%b %d}: {n_new} new, {n_week} due this week"

    h = ['<div style="font-family:Arial,Helvetica,sans-serif;max-width:680px;color:#222;line-height:1.45">',
         f'<h2 style="margin:0 0 4px">Arts opportunities — {today:%A, %B %d, %Y}</h2>',
         f'<p style="margin:0 0 16px;color:#666">{data["totals"]["total"]} tracked · '
         f'{data["totals"]["active"]} confirmed open · {data["totals"]["verify"]} need verification · '
         f'scan cost ~${data["cost"]:.2f}</p>']

    def section(title):
        h.append(f'<h3 style="border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:24px">{escape(title)}</h3>')

    section(f"New opportunities ({n_new})")
    if not data["new"]:
        h.append("<p>No new opportunities found today.</p>")
    else:
        h.append("<ul style='padding-left:18px'>")
        for o in data["new"]:
            where = ", ".join(x for x in (o["place"], o["state_code"]) if x and x != o["state_code"]) or (o["state_code"] or "")
            if o["place"] and o["state_code"] and o["place"] != o["state_code"]:
                where = f'{o["place"]}, {o["state_code"]}'
            bits = [x for x in (escape(o["issuer"] or ""), escape(where), _money(o["funding_max"]),
                                "due " + _date(o["due_at"], o.get("local_timezone"))) if x]
            h.append(f'<li style="margin-bottom:8px">{_link(o["name"], o["source_url"])}<br>'
                     f'<span style="color:#555">{" · ".join(bits)}</span><br>'
                     f'<span style="color:#888;font-size:12px">{escape(STATUS_NOTE.get(o["validity"], o["validity"]))}</span></li>')
        h.append("</ul>")

    for key, title in BUCKETS:
        rows = [d for d in data["deadlines"] if d["bucket"] == key]
        if not rows:
            continue
        section(f"{title} ({len(rows)})")
        h.append("<ul style='padding-left:18px'>")
        for d in rows:
            kind = "" if d["kind"] == "application" else f' <b>[{escape(d["kind"].replace("_", " "))}]</b>'
            verify = "" if (d["validity"] == "ACTIVE" and d["confidence"] == "CONFIRMED") else \
                ' <span style="color:#b36b00;font-size:12px">verify</span>'
            loc = escape(", ".join(x for x in (d["place"], d["state_code"]) if x))
            h.append(f'<li><b>{_date(d["due_at"], d.get("local_timezone"))}</b>{kind} — {_link(d["name"], d["source_url"])}'
                     f' <span style="color:#555">{loc}</span>{verify}</li>')
        h.append("</ul>")

    if data["changes"]:
        section(f"Changed details ({len(data['changes'])})")
        h.append("<ul style='padding-left:18px'>")
        for c in data["changes"]:
            h.append(f'<li>{_link(c["name"], c["source_url"])}: {escape(c["field_name"].replace("_", " "))} '
                     f'changed from <i>{escape(str(c["old_value"])[:80])}</i> to <b>{escape(str(c["new_value"])[:80])}</b></li>')
        h.append("</ul>")

    if data["failing"]:
        section(f"Sources that failed today ({len(data['failing'])})")
        h.append("<ul style='padding-left:18px;color:#555'>")
        for s in data["failing"]:
            h.append(f'<li>{_link(s["name"], s["url"])} — {escape((s["last_error"] or "unknown error")[:120])}'
                     f' (failed {s["consecutive_failures"]}x)</li>')
        h.append("</ul>")

    h.append('<p style="color:#999;font-size:12px;margin-top:24px">"Verify" means the deadline or status was not '
             'fully confirmed on an official page. Open the link and check before acting.</p></div>')
    return subject, "\n".join(h)


def send(api_key, sender, to, subject, html):
    import httpx
    r = httpx.post("https://api.resend.com/emails", timeout=30,
                   headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                   json={"from": sender, "to": [to], "subject": subject, "html": html})
    if r.status_code >= 300:
        raise RuntimeError(f"Resend error {r.status_code}: {r.text[:300]}")
    return r.json()
