"""LLM extraction of opportunities from a page snapshot, with quote verification.

The model must return a verbatim quote for every value it reports. We then check
each quote against the stored page text; any quote we can't find is downgraded to
UNKNOWN. The model is never allowed to fill gaps from general knowledge.
"""
import json
from datetime import date

from .textutil import locate_quote

FIELD = {  # one extracted field = value + verbatim quote + confidence
    "type": "object",
    "properties": {
        "value": {"type": ["string", "null"]},
        "quote": {"type": ["string", "null"], "description": "Exact text copied from the page supporting the value. Null if not stated."},
        "confidence": {"type": "string", "enum": ["CONFIRMED", "PROBABLE", "INFERRED", "UNKNOWN"]},
    },
    "required": ["value", "quote", "confidence"],
}

TEXT_FIELDS = ["name", "issuer", "city", "state_code", "opportunity_type", "funding_type", "description",
               "community_served", "applicant_eligibility", "artist_eligibility", "required_partners",
               "funding_min", "funding_max", "total_project_budget", "artist_budget", "match_requirement",
               "application_deadline", "deadline_timezone", "intent_to_apply_deadline", "cycle_label",
               "project_timeline", "installation_timeline", "application_requirements",
               "contact_name", "contact_info"]

TOOL = {
    "name": "record_opportunities",
    "description": "Record every distinct funding/commission/call opportunity described on the page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "page_kind": {"type": "string", "enum": ["single_opportunity", "listing_of_opportunities",
                                                      "news_or_announcement", "not_an_opportunity"]},
            "opportunities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        **{f: FIELD for f in TEXT_FIELDS},
                        "mediums": {"type": "array", "items": {"type": "string", "enum": [
                            "sculpture", "mural", "environmental_graphics", "projection", "light", "digital",
                            "installation", "interactive", "sound", "community_engaged", "design",
                            "programming", "education", "research", "any"]}},
                        "page_says_closed": {"type": "boolean"},
                        "page_says_canceled": {"type": "boolean"},
                        "is_recurring": {"type": ["boolean", "null"]},
                        "is_capital_project_signal": {"type": "boolean",
                            "description": "True if this is a planned/funded project with no artist call yet."},
                        "detail_url": {"type": ["string", "null"]},
                    },
                    "required": TEXT_FIELDS + ["mediums", "page_says_closed", "page_says_canceled",
                                               "is_recurring", "is_capital_project_signal", "detail_url"],
                },
            },
            "promising_links": {
                "type": "array", "description": "Up to 10 links on the page likely to lead to specific calls/guidelines.",
                "items": {"type": "object", "properties": {"url": {"type": "string"}, "label": {"type": "string"}},
                          "required": ["url", "label"]},
            },
        },
        "required": ["page_kind", "opportunities", "promising_links"],
    },
}

SYSTEM = """You extract arts funding and commission opportunities from web pages for a public-art studio.
Rules:
- Use ONLY the page text provided. Never use outside knowledge to fill a field.
- For every field: copy an exact supporting quote (short, <= 30 words) from the page, or set value and quote to null with confidence UNKNOWN.
- CONFIRMED = stated explicitly on the page. PROBABLE = strongly implied by page text. INFERRED = your interpretation (quote still required if any text supports it). UNKNOWN = not on page.
- Dates: give application_deadline as ISO 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM' in the page's local time; put the time zone the page states (e.g. 'ET', 'PT', 'America/Chicago') in deadline_timezone.
- Money: plain numbers without symbols (e.g. '25000').
- If the page says a program is closed, paused, suspended, or 'check back', set page_says_closed=true.
- A listing page may contain several programs: return each one separately.
- Planned construction, bond-funded projects, or master plans that mention public art but have no open call are capital project signals.
Today's date: {today}."""


def extract(client, model: str, page_text: str, url: str, today: date, max_chars: int = 60000):
    """Returns (parsed_dict, usage). Raises on API error."""
    msg = client.messages.create(
        model=model,
        max_tokens=4000,
        system=SYSTEM.format(today=today.isoformat()),
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_opportunities"},
        messages=[{"role": "user", "content": f"URL: {url}\n\nPAGE TEXT:\n{page_text[:max_chars]}"}],
    )
    block = next(b for b in msg.content if b.type == "tool_use")
    return block.input, msg.usage


def verify_quotes(opp: dict, page_text: str) -> dict:
    """Downgrade any field whose quote isn't really on the page. Adds 'span' offsets."""
    for f in TEXT_FIELDS:
        fld = opp.get(f) or {}
        if fld.get("confidence") in ("CONFIRMED", "PROBABLE"):
            span = locate_quote(fld.get("quote") or "", page_text)
            if span is None:
                # Quote not found on the page: treat the value as ungrounded.
                fld.update({"confidence": "UNKNOWN", "quote_rejected": fld.get("quote"),
                            "value_unverified": fld.get("value"), "value": None, "quote": None})
            else:
                fld["span"] = span
        opp[f] = fld
    return opp
