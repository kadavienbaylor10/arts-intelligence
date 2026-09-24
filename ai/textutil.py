"""Text normalization, hashing, and quote verification (pure functions, no I/O)."""
import hashlib
import re

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Collapse whitespace so hashes don't change on cosmetic edits."""
    return _WS.sub(" ", text or "").strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def _canon(s: str) -> str:
    s = s.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    return normalize(s).lower()


def locate_quote(quote: str, text: str):
    """Return (start, end) of quote inside text, tolerant of whitespace/quote-style
    differences. Returns None if the quote is not actually present.
    This is the anti-fabrication check: a claim whose quote can't be found
    in the stored snapshot is downgraded to UNKNOWN."""
    if not quote or not text:
        return None
    q = _canon(quote)
    if len(q) < 4:
        return None
    t = _canon(text)
    i = t.find(q)
    if i == -1:
        return None
    # Offsets refer to the canonicalized text; good enough for highlighting and audit.
    return i, i + len(q)


def fingerprint(issuer: str, name: str, cycle: str | None) -> str:
    def slug(x):
        x = _canon(x or "")
        x = re.sub(r"[^a-z0-9 ]", "", x)
        x = re.sub(r"\b(the|of|and|for|a|an|grant|grants|program)\b", " ", x)
        return normalize(x)
    raw = f"{slug(issuer)}|{slug(name)}|{slug(cycle or '')}"
    return hashlib.sha1(raw.encode()).hexdigest()
