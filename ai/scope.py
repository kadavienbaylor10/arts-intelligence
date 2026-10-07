"""Market model: your 20 target markets, and whether an opportunity is in scope.

In scope when ANY of these hold:
  - its city belongs to one of the 20 markets (including the market's main suburbs/counties)
  - it is statewide in a state that contains one of the markets
  - it is regional, national, or international in reach (multi-city)
Out of scope: a local opportunity in a city outside the markets, or a statewide one
in a state with no market.
"""
import re

MARKETS = {
    "Dallas–Fort Worth": ("TX", ["dallas", "fort worth", "arlington", "irving", "plano", "denton", "garland", "frisco", "mckinney", "grand prairie", "richardson", "dallas county", "tarrant county"]),
    "New York City": ("NY", ["new york", "new york city", "nyc", "manhattan", "brooklyn", "queens", "bronx", "staten island"]),
    "Los Angeles": ("CA", ["los angeles", "long beach", "santa monica", "pasadena", "glendale", "burbank", "west hollywood", "inglewood", "culver city", "los angeles county"]),
    "Chicago": ("IL", ["chicago", "evanston", "oak park", "cook county"]),
    "Houston": ("TX", ["houston", "pasadena", "sugar land", "the woodlands", "katy", "pearland", "harris county"]),
    "Washington, DC": ("DC", ["washington", "washington dc", "washington, dc", "district of columbia", "dc"]),
    "Philadelphia": ("PA", ["philadelphia"]),
    "Miami": ("FL", ["miami", "miami beach", "miami-dade", "miami dade", "hialeah", "coral gables", "north miami", "fort lauderdale", "broward county"]),
    "Atlanta": ("GA", ["atlanta", "decatur", "marietta", "sandy springs", "johns creek", "fulton county", "dekalb county"]),
    "Phoenix": ("AZ", ["phoenix", "tempe", "scottsdale", "mesa", "chandler", "glendale", "gilbert", "maricopa county"]),
    "San Francisco Bay Area": ("CA", ["san francisco", "oakland", "san jose", "berkeley", "palo alto", "richmond", "fremont", "santa clara", "sunnyvale", "walnut creek", "alameda county", "santa clara county", "bay area"]),
    "Seattle": ("WA", ["seattle", "bellevue", "tacoma", "redmond", "everett", "king county"]),
    "Denver": ("CO", ["denver", "aurora", "lakewood", "boulder"]),
    "Austin": ("TX", ["austin", "round rock", "travis county"]),
    "Raleigh–Durham": ("NC", ["raleigh", "durham", "chapel hill", "cary", "carrboro", "orange county", "wake county", "research triangle"]),
    "Nashville": ("TN", ["nashville", "murfreesboro", "franklin", "davidson county"]),
    "Orlando": ("FL", ["orlando", "winter park", "kissimmee", "orange county"]),
    "San Antonio": ("TX", ["san antonio", "bexar county"]),
    "Las Vegas": ("NV", ["las vegas", "henderson", "north las vegas", "clark county"]),
    "New Orleans": ("LA", ["new orleans", "metairie", "jefferson parish", "orleans parish"]),
}
MARKET_STATES = sorted({st for st, _ in MARKETS.values()})
WIDE_SCOPES = {"REGIONAL", "NATIONAL", "INTERNATIONAL"}


def _norm(s):
    s = (s or "").lower().replace("–", "-").strip()
    s = re.sub(r",?\s+(tx|ny|ca|il|dc|pa|fl|ga|az|wa|co|nc|tn|nv|la)$", "", s)
    return re.sub(r"\s+", " ", s)


def market_for(city, state_code):
    """Return the market name a city belongs to, or None."""
    c = _norm(city)
    if not c:
        return None
    for name, (st, aliases) in MARKETS.items():
        if state_code and state_code.upper() != st:
            continue
        if c == _norm(name) or c in aliases:
            return name
    return None


def normalize_scope(raw):
    r = (raw or "").strip().upper()
    for s in ("INTERNATIONAL", "NATIONAL", "REGIONAL", "STATE", "LOCAL"):
        if s in r:
            return s
    if "STATEWIDE" in r:
        return "STATE"
    return None


def classify(city, state_code, scope_raw, source_place_kind=None):
    """Return (market or None, scope, in_scope: True/False/None).
    None means unknown: kept visible but flagged for review."""
    scope = normalize_scope(scope_raw)
    market = market_for(city, state_code)
    st = (state_code or "").upper()
    if market:
        return market, scope or "LOCAL", True
    if scope in WIDE_SCOPES:
        return None, scope, True
    if scope == "STATE" or (not city and source_place_kind == "state"):
        return None, "STATE", (st in MARKET_STATES) if st else None
    if city and st:
        return None, scope or "LOCAL", False
    if not city and not st:
        # national/regional source page with no stated geography
        return None, scope, None
    if not city and st:
        return None, scope or "STATE", st in MARKET_STATES
    return None, scope, None
