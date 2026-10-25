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
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import date, datetime
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
# Sections never worth classifying
SKIP_PREFIXES = ("video/", "photo/", "opinion/", "sports/", "entertainment/", "lifestyle/", "chakri/",
                 "religion/", "education/", "technology/", "onnoalo/", "world/", "business/", "amp/",
                 "feature/", "special-supplement/", "topic/", "author/")
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
    """Cheap pre-filter: which sitemap entries are worth downloading."""
    if c.section.startswith(SKIP_PREFIXES) or c.section in {"video", "photo"}:
        return False
    if c.section in CRIME_SECTIONS:
        return True
    if not c.title and not c.keywords:
        return False  # daily sitemap entry outside the crime/capital sections
    meta = f"{c.title} {c.keywords}"
    if c.section == "bangladesh/district":
        # District news: only Dhaka-district places (Savar, Keraniganj, ...) count, not "ঢাকা বিভাগ"
        return crime_signal(meta) > 0 and bool(gaz.find_all(meta))
    return crime_signal(meta) > 0 and gaz.mentions_dhaka(meta)


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


class ProthomAloClient:
    def __init__(self, client: httpx.Client | None = None, delay: float | None = None):
        self.http = client or httpx.Client(headers={"User-Agent": settings.user_agent, "Accept-Language": "bn,en"},
                                           timeout=30, follow_redirects=True)
        self.delay = settings.request_delay if delay is None else delay
        self._robots: urllib.robotparser.RobotFileParser | None = None
        self._last = 0.0

    def _get(self, url: str) -> str:
        if not self.allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        r = self.http.get(url)
        r.raise_for_status()
        if len(r.content) > MAX_BYTES:
            raise ValueError("response too large")
        return r.text

    def allowed(self, url: str) -> bool:
        if self._robots is None:
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.parse(self.http.get(f"{BASE}/robots.txt").text.splitlines())
            except httpx.HTTPError:
                rp.parse([])
            self._robots = rp
        return self._robots.can_fetch(settings.user_agent, url)

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
