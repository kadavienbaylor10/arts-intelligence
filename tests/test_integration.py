"""End-to-end test against a real Postgres (skipped unless TEST_DATABASE_URL is set).
Simulates a fetched page + model output, then runs save -> verify -> calendar."""
import os
from datetime import date

import pytest

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")

PAGE = ("Creation and Presentation Grants. Next Deadline: October 8, 2027 (new applicant intent to apply "
        "deadline 9/10/27). Grants support established nonprofit arts organizations in Wisconsin. "
        "Applicants must match each dollar with at least one dollar of non-state funds.")


def model_output():
    from ai.extractor import TEXT_FIELDS
    o = {f: {"value": None, "quote": None, "confidence": "UNKNOWN"} for f in TEXT_FIELDS}
    o.update({
        "name": {"value": "Creation and Presentation Grants", "quote": "Creation and Presentation Grants", "confidence": "CONFIRMED"},
        "issuer": {"value": "Wisconsin Arts Board", "quote": None, "confidence": "INFERRED"},
        "state_code": {"value": "WI", "quote": "nonprofit arts organizations in Wisconsin", "confidence": "CONFIRMED"},
        "opportunity_type": {"value": "grant", "quote": "Creation and Presentation Grants", "confidence": "CONFIRMED"},
        "application_deadline": {"value": "2027-10-08", "quote": "Next Deadline: October 8, 2027", "confidence": "CONFIRMED"},
        "intent_to_apply_deadline": {"value": "2027-09-10", "quote": "intent to apply deadline 9/10/27", "confidence": "CONFIRMED"},
        "match_requirement": {"value": "1:1", "quote": "match each dollar with at least one dollar", "confidence": "CONFIRMED"},
        "funding_max": {"value": "999999", "quote": "Grants up to $999,999", "confidence": "CONFIRMED"},  # fabricated
        "cycle_label": {"value": "FY2028", "quote": None, "confidence": "INFERRED"},
    })
    o.update({"mediums": ["any"], "page_says_closed": False, "page_says_canceled": False, "is_recurring": True,
              "is_capital_project_signal": False, "detail_url": None})
    return o


def test_pipeline(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", URL)
    import importlib
    from ai import config, db
    importlib.reload(config); importlib.reload(db)
    monkeypatch.setattr(db, "DATABASE_URL", URL)
    from ai import run
    from ai.extractor import verify_quotes
    from ai.textutil import content_hash

    with db.connect() as conn:
        src = conn.execute("SELECT s.*, p.state_code FROM sources s LEFT JOIN places p ON p.id=s.place_id "
                           "WHERE s.url LIKE '%%artsboard.wisconsin.gov%%'").fetchone()
        snap_id = db.record_fetch(conn, src, src["url"], 200, PAGE, True, content_hash(PAGE), True)
        snap = conn.execute("SELECT sn.*, s.tier, s.name AS source_name, p.state_code FROM source_snapshots sn "
                            "JOIN sources s ON s.id=sn.source_id LEFT JOIN places p ON p.id=s.place_id "
                            "WHERE sn.id=%s", (snap_id,)).fetchone()
        opp = verify_quotes(model_output(), PAGE)
        opp_id = run.save_opportunity(conn, opp, snap, "test-model", date(2026, 9, 24))
        conn.commit()

        o = conn.execute("SELECT * FROM opportunities WHERE id=%s", (opp_id,)).fetchone()
        assert o["funding_max"] is None                    # fabricated amount rejected
        dl = conn.execute("SELECT * FROM deadlines WHERE opportunity_id=%s AND kind='application'", (opp_id,)).fetchone()
        assert dl["confidence"] == "PROBABLE"              # date stated, time/zone assumed
        assert o["validity"] == "REQUIRES_VERIFICATION"    # not ACTIVE until time confirmed / human check
        ms = conn.execute("SELECT count(*) AS n FROM milestones WHERE opportunity_id=%s", (opp_id,)).fetchone()
        assert ms["n"] == 10

        # Re-extracting the same page must update, not duplicate
        run.save_opportunity(conn, verify_quotes(model_output(), PAGE), snap, "test-model", date(2026, 9, 24))
        conn.commit()
        n = conn.execute("SELECT count(*) AS n FROM opportunities WHERE fingerprint=%s", (o["fingerprint"],)).fetchone()
        assert n["n"] == 1

    out = tmp_path / "cal.ics"
    run.cmd_calendar(str(out))
    body = out.read_text()
    assert "Creation and Presentation Grants [VERIFY]" in body
