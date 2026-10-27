"""Newspaper registry: everything that differs between publishers lives here.

Each source has its own hosts, robots.txt, 1-request-per-second lane, sitemaps and article-text location. Verified live
on 27 Oct 2026 with our User-Agent: robots allows us, the news sitemap has titles, and the text block below holds the
article. A source whose site changes (403, new template) is switched off with SOURCES_DISABLED=key1,key2.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class Source:
    key: str
    name_bn: str
    name_en: str
    base: str                                   # https://host (robots.txt lives here)
    hosts: frozenset[str]
    news_sitemap: str                           # path; Google News sitemap with titles
    archive: str | None = None                  # "daily" | "monthly" | None
    archive_path: str = ""                      # with {day} or {month} (YYYY-MM-01)
    body_selectors: tuple[str, ...] = ()        # empty = JSON-LD articleBody (Prothom Alo)
    crime_sections: frozenset[str] = frozenset()        # always worth downloading
    title_after_download: frozenset[str] = frozenset()  # untitled archive entries downloaded in these sections
    sections_in_path: bool = True               # False: URLs carry no section (numeric id + slug)
    title_in_url: bool = False                  # the URL slug is the headline (usable when a sitemap has no title)

    def url(self, path: str) -> str:
        return self.base + path


SOURCES: dict[str, Source] = {s.key: s for s in [
    Source("prothomalo", "প্রথম আলো", "Prothom Alo", "https://www.prothomalo.com",
           frozenset({"www.prothomalo.com", "prothomalo.com"}), "/news_sitemap.xml",
           archive="daily", archive_path="/sitemap/sitemap-daily-{day}.xml",
           crime_sections=frozenset({"bangladesh/crime", "bangladesh/capital"}),
           title_after_download=frozenset({"bangladesh", "bangladesh/district", "politics"})),
    Source("samakal", "সমকাল", "Samakal", "https://samakal.com", frozenset({"samakal.com", "www.samakal.com"}),
           "/news_sitemap.xml", archive="daily", archive_path="/sitemap/sitemap-daily-{day}.xml",
           body_selectors=("#contentDetails",), title_in_url=True,
           title_after_download=frozenset({"bangladesh", "capital", "whole-country"})),
    Source("ittefaq", "ইত্তেফাক", "Ittefaq", "https://www.ittefaq.com.bd",
           frozenset({"www.ittefaq.com.bd", "ittefaq.com.bd"}), "/news-sitemap.xml",
           archive="monthly", archive_path="/{month}.xml", body_selectors=(".jw_article_body",),
           sections_in_path=False, title_in_url=True),
    Source("banglatribune", "বাংলা ট্রিবিউন", "Bangla Tribune", "https://www.banglatribune.com",
           frozenset({"www.banglatribune.com", "banglatribune.com"}), "/news-sitemap.xml",
           archive="monthly", archive_path="/archive_{month}.xml", body_selectors=(".jw_article_body",),
           crime_sections=frozenset({"law-and-crime"}), title_in_url=True,
           title_after_download=frozenset({"country", "national"})),
    Source("ajkerpatrika", "আজকের পত্রিকা", "Ajker Patrika", "https://www.ajkerpatrika.com",
           frozenset({"www.ajkerpatrika.com", "ajkerpatrika.com"}), "/news-sitemap.xml",
           archive="daily", archive_path="/sitemap/{day}.xml", body_selectors=(".block-full_richtext",),
           title_after_download=frozenset({"bangladesh", "national"})),
    Source("deshrupantor", "দেশ রূপান্তর", "Desh Rupantor", "https://www.deshrupantor.com",
           frozenset({"www.deshrupantor.com", "deshrupantor.com"}), "/news-sitemap.xml",
           archive="monthly", archive_path="/{month}.xml", body_selectors=(".jw_article_body",),
           sections_in_path=False, title_in_url=True),
]}


def enabled_sources() -> list[Source]:
    off = {x.strip() for x in os.getenv("SOURCES_DISABLED", "").split(",") if x.strip()}
    return [s for s in SOURCES.values() if s.key not in off]


def source_for_url(url: str) -> Source | None:
    host = (urlsplit(url).hostname or "").lower()
    return next((s for s in SOURCES.values() if host in s.hosts), None)


def section_of(url: str) -> str:
    """The URL's section ("bangladesh/crime", "capital", "law-and-crime"); "" when the site has none."""
    src = source_for_url(url)
    parts = [p for p in urlsplit(url).path.split("/") if p]
    if src is None:
        return (urlsplit(url).scheme or "") + ":"       # not one of ours (e.g. a sister site)
    if not src.sections_in_path or not parts:
        return ""
    if len(parts) >= 3 and not parts[1].isdigit() and parts[1] != "article":
        return "/".join(parts[:2])
    return parts[0]


def title_from_url(url: str) -> str:
    """The headline some sites put in the URL slug ("/817537/স্ত্রীকে-হত্যা-..."), for untitled archive entries."""
    src = source_for_url(url)
    if not src or not src.title_in_url:
        return ""
    slug = unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    return "" if slug.isascii() else slug.replace("-", " ").strip()


def publisher_names(url: str | None) -> tuple[str | None, str | None]:
    src = source_for_url(url or "")
    return (src.name_bn, src.name_en) if src else (None, None)
