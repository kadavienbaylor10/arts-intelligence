"""Pipeline entry point.

  python -m ai.run load-sources sql/seed_sources.csv
  python -m ai.run fetch        # fetch due sources, snapshot changed pages
  python -m ai.run extract      # LLM-extract opportunities from changed snapshots
  python -m ai.run verify       # re-evaluate status, expire past deadlines, schedule reviews
  python -m ai.run calendar     # write calendar.ics (and upload if Supabase storage is configured)
  python -m ai.run daily        # fetch + extract + verify + calendar
"""
import csv
import re
import sys
from datetime import date, datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from . import config, db, deadlines, verifier
from .textutil import content_hash, fingerprint

TZ_ALIASES = {"ET": "America/New_York", "EST": "America/New_York", "EDT": "America/New_York", "EASTERN": "America/New_York",
              "CT": "America/Chicago", "CST": "America/Chicago", "CDT": "America/Chicago", "CENTRAL": "America/Chicago",
              "MT": "America/Denver", "MST": "America/Denver", "MDT": "America/Denver", "MOUNTAIN": "America/Denver",
              "PT": "America/Los_Angeles", "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles", "PACIFIC": "America/Los_Angeles",
              "AKT": "America/Anchorage", "HT": "Pacific/Honolulu", "HST": "Pacific/Honolulu"}
STATE_TZ = {"TX": "America/Chicago", "IL": "America/Chicago", "TN": "America/Chicago", "LA": "America/Chicago",
            "MN": "America/Chicago", "CA": "America/Los_Angeles", "WA": "America/Los_Angeles", "CO": "America/Denver",
            "AZ": "America/Phoenix", "AK": "America/Anchorage", "HI": "Pacific/Honolulu"}


def resolve_tz(tz_text, state_code):
    if tz_text:
        t = tz_text.strip()
        if "/" in t:
            try:
                ZoneInfo(t)
                return t, True
            except Exception:
                pass
        key = re.sub(r"[^A-Z]", "", t.upper())
        if key in TZ_ALIASES:
            return TZ_ALIASES[key], True
    return STATE_TZ.get(state_code or "", "America/New_York"), False


def parse_deadline(value, tz_name):
    """ISO date or datetime (local) -> aware UTC datetime. Date-only deadlines are set to 11:59 PM local."""
    if not value:
        return None, False
    try:
        if "T" in value:
            local = datetime.fromisoformat(value[:16])
            time_stated = True
        else:
            d = date.fromisoformat(value[:10])
            local = datetime(d.year, d.month, d.day, 23, 59)
            time_stated = False
    except ValueError:
        return None, False
    return local.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc), time_stated


def money(v):
    if not v:
        return None
    digits = re.sub(r"[^\d.]", "", str(v))
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def val(opp, f):
    return (opp.get(f) or {}).get("value")


# ---------------------------------------------------------------- commands

def cmd_load_sources(path):
    with db.connect() as conn, open(path, newline="") as fh:
        n = 0
        for row in csv.DictReader(fh):
            place_id = None
            if row.get("state_code"):
                place_id = db.get_or_create_place(conn, None, row["state_code"])
            conn.execute("""
                INSERT INTO sources (name, url, tier, category, place_id, fetch_method, check_every, tos_notes, discovered_via)
                VALUES (%s,%s,%s,%s,%s,%s, make_interval(days => %s), %s, 'seed')
                ON CONFLICT (url) DO NOTHING""",
                (row["name"], row["url"], row["tier"], row["category"], place_id, row["fetch_method"],
                 int(row.get("check_every_days") or 7), row.get("notes") or None))
            n += 1
        conn.commit()
    print(f"loaded {n} sources")


def cmd_fetch():
    from .fetcher import fetch, make_client
    import httpx
    ok = fail = changed_n = 0
    with db.connect() as conn, make_client() as client:
        for s in db.sources_due(conn, config.MAX_SOURCES_PER_RUN):
            try:
                r = fetch(s["url"], client)
                if r["robots_allowed"] is False:
                    conn.execute("UPDATE sources SET robots_allowed=FALSE, last_fetched_at=now() WHERE id=%s", (s["id"],))
                    print(f"robots.txt disallows: {s['url']}")
                    continue
                if not r["text"] or (r["status"] or 500) >= 400:
                    raise httpx.HTTPError(f"status {r['status']}")
                h = content_hash(r["text"])
                changed = h != s["last_content_hash"]
                db.record_fetch(conn, s, r["final_url"], r["status"], r["text"], changed, h, r["robots_allowed"])
                changed_n += changed
                ok += 1
            except Exception as e:  # noqa: BLE001 - one bad source must not stop the run
                db.record_failure(conn, s["id"], str(e))
                fail += 1
                print(f"fetch failed: {s['url']}: {e}")
            conn.commit()
        db.log_job(conn, "fetch", "ok", ok + fail, changed_n, error=f"{fail} failures" if fail else None)
        conn.commit()
    print(f"fetched {ok}, changed {changed_n}, failed {fail}")


def save_opportunity(conn, opp, snap, model, today):
    name, issuer = val(opp, "name"), val(opp, "issuer")
    if not name:
        return None
    state = val(opp, "state_code") or snap["state_code"]
    cycle = val(opp, "cycle_label")
    fp = fingerprint(issuer or snap["source_name"], name, cycle)
    tz_name, tz_stated = resolve_tz(val(opp, "deadline_timezone"), state)
    due_utc, time_stated = parse_deadline(val(opp, "application_deadline"), tz_name)
    cols = {
        "name": name,
        "issuer_org_id": db.get_or_create_org(conn, issuer),
        "place_id": db.get_or_create_place(conn, val(opp, "city"), state),
        "opportunity_type": "capital_project_signal" if opp.get("is_capital_project_signal")
                            else (val(opp, "opportunity_type") or "other").lower().replace(" ", "_")[:40],
        "funding_type": val(opp, "funding_type"),
        "description": val(opp, "description"),
        "community_served": val(opp, "community_served"),
        "applicant_eligibility": val(opp, "applicant_eligibility"),
        "artist_eligibility": val(opp, "artist_eligibility"),
        "required_partners": val(opp, "required_partners"),
        "funding_min": money(val(opp, "funding_min")),
        "funding_max": money(val(opp, "funding_max")),
        "total_project_budget": money(val(opp, "total_project_budget")),
        "artist_budget": money(val(opp, "artist_budget")),
        "match_requirement": val(opp, "match_requirement"),
        "project_timeline": val(opp, "project_timeline"),
        "installation_timeline": val(opp, "installation_timeline"),
        "application_requirements": val(opp, "application_requirements"),
        "contact_name": val(opp, "contact_name"),
        "contact_info": val(opp, "contact_info"),
        "source_url": opp.get("detail_url") or snap["url"],
        "cycle_label": cycle,
        "is_recurring": opp.get("is_recurring"),
        "fingerprint": fp,
    }
    known_types = {r["code"] for r in conn.execute("SELECT code FROM opportunity_types").fetchall()}
    if cols["opportunity_type"] not in known_types:
        cols["opportunity_type"] = "other"

    existing = db.find_by_fingerprint(conn, fp)
    if existing:
        opp_id = existing["id"]
        db.update_opportunity(conn, opp_id, cols, snap["id"])
    else:
        opp_id = db.insert_opportunity(conn, cols)

    claim_ids = {}
    from .extractor import TEXT_FIELDS
    for f in TEXT_FIELDS:
        claim_ids[f] = db.add_claim(conn, opp_id, f, opp.get(f) or {}, snap["id"], model)
    conn.execute("""INSERT INTO claims (entity_table, entity_id, field_name, value_json, confidence, snapshot_id, extracted_by, model)
                    VALUES ('opportunities', %s, 'page_flags', %s, 'INFERRED', %s, 'AGENT', %s)""",
                 (opp_id, db.Json({"closed": opp.get("page_says_closed"), "canceled": opp.get("page_says_canceled"),
                                   "capital_signal": opp.get("is_capital_project_signal")}), snap["id"], model))

    for m in opp.get("mediums") or []:
        conn.execute("""INSERT INTO opportunity_mediums (opportunity_id, medium_code, basis) VALUES (%s,%s,'INFERRED')
                        ON CONFLICT DO NOTHING""", (opp_id, m))

    dl_conf = (opp.get("application_deadline") or {}).get("confidence", "UNKNOWN")
    if due_utc:
        if not (tz_stated and time_stated) and dl_conf == "CONFIRMED":
            dl_conf = "PROBABLE"   # date confirmed, but exact time/zone assumed
        db.upsert_deadline(conn, opp_id, "application", due_utc, tz_name, dl_conf, claim_ids["application_deadline"])
    itp_utc, _ = parse_deadline(val(opp, "intent_to_apply_deadline"), tz_name)
    if itp_utc:
        db.upsert_deadline(conn, opp_id, "intent_to_apply", itp_utc, tz_name,
                           (opp.get("intent_to_apply_deadline") or {}).get("confidence", "UNKNOWN"),
                           claim_ids["intent_to_apply_deadline"])

    evaluate(conn, opp_id)
    return opp_id


def evaluate(conn, opp_id, now=None):
    """Apply verifier rules to one opportunity and (re)build its milestone plan."""
    now = now or datetime.now(timezone.utc)
    o = conn.execute("SELECT * FROM opportunities WHERE id=%s", (opp_id,)).fetchone()
    d = conn.execute("""SELECT d.*, s.tier FROM deadlines d
                        LEFT JOIN claims c ON c.id = d.claim_id
                        LEFT JOIN source_snapshots sn ON sn.id = c.snapshot_id
                        LEFT JOIN sources s ON s.id = sn.source_id
                        WHERE d.opportunity_id=%s AND d.kind='application'""", (opp_id,)).fetchone()
    flags = conn.execute("""SELECT value_json FROM claims WHERE entity_table='opportunities' AND entity_id=%s
                            AND field_name='page_flags' ORDER BY id DESC LIMIT 1""", (opp_id,)).fetchone()
    flags = (flags or {}).get("value_json") or {}
    ev = verifier.Evidence(
        deadline=d["due_at"] if d else None,
        deadline_confidence=d["confidence"] if d else "UNKNOWN",
        source_tier=(d or {}).get("tier") or "P3_SECONDARY_DB",
        cycle_label=o["cycle_label"],
        page_says_canceled=bool(flags.get("canceled")),
        page_says_closed=bool(flags.get("closed")),
        is_recurring=o["is_recurring"],
        is_capital_signal=bool(flags.get("capital_signal")) or o["opportunity_type"] == "capital_project_signal",
    )
    status = verifier.decide(ev, now)
    overall = "CONFIRMED" if status == "ACTIVE" else (ev.deadline_confidence if d else "UNKNOWN")
    conn.execute("""UPDATE opportunities SET validity=%s, overall_confidence=%s, last_verified_at=now(),
                    next_review_at=%s WHERE id=%s""",
                 (status, overall, verifier.next_review(status, ev.deadline, now), opp_id))
    if status in ("ACTIVE", "REQUIRES_VERIFICATION") and ev.deadline and ev.deadline > now:
        # Public-art applications almost always need partners (fabricator, engineer, community org),
        # so the partner-inclusive plan is the default.
        local_due = ev.deadline.astimezone(ZoneInfo(d["local_timezone"] or "America/New_York")).date()
        ms, compressed = deadlines.plan(local_due, now.date(), needs_partners=True)
        db.replace_milestones(conn, opp_id, ms, compressed)
    return status


def cmd_extract():
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    from .extractor import extract, verify_quotes
    tin = tout = found = 0
    today = date.today()
    with db.connect() as conn:
        snaps = db.snapshots_to_extract(conn, config.MAX_EXTRACTIONS_PER_RUN)
        for snap in snaps:
            try:
                data, usage = extract(client, config.EXTRACT_MODEL, snap["clean_text"], snap["url"], today)
                tin += usage.input_tokens
                tout += usage.output_tokens
                for opp in data.get("opportunities", []):
                    opp = verify_quotes(opp, snap["clean_text"])
                    if save_opportunity(conn, opp, snap, config.EXTRACT_MODEL, today):
                        found += 1
                # Propose follow-up links as INACTIVE sources awaiting your approval
                src_domain = urlparse(snap["url"]).netloc
                for link in data.get("promising_links", [])[:10]:
                    same = urlparse(link["url"]).netloc == src_domain
                    conn.execute("""INSERT INTO sources (name, url, tier, category, place_id, fetch_method, discovered_via, active)
                                    SELECT %s, %s, %s, s.category, s.place_id, 'HTML', %s, FALSE FROM sources s WHERE s.id=%s
                                    ON CONFLICT (url) DO NOTHING""",
                                 (link["label"][:200], link["url"], snap["tier"] if same else "P3_SECONDARY_DB",
                                  f"link_from_source:{snap['source_id']}", snap["source_id"]))
                db.log_job(conn, f"extract:{snap['id']}", "ok", 1, len(data.get("opportunities", [])),
                           usage.input_tokens, usage.output_tokens)
                conn.commit()
            except Exception as e:  # noqa: BLE001
                conn.rollback()
                db.log_job(conn, f"extract:{snap['id']}", "error", 1, 0, error=str(e)[:500])
                conn.commit()
                print(f"extract failed for snapshot {snap['id']}: {e}")
        cost = tin / 1e6 * config.PRICE_PER_MTOK["input"] + tout / 1e6 * config.PRICE_PER_MTOK["output"]
        db.log_job(conn, "extract", "ok", len(snaps), found, tin, tout, cost)
        conn.commit()
    print(f"extracted {found} opportunities from {len(snaps)} pages; est. cost ${cost:.3f}")


def cmd_verify():
    with db.connect() as conn:
        rows = conn.execute("""SELECT id FROM opportunities WHERE duplicate_of IS NULL
                               AND validity NOT IN ('EXPIRED','CANCELED')
                               AND (next_review_at IS NULL OR next_review_at <= now())""").fetchall()
        counts = {}
        for r in rows:
            s = evaluate(conn, r["id"])
            counts[s] = counts.get(s, 0) + 1
        db.log_job(conn, "verify", "ok", len(rows), len(rows))
        conn.commit()
    print(f"verified {len(rows)}: {counts}")


def cmd_calendar(out_path="calendar.ics"):
    from .ics import build_ics
    events = []
    with db.connect() as conn:
        for r in conn.execute("SELECT * FROM v_upcoming_deadlines").fetchall():
            flag = "" if r["confidence"] == "CONFIRMED" and r["validity"] == "ACTIVE" else " [VERIFY]"
            events.append({"uid": f"dl-{r['id']}-{r['kind']}@arts-intelligence",
                           "summary": f"{r['kind'].replace('_', ' ').upper()}: {r['name']}{flag}",
                           "description": f"{r['place'] or ''} {r['state_code'] or ''} | status {r['validity']} | "
                                          f"confidence {r['confidence']}",
                           "start_utc": r["due_at"]})
        for m in conn.execute("""SELECT m.*, o.name AS opp FROM milestones m JOIN opportunities o ON o.id=m.opportunity_id
                                 WHERE m.completed_at IS NULL AND m.name <> 'DEADLINE' AND m.due_date >= current_date
                                 AND o.stage NOT IN ('NEW','ARCHIVED','DECLINED')""").fetchall():
            # Milestones appear only once you move an opportunity past NEW, so the calendar isn't flooded.
            events.append({"uid": f"ms-{m['id']}@arts-intelligence",
                           "summary": f"{m['name']}: {m['opp']}" + (" (compressed)" if m["compressed"] else ""),
                           "all_day": m["due_date"]})
    body = build_ics(events)
    with open(out_path, "w") as fh:
        fh.write(body)
    if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
        import httpx
        r = httpx.post(f"{config.SUPABASE_URL}/storage/v1/object/calendar/arts.ics", content=body.encode(),
                       headers={"Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
                                "Content-Type": "text/calendar", "x-upsert": "true"}, timeout=30)
        print("uploaded calendar:", r.status_code)
    print(f"wrote {len(events)} events to {out_path}")


def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "load-sources":
        cmd_load_sources(rest[0] if rest else "sql/seed_sources.csv")
    elif cmd == "fetch":
        cmd_fetch()
    elif cmd == "extract":
        cmd_extract()
    elif cmd == "verify":
        cmd_verify()
    elif cmd == "calendar":
        cmd_calendar()
    elif cmd == "daily":
        cmd_fetch(); cmd_extract(); cmd_verify(); cmd_calendar()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
