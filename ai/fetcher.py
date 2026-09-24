"""Polite fetching + text extraction. Returns normalized text for snapshotting."""
import io
import urllib.robotparser
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from .config import USER_AGENT
from .textutil import normalize

_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def robots_allows(url: str, client: httpx.Client) -> bool | None:
    """True/False if robots.txt answers; None if robots.txt is unreachable (treated as allowed but recorded)."""
    root = "{0.scheme}://{0.netloc}".format(urlparse(url))
    if root not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = client.get(root + "/robots.txt", timeout=15)
            if r.status_code >= 400:
                _robots_cache[root] = None
            else:
                rp.parse(r.text.splitlines())
                _robots_cache[root] = rp
        except httpx.HTTPError:
            _robots_cache[root] = None
    rp = _robots_cache[root]
    return None if rp is None else rp.can_fetch(USER_AGENT, url)


def html_to_text_and_links(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "svg"]):
        tag.decompose()
    links = []
    for a in soup.find_all("a", href=True):
        label = normalize(a.get_text(" "))
        href = urljoin(base_url, a["href"])
        if href.startswith("http") and label:
            links.append({"url": href.split("#")[0], "label": label[:200]})
    return normalize(soup.get_text(" ")), links


def pdf_to_text(data: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return normalize(" ".join((p.extract_text() or "") for p in pdf.pages[:40]))


def fetch(url: str, client: httpx.Client):
    """Returns dict(status, text, links, final_url, robots_allowed) or raises httpx errors."""
    allowed = robots_allows(url, client)
    if allowed is False:
        return {"status": None, "text": "", "links": [], "final_url": url, "robots_allowed": False}
    r = client.get(url, timeout=30, follow_redirects=True)
    ctype = r.headers.get("content-type", "")
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        text, links = pdf_to_text(r.content), []
    else:
        text, links = html_to_text_and_links(r.text, str(r.url))
    return {"status": r.status_code, "text": text, "links": links,
            "final_url": str(r.url), "robots_allowed": allowed}


def make_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, http2=False)
