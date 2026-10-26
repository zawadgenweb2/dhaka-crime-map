"""Prothom Alo (Bangla) collector.

Discovery uses the publisher's own sitemaps, which robots.txt advertises:
  * news_sitemap.xml   - last ~48h, with title + keywords (used by the scheduled runs)
  * sitemap-daily-YYYY-MM-DD.xml - one per day, URL + section only (used for backfill)
Article text comes from the page's JSON-LD NewsArticle block.
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET

from .config import settings
from .gazetteer import Gazetteer
from .text import crime_signal

log = logging.getLogger(__name__)
DHAKA_TZ = ZoneInfo("Asia/Dhaka")
BASE = "https://www.prothomalo.com"
NEWS_SITEMAP = f"{BASE}/news_sitemap.xml"
DAILY_SITEMAP = f"{BASE}/sitemap/sitemap-daily-{{day}}.xml"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "n": "http://www.google.com/schemas/sitemap-news/0.9"}

# Sections that are almost always crime or Dhaka news
CRIME_SECTIONS = {"bangladesh/crime", "bangladesh/capital"}
# Not articles (no text to read)
NON_ARTICLE_PREFIXES = ("video/", "photo/", "amp/", "topic/", "author/")
# Daily sitemaps list URLs without titles. In these sections the title is read after download (backfills).
TITLE_AFTER_DOWNLOAD = {"bangladesh", "bangladesh/district", "politics"}
MAX_BYTES = 8 * 1024 * 1024


@dataclass
class Candidate:
    url: str
    section: str
    title: str = ""
    keywords: str = ""
    published_at: datetime | None = None


@dataclass
class Article:
    url: str
    section: str
    title: str
    body: str
    published_at: datetime | None
    keywords: str = ""
    extra: dict = field(default_factory=dict)


def section_of(url: str) -> str:
    path = url.split("prothomalo.com/", 1)[-1].strip("/")
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) >= 3 else parts[0]


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=DHAKA_TZ)


def parse_news_sitemap(xml: str) -> list[Candidate]:
    out = []
    for u in ET.fromstring(xml).findall("s:url", NS):
        loc = (u.findtext("s:loc", "", NS) or "").strip()
        if not loc:
            continue
        out.append(Candidate(
            url=loc, section=section_of(loc),
            title=(u.findtext("n:news/n:title", "", NS) or "").strip(),
            keywords=(u.findtext("n:news/n:keywords", "", NS) or "").strip(),
            published_at=parse_dt(u.findtext("n:news/n:publication_date", None, NS))))
    return out


def parse_daily_sitemap(xml: str) -> list[Candidate]:
    out = []
    for u in ET.fromstring(xml).findall("s:url", NS):
        loc = (u.findtext("s:loc", "", NS) or "").strip()
        if loc:
            out.append(Candidate(url=loc, section=section_of(loc),
                                 published_at=parse_dt(u.findtext("s:lastmod", None, NS))))
    return out


def is_candidate(c: Candidate, gaz: Gazetteer) -> bool:
    """Stage 1, before download: is this sitemap entry worth downloading?

    - crime and capital sections: always
    - any other section (sports, business, district, ...): when the title or keywords contain a crime word.
      Dhaka is NOT required in the title; the full text decides that after download (belongs_to_dhaka).
    - no title known (daily-sitemap entry): only in TITLE_AFTER_DOWNLOAD sections; the title is checked after download
    - videos, photo galleries and Prothom Alo's sister sites (other hosts): never"""
    if (urlsplit(c.url).hostname or "").lower() not in ALLOWED_HOSTS:
        return False
    if c.section.startswith(NON_ARTICLE_PREFIXES) or c.section in {"video", "photo"}:
        return False
    if c.section in CRIME_SECTIONS:
        return True
    if not c.title and not c.keywords:
        return c.section in TITLE_AFTER_DOWNLOAD
    return crime_signal(f"{c.title} {c.keywords}") > 0


def belongs_to_dhaka(section: str, text: str, gaz: Gazetteer) -> bool:
    """Stage 2, after download: does the full text place it in Dhaka district? District news must name a
    Dhaka-district place (Savar, Keraniganj, ...): a bare "ঢাকা" there is usually "ঢাকা মেডিকেলে পাঠানো হয়"."""
    if section == "bangladesh/district":
        return bool(gaz.find_all(text))
    return gaz.mentions_dhaka(text)


def parse_article(page: str, url: str) -> Article:
    soup = BeautifulSoup(page, "html.parser")
    node: dict = {}
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or tag.get_text() or "null")
        except (ValueError, TypeError):
            continue
        for n in data if isinstance(data, list) else [data]:
            if isinstance(n, dict) and n.get("@type") in ("NewsArticle", "Article") and n.get("articleBody"):
                if not node or n.get("@type") == "NewsArticle":
                    node = n
    if not node:
        raise ValueError("no JSON-LD article body")
    body = node["articleBody"]
    for _ in range(3):  # Prothom Alo double-escapes the HTML
        decoded = html.unescape(body)
        if decoded == body:
            break
        body = decoded
    text = BeautifulSoup(body, "html.parser").get_text("\n", strip=True)
    text = "\n".join(re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip(" ."))
    title = html.unescape(node.get("headline") or node.get("name") or "").strip()
    kw = node.get("keywords") or ""
    if isinstance(kw, list):
        kw = ", ".join(kw)
    if len(text) < 80 or not title:
        raise ValueError("article too short or missing title")
    return Article(url=node.get("url") or url, section=section_of(url), title=title, body=text[:60000],
                   published_at=parse_dt(node.get("datePublished")), keywords=kw)


ALLOWED_HOSTS = {"www.prothomalo.com", "prothomalo.com"}
MAX_REDIRECTS = 3
MAX_ROBOTS_BYTES = 512 * 1024


class FetchBlocked(PermissionError):
    """robots.txt, host allowlist or size limit forbids this request."""


class RobotsPolicy:
    """robots.txt per RFC 9309: group by user-agent (else '*'), longest matching rule wins, Allow wins ties,
    '*' and '$' supported, /robots.txt itself always allowed."""

    def __init__(self, rules: list[tuple[str, bool]] | None = None, allow_all: bool = False, disallow_all: bool = False):
        self.rules, self.allow_all, self.disallow_all = rules or [], allow_all, disallow_all

    @classmethod
    def parse(cls, text: str, user_agent: str) -> "RobotsPolicy":
        product = user_agent.split("/", 1)[0].strip().lower()
        groups: list[tuple[list[str], list[tuple[str, bool]]]] = []
        agents: list[str] = []
        rules: list[tuple[str, bool]] = []
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if rules:                       # a user-agent line after rules starts a new group
                    groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(value.lower())
            elif key in ("allow", "disallow") and agents:
                if value:
                    rules.append((value, key == "allow"))
        if agents:
            groups.append((agents, rules))
        mine = [r for a, r in groups if product and product in a]
        chosen = mine or [r for a, r in groups if "*" in a]
        return cls([rule for rs in chosen for rule in rs])

    @staticmethod
    def _matches(pattern: str, path: str) -> bool:
        anchored = pattern.endswith("$")
        body = re.escape(unquote(pattern[:-1] if anchored else pattern)).replace(r"\*", ".*")
        return re.match(body + ("$" if anchored else ""), path) is not None

    def can_fetch(self, url: str) -> bool:
        parts = urlsplit(url)
        path = unquote(parts.path or "/") + (f"?{unquote(parts.query)}" if parts.query else "")
        if path == "/robots.txt" or self.allow_all:
            return True
        if self.disallow_all:
            return False
        best: tuple[int, bool] | None = None
        for pattern, allow in self.rules:
            if self._matches(pattern, path):
                key = (len(pattern), allow)          # longer wins; on equal length Allow (True) wins
                if best is None or key > best:
                    best = key
        return True if best is None else best[1]


class ProthomAloClient:
    def __init__(self, client: httpx.Client | None = None, delay: float | None = None):
        # Redirects are followed manually so every hop is host- and robots-checked.
        self.http = client or httpx.Client(headers={"User-Agent": settings.user_agent, "Accept-Language": "bn,en"},
                                           timeout=30, follow_redirects=False)
        self.delay = settings.request_delay if delay is None else delay
        self._robots: RobotsPolicy | None = None
        self._last = 0.0

    def _download(self, url: str, limit: int) -> httpx.Response:
        """GET with a streamed size cap (Content-Length is not trusted)."""
        with self.http.stream("GET", url) as r:
            chunks, size = [], 0
            if not r.is_redirect:
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise FetchBlocked(f"response larger than {limit} bytes: {url}")
                    chunks.append(chunk)
            # iter_bytes() already decompressed the body: drop encoding/length headers so it isn't decoded twice.
            headers = [(k, v) for k, v in r.headers.items() if k.lower() not in ("content-encoding", "content-length")]
            return httpx.Response(r.status_code, headers=headers, content=b"".join(chunks), request=r.request)

    def _get(self, url: str) -> str:
        for _ in range(MAX_REDIRECTS + 1):
            host = (urlsplit(url).hostname or "").lower()
            if urlsplit(url).scheme != "https" or host not in ALLOWED_HOSTS:
                raise FetchBlocked(f"host not allowed: {url}")
            if not self.allowed(url):
                raise FetchBlocked(f"robots.txt disallows {url}")
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = self._download(url, MAX_BYTES)
            if r.is_redirect:
                url = urljoin(url, r.headers.get("location", ""))
                continue
            r.raise_for_status()
            return r.text
        raise FetchBlocked(f"too many redirects: {url}")

    def allowed(self, url: str) -> bool:
        """RFC 9309: follow up to 5 same-site redirects; 4xx = no restrictions; 5xx, unreachable or a redirect loop
        = crawl nothing this run (the slot is retried later)."""
        if self._robots is None:
            target = f"{BASE}/robots.txt"
            policy = RobotsPolicy(disallow_all=True)
            try:
                for _ in range(6):
                    if (urlsplit(target).hostname or "").lower() not in ALLOWED_HOSTS:
                        break
                    r = self._download(target, MAX_ROBOTS_BYTES)
                    if r.is_redirect:
                        target = urljoin(target, r.headers.get("location", ""))
                        continue
                    if 200 <= r.status_code < 300:
                        policy = RobotsPolicy.parse(r.text, settings.user_agent)
                    elif 400 <= r.status_code < 500:
                        policy = RobotsPolicy(allow_all=True)
                    break
            except (httpx.HTTPError, FetchBlocked):
                pass
            if policy.disallow_all:
                log.warning("robots.txt unavailable; not crawling this run")
            self._robots = policy
        return self._robots.can_fetch(url)

    def news_sitemap(self) -> list[Candidate]:
        return parse_news_sitemap(self._get(NEWS_SITEMAP))

    def daily_sitemap(self, day: date) -> list[Candidate]:
        try:
            return parse_daily_sitemap(self._get(DAILY_SITEMAP.format(day=day.isoformat())))
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise

    def article(self, url: str) -> Article:
        return parse_article(self._get(url), url)
