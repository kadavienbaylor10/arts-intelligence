"""Database access (psycopg 3). All writes go through here."""
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from .config import DATABASE_URL


@contextmanager
def connect():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False) as conn:
        yield conn


def sources_due(conn, limit):
    return conn.execute("""
        SELECT s.*, p.state_code FROM sources s LEFT JOIN places p ON p.id = s.place_id
        WHERE s.active AND s.fetch_method <> 'MANUAL' AND coalesce(s.robots_allowed, TRUE)
          AND (s.last_fetched_at IS NULL OR s.last_fetched_at + s.check_every < now())
        ORDER BY s.last_fetched_at NULLS FIRST LIMIT %s""", (limit,)).fetchall()


def record_fetch(conn, source, url, status, text, changed, content_hash, robots_allowed):
    snap = conn.execute("""
        INSERT INTO source_snapshots (source_id, url, http_status, content_hash, clean_text, changed)
        VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
        (source["id"], url, status, content_hash, text if changed else None, changed)).fetchone()
    conn.execute("""
        UPDATE sources SET last_fetched_at = now(), robots_allowed = coalesce(%s, robots_allowed),
          consecutive_failures = 0, last_content_hash = %s,
          last_changed_at = CASE WHEN %s THEN now() ELSE last_changed_at END
        WHERE id = %s""", (robots_allowed, content_hash, changed, source["id"]))
    return snap["id"]


def record_failure(conn, source_id, err):
    conn.execute("""UPDATE sources SET last_fetched_at = now(), consecutive_failures = consecutive_failures + 1,
                    active = consecutive_failures + 1 < 5, last_error = %s WHERE id = %s""",
                 (str(err)[:300], source_id))


def snapshots_to_extract(conn, limit):
    return conn.execute("""
        SELECT sn.*, s.tier, s.name AS source_name, p.state_code
        FROM source_snapshots sn JOIN sources s ON s.id = sn.source_id
        LEFT JOIN places p ON p.id = s.place_id
        WHERE sn.changed AND sn.clean_text IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.snapshot_id = sn.id)
          AND NOT EXISTS (SELECT 1 FROM job_runs j WHERE j.job = 'extract:' || sn.id)
        ORDER BY sn.fetched_at DESC LIMIT %s""", (limit,)).fetchall()


def get_or_create_place(conn, city, state_code):
    if not state_code:
        return None
    kind, name = ("city", city) if city else ("state", state_code)
    if kind == "state":   # state rows are matched by code (names may be 'Texas' or 'TX')
        row = conn.execute("SELECT id FROM places WHERE state_code=%s AND place_kind='state' ORDER BY is_target DESC LIMIT 1",
                           (state_code,)).fetchone()
    else:
        row = conn.execute("SELECT id FROM places WHERE lower(name)=lower(%s) AND state_code=%s AND place_kind='city'",
                           (name, state_code)).fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO places (name, place_kind, state_code) VALUES (%s,%s,%s) RETURNING id",
                        (name, kind, state_code)).fetchone()["id"]


def get_or_create_org(conn, name, org_type="unknown", website=None):
    if not name:
        return None
    row = conn.execute("SELECT id FROM organizations WHERE lower(name)=lower(%s) LIMIT 1", (name,)).fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO organizations (name, org_type, website) VALUES (%s,%s,%s) RETURNING id",
                        (name, org_type, website)).fetchone()["id"]


def find_by_fingerprint(conn, fp):
    return conn.execute("SELECT * FROM opportunities WHERE fingerprint=%s AND duplicate_of IS NULL", (fp,)).fetchone()


def insert_opportunity(conn, cols: dict):
    keys = list(cols)
    return conn.execute(
        f"INSERT INTO opportunities ({','.join(keys)}) VALUES ({','.join(['%s']*len(keys))}) RETURNING id",
        [cols[k] for k in keys]).fetchone()["id"]


def update_opportunity(conn, opp_id, cols: dict, snapshot_id):
    """Update changed columns and log each change for alerts."""
    old = conn.execute("SELECT * FROM opportunities WHERE id=%s", (opp_id,)).fetchone()
    changed = {k: v for k, v in cols.items() if v is not None and str(old.get(k)) != str(v)}
    for k, v in changed.items():
        conn.execute("""INSERT INTO opportunity_changes (opportunity_id, field_name, old_value, new_value, snapshot_id)
                        VALUES (%s,%s,%s,%s,%s)""", (opp_id, k, str(old.get(k)), str(v), snapshot_id))
    if changed:
        sets = ",".join(f"{k}=%s" for k in changed)
        conn.execute(f"UPDATE opportunities SET {sets}, updated_at=now() WHERE id=%s", [*changed.values(), opp_id])
    return changed


def add_claim(conn, opp_id, field, fld, snapshot_id, model):
    """Insert a new claim and mark earlier claims for the same field as superseded."""
    span = fld.get("span") or (None, None)
    cid = conn.execute("""
        INSERT INTO claims (entity_table, entity_id, field_name, value_text, value_json, confidence,
                            snapshot_id, quote, quote_start, quote_end, extracted_by, model)
        VALUES ('opportunities',%s,%s,%s,%s,%s,%s,%s,%s,%s,'AGENT',%s) RETURNING id""",
        (opp_id, field, fld.get("value"), Json(fld), fld.get("confidence", "UNKNOWN"),
         snapshot_id, fld.get("quote"), span[0], span[1], model)).fetchone()["id"]
    conn.execute("""UPDATE claims SET superseded_by = %s WHERE entity_table='opportunities' AND entity_id=%s
                    AND field_name=%s AND superseded_by IS NULL AND id <> %s""", (cid, opp_id, field, cid))
    return cid


def upsert_deadline(conn, opp_id, kind, due_at, tz, confidence, claim_id):
    conn.execute("DELETE FROM deadlines WHERE opportunity_id=%s AND kind=%s", (opp_id, kind))
    conn.execute("""INSERT INTO deadlines (opportunity_id, kind, due_at, local_timezone, confidence, claim_id)
                    VALUES (%s,%s,%s,%s,%s,%s)""", (opp_id, kind, due_at, tz, confidence, claim_id))


def replace_milestones(conn, opp_id, milestones, compressed):
    conn.execute("DELETE FROM milestones WHERE opportunity_id=%s AND auto_generated AND completed_at IS NULL", (opp_id,))
    for m in milestones:
        conn.execute("""INSERT INTO milestones (opportunity_id, name, due_date, sequence, compressed)
                        VALUES (%s,%s,%s,%s,%s)""", (opp_id, m["name"], m["due_date"], m["sequence"], compressed))


def log_job(conn, job, status, items_in=0, items_out=0, tin=0, tout=0, cost=0.0, error=None):
    conn.execute("""INSERT INTO job_runs (job, finished_at, status, items_in, items_out, llm_input_tokens,
                    llm_output_tokens, est_cost_usd, error) VALUES (%s, now(), %s,%s,%s,%s,%s,%s,%s)""",
                 (job, status, items_in, items_out, tin, tout, cost, error))
