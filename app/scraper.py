"""Newspaper collector (the papers are listed in sources.py).

Discovery uses each publisher's own sitemaps, which robots.txt advertises:
  * the Google News sitemap - last ~48h, with titles (used by the scheduled runs)
  * a daily or monthly archive sitemap - URL (+ lastmod) only (used for backfill)
Article text comes from the page's JSON-LD NewsArticle block (Prothom Alo) or the paper's article-text block.
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
from .sources import SOURCES, Source, section_of, source_for_url, title_from_url
from .text import crime_signal, normalize

log = logging.getLogger(__name__)
DHAKA_TZ = ZoneInfo("Asia/Dhaka")
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "n": "http://www.google.com/schemas/sitemap-news/0.9"}

# Sections that are almost always crime news (any paper)
CRIME_SECTIONS = set().union(*(s.crime_sections for s in SOURCES.values()))
# Not articles (no text to read)
NON_ARTICLE_SECTIONS = {"video", "videos", "photo", "photos", "gallery", "amp", "topic", "tags", "author", "https:", "http:"}
# District-news sections: a bare "ঢাকা" there is not the capital
DISTRICT_SECTIONS = {"bangladesh/district", "whole-country"}
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
            title=(u.findtext("n:news/n:title", "", NS) or "").strip() or title_from_url(loc),
            keywords=(u.findtext("n:news/n:keywords", "", NS) or "").strip(),
            published_at=parse_dt(u.findtext("n:news/n:publication_date", None, NS))))
    return out


def parse_daily_sitemap(xml: str) -> list[Candidate]:
    out = []
    for u in ET.fromstring(xml).findall("s:url", NS):
        loc = (u.findtext("s:loc", "", NS) or "").strip()
        if loc:
            out.append(Candidate(url=loc, section=section_of(loc), title=title_from_url(loc),
                                 published_at=parse_dt(u.findtext("s:lastmod", None, NS))))
    return out


def is_candidate(c: Candidate, gaz: Gazetteer) -> bool:
    """Stage 1, before download: is this sitemap entry worth downloading?

    - the paper's crime sections: always
    - any other section (sports, business, district, ...): when the title (or the headline in the URL) or keywords
      contain a crime word. A district is NOT required in the title; the full text decides (belongs_to_districts).
    - no title known (archive entry): only in the paper's title_after_download sections; checked after download
    - videos, photo galleries and other hosts (sister sites): never"""
    src = source_for_url(c.url)
    if src is None or c.section.split("/")[0] in NON_ARTICLE_SECTIONS:
        return False
    if c.section in src.crime_sections:
        return True
    if not c.title and not c.keywords:
        return c.section in src.title_after_download
    return crime_signal(f"{c.title} {c.keywords}") > 0


# Words that place a story in the capital. A bare "ঢাকা" is not enough outside the crime/capital sections
# ("ঢাকা বিভাগ", "ঢাকায় পাঠানো হয়").
CAPITAL_TERMS = [normalize(t) for t in ("রাজধানী", "ডিএমপি", "ঢাকা মহানগর")]


def belongs_to_districts(section: str, text: str, gaz: Gazetteer) -> bool:
    """Stage 2, after download: could the story be in one of the supported districts? Gemma makes the final call.
    Crime/capital sections: any supported district or place named. Other sections: a place of a supported district
    (not a referral hospital) or, outside district news, a capital term or another supported district's name."""
    if section in CRIME_SECTIONS:
        return gaz.mentions_supported(text)
    if gaz.grounded_places(text) or gaz.district_mentions(text) - {"dhaka"}:
        return True
    if section in DISTRICT_SECTIONS:
        return False
    n = normalize(text)
    return any(t in n for t in CAPITAL_TERMS)


belongs_to_dhaka = belongs_to_districts      # old name


def _clean_lines(text: str) -> str:
    return "\n".join(re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip(" ."))


def parse_article(page: str, url: str) -> Article:
    src = source_for_url(url)
    if src and src.body_selectors:
        return parse_dom_article(page, url, src)
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
    text = _clean_lines(BeautifulSoup(body, "html.parser").get_text("\n", strip=True))
    title = html.unescape(node.get("headline") or node.get("name") or "").strip()
    kw = node.get("keywords") or ""
    if isinstance(kw, list):
        kw = ", ".join(kw)
    if len(text) < 80 or not title:
        raise ValueError("article too short or missing title")
    return Article(url=node.get("url") or url, section=section_of(url), title=title, body=text[:60000],
                   published_at=parse_dt(node.get("datePublished")), keywords=kw)


def parse_dom_article(page: str, url: str, src: Source) -> Article:
    """Papers whose JSON-LD has no article text: title and date from meta/JSON-LD, text from the paper's text block
    (paragraphs only; captions, embeds, "read more" boxes and scripts dropped)."""
    soup = BeautifulSoup(page, "html.parser")
    ld: dict = {}
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or tag.get_text() or "null", strict=False)
        except (ValueError, TypeError):
            continue
        nodes = data if isinstance(data, list) else (data.get("@graph") or [data]) if isinstance(data, dict) else []
        for n in nodes:
            if isinstance(n, dict) and n.get("@type") in ("NewsArticle", "Article") and not ld:
                ld = n
    meta = {(m.get("property") or m.get("name") or "").lower(): m.get("content") or "" for m in soup.find_all("meta")}
    title = html.unescape(meta.get("og:title") or ld.get("headline") or (soup.h1.get_text(strip=True) if soup.h1 else "")).strip()
    published = parse_dt(meta.get("article:published_time") or ld.get("datePublished"))
    kw = ld.get("keywords") or meta.get("news_keywords") or meta.get("keywords") or ""
    if isinstance(kw, list):
        kw = ", ".join(kw)
    blocks = [el for sel in src.body_selectors for el in soup.select(sel)]
    parts = []
    for el in blocks:
        for junk in el.select("script, style, figure, figcaption, iframe, aside, noscript, .ad, .advertisement"):
            junk.decompose()
        paras = el.find_all(["p", "h2", "h3", "li"])
        parts.append("\n".join(p.get_text(" ", strip=True) for p in paras) if paras else el.get_text("\n", strip=True))
    text = _clean_lines("\n".join(parts))
    if len(text) < 80 or not title:
        raise ValueError("article too short or missing title")
    return Article(url=url, section=section_of(url), title=title, body=text[:60000], published_at=published,
                   keywords=html.unescape(kw))


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


class NewsClient:
    """One paper's lane: its own robots.txt, host allowlist and one-request-per-second pace."""

    def __init__(self, source: Source | str = "prothomalo", client: httpx.Client | None = None,
                 delay: float | None = None):
        self.source = SOURCES[source] if isinstance(source, str) else source
        self._months: dict[str, list[Candidate]] = {}
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
            if urlsplit(url).scheme != "https" or host not in self.source.hosts:
                raise FetchBlocked(f"host not allowed: {url}")
            if not self.allowed(url):
                raise FetchBlocked(f"robots.txt disallows {url}")
            self._pace()
            r = self._download(url, MAX_BYTES)
            if r.is_redirect:
                url = urljoin(url, r.headers.get("location", ""))
                continue
            r.raise_for_status()
            return r.text
        raise FetchBlocked(f"too many redirects: {url}")

    def _pace(self):
        """One request per second to the publisher, robots.txt included."""
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def allowed(self, url: str) -> bool:
        """RFC 9309: follow up to 5 same-site redirects; 4xx = no restrictions; 5xx, unreachable or a redirect loop
        = crawl nothing this run (the slot is retried later)."""
        if self._robots is None:
            target = self.source.url("/robots.txt")
            policy = RobotsPolicy(disallow_all=True)
            try:
                for _ in range(6):
                    if (urlsplit(target).hostname or "").lower() not in self.source.hosts:
                        break
                    self._pace()
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
                log.warning("%s: robots.txt unavailable; not crawling this run", self.source.key)
            self._robots = policy
        return self._robots.can_fetch(url)

    def news_sitemap(self) -> list[Candidate]:
        return parse_news_sitemap(self._get(self.source.url(self.source.news_sitemap)))

    def _archive(self, path: str) -> list[Candidate]:
        try:
            return parse_daily_sitemap(self._get(self.source.url(path)))
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise

    def daily_sitemap(self, day: date) -> list[Candidate]:
        """The archive entries for one day: the day's own file, or (monthly archives) the month's file read once and
        filtered by lastmod. lastmod is never before publication, so a story published that day is listed on that day
        or later; monthly days are approximate (the window check after download is exact)."""
        if self.source.archive == "daily":
            return self._archive(self.source.archive_path.format(day=day.isoformat()))
        if self.source.archive == "monthly":
            month = day.replace(day=1).isoformat()
            if month not in self._months:
                self._months[month] = self._archive(self.source.archive_path.format(month=month))
            return [c for c in self._months[month]
                    if c.published_at is None or c.published_at.astimezone(DHAKA_TZ).date() == day]
        return []

    def article(self, url: str) -> Article:
        return parse_article(self._get(url), url)


ProthomAloClient = NewsClient          # old name: NewsClient() defaults to Prothom Alo
