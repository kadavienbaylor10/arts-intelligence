"""Polite fetching + text extraction.

Strategy per source:
  1. Plain HTTP request with complete, browser-like headers (still identifies the bot honestly).
  2. Retry once on timeouts / connection resets; retry http:// URLs as https:// on SSL errors.
  3. If the site answers with a bot-protection response (403, 202-with-challenge, 429) or the
     page needs JavaScript, fall back to a real headless browser (Playwright/Chromium).
  4. robots.txt is always respected; a disallow is never bypassed.
"""
import io
import time
import urllib.robotparser
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from .config import USER_AGENT
from .textutil import normalize

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}
BLOCK_STATUSES = {202, 403, 429, 503}
MIN_REAL_TEXT = 200          # fewer characters than this = probably a challenge/interstitial page
TIMEOUT = 45

_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}


class FetchError(Exception):
    pass


def robots_allows(url: str, client: httpx.Client) -> bool | None:
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


def looks_blocked(status: int | None, text: str) -> bool:
    if status in BLOCK_STATUSES:
        return True
    low = text[:2000].lower()
    challenge_words = ("verify you are human", "checking your browser", "enable javascript",
                       "access denied", "request unsuccessful", "attention required")
    return len(text) < MIN_REAL_TEXT or any(w in low for w in challenge_words)


def _http_get(url: str, client: httpx.Client):
    last = None
    for attempt in range(2):
        try:
            return client.get(url, timeout=TIMEOUT, follow_redirects=True)
        except httpx.ConnectError as e:
            last = e
            if "SSL" in str(e) and url.startswith("http://"):
                url = "https://" + url[len("http://"):]      # try the secure address instead
                continue
        except (httpx.TimeoutException, httpx.RemoteProtocolError) as e:
            last = e
        time.sleep(3 * (attempt + 1))
    raise FetchError(f"{type(last).__name__}: {last}")


def _parse(resp):
    ctype = resp.headers.get("content-type", "")
    if "pdf" in ctype or str(resp.url).lower().endswith(".pdf"):
        return pdf_to_text(resp.content), []
    return html_to_text_and_links(resp.text, str(resp.url))


_browser = None


def _browser_fetch(url: str):
    """Headless Chromium fallback. Returns (status, text, links, final_url) or raises."""
    global _browser
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise FetchError("headless browser not installed") from e
    if _browser is None:
        pw = sync_playwright().start()
        _browser = pw.chromium.launch(headless=True)
    page = _browser.new_page(user_agent=USER_AGENT, locale="en-US")
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT * 1000)
        page.wait_for_timeout(4000)   # let challenge pages / JS content settle
        html, final = page.content(), page.url
        status = resp.status if resp else None
    finally:
        page.close()
    text, links = html_to_text_and_links(html, final)
    return status, text, links, final


def fetch(url: str, client: httpx.Client, js: bool = False):
    """Returns dict(status, text, links, final_url, robots_allowed, via). Raises FetchError."""
    allowed = robots_allows(url, client)
    if allowed is False:
        return {"status": None, "text": "", "links": [], "final_url": url, "robots_allowed": False, "via": None}

    status, text, links, final, via = None, "", [], url, "http"
    if not js:
        try:
            r = _http_get(url, client)
            status, final = r.status_code, str(r.url)
            if status < 400 or status in BLOCK_STATUSES:
                text, links = _parse(r)
            if status == 404:
                raise FetchError("status 404 (page not found - the link needs updating)")
        except FetchError as e:
            if "404" in str(e):
                raise
            status, text = None, ""
            http_error = str(e)
        else:
            http_error = f"status {status}"
        if status and status < 400 and not looks_blocked(status, text):
            return {"status": status, "text": text, "links": links, "final_url": final,
                    "robots_allowed": allowed, "via": via}
    else:
        http_error = "page needs JavaScript"

    # Fallback: real browser
    try:
        b_status, b_text, b_links, b_final = _browser_fetch(url)
    except Exception as e:  # noqa: BLE001
        raise FetchError(f"{http_error}; browser fallback failed: {str(e)[:120]}")
    if b_status and b_status < 400 and not looks_blocked(b_status, b_text):
        return {"status": b_status, "text": b_text, "links": b_links, "final_url": b_final,
                "robots_allowed": allowed, "via": "browser"}
    raise FetchError(f"blocked by site protection ({http_error}; browser got status {b_status}). "
                     "Consider covering this source by newsletter/email instead.")


def make_client() -> httpx.Client:
    return httpx.Client(headers=BROWSER_HEADERS, http2=False)


def close_browser():
    global _browser
    if _browser is not None:
        try:
            _browser.close()
        except Exception:  # noqa: BLE001
            pass
        _browser = None
