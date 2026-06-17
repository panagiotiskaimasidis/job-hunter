"""Welcome to the Jungle (WTTJ) scraper — Europe's biggest startup/engineering job board.

Two-phase approach:
1. search_stubs() — hits the search page, tries to extract job cards from __NEXT_DATA__
   JSON blob; falls back to HTML card parsing.
2. fetch_description() — loads the individual job page and extracts description from
   __NEXT_DATA__ or visible HTML.
"""

import hashlib
import json
import logging
from typing import Iterator
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from scraper.base import BaseJobScraper, JobPosting

logger = logging.getLogger(__name__)

_BASE = "https://www.welcometothejungle.com"
_SEARCH = f"{_BASE}/en/jobs"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class WttjScraper(BaseJobScraper):
    source_name = "wttj"

    def search_stubs(self, query: str, location: str) -> list[JobPosting]:
        params: dict = {"query": query, "page": 1}
        loc_lower = (location or "").lower()
        if loc_lower and loc_lower not in ("remote", "europe", "anywhere", "worldwide"):
            params["aroundQuery"] = location

        stubs: list[JobPosting] = []
        try:
            url = f"{_SEARCH}?{urlencode(params)}"
            resp = httpx.get(url, headers=_HEADERS, timeout=25, follow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # ── Try __NEXT_DATA__ JSON first ────────────────────────────────
            script = soup.find("script", {"id": "__NEXT_DATA__"})
            if script and script.string:
                try:
                    data = json.loads(script.string)
                    page_props = data.get("props", {}).get("pageProps", {})
                    jobs_list = (
                        page_props.get("jobs")
                        or page_props.get("searchResults", {}).get("jobs")
                        or []
                    )
                    for j in jobs_list[: self.max_jobs]:
                        stub = self._from_next_data(j)
                        if stub:
                            stubs.append(stub)
                    if stubs:
                        return stubs
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass

            # ── Fallback: parse HTML job cards ──────────────────────────────
            cards = (
                soup.select("article[data-testid]")
                or soup.select("li[data-testid]")
                or soup.select("article")
                or soup.select("div.job-card")
            )
            for card in cards[: self.max_jobs]:
                stub = self._from_card(card, location)
                if stub:
                    stubs.append(stub)

        except Exception as exc:
            logger.warning("[wttj] search_stubs('%s', '%s') failed: %s", query, location, exc)

        return stubs

    def _from_next_data(self, j: dict) -> "JobPosting | None":
        try:
            org = j.get("organization") or {}
            office = j.get("office") or {}
            slug = j.get("slug") or ""
            org_slug = org.get("slug") or ""
            url = (
                f"{_BASE}/en/companies/{org_slug}/jobs/{slug}"
                if slug and org_slug
                else ""
            )
            loc = office.get("city") or office.get("country") or "Europe"
            jid = hashlib.md5(f"wttj-{j.get('id', slug)}".encode()).hexdigest()[:12]
            return JobPosting(
                title=j.get("name") or "",
                company=org.get("name") or "Unknown",
                location=loc,
                description="",
                url=url,
                source=self.source_name,
                job_id=jid,
            )
        except Exception as exc:
            logger.debug("[wttj] _from_next_data failed: %s", exc)
            return None

    def _from_card(self, card, default_location: str) -> "JobPosting | None":
        try:
            title_el = (
                card.select_one("h3")
                or card.select_one("h2")
                or card.select_one("[data-testid='job-name']")
            )
            company_el = (
                card.select_one("[data-testid='company-name']")
                or card.select_one("[class*='company']")
            )
            location_el = (
                card.select_one("[data-testid='job-location']")
                or card.select_one("[class*='location']")
            )
            link_el = card.select_one("a[href*='/jobs/']") or card.select_one("a[href]")

            if not title_el or not link_el:
                return None

            href = link_el.get("href", "")
            if href.startswith("/"):
                href = _BASE + href

            title = title_el.get_text(strip=True)
            company = company_el.get_text(strip=True) if company_el else "Unknown"
            loc = location_el.get_text(strip=True) if location_el else default_location
            jid = hashlib.md5(f"wttj-{title}{company}".encode()).hexdigest()[:12]

            return JobPosting(
                title=title,
                company=company,
                location=loc,
                description="",
                url=href,
                source=self.source_name,
                job_id=jid,
            )
        except Exception as exc:
            logger.debug("[wttj] _from_card failed: %s", exc)
            return None

    def fetch_description(self, url: str) -> str:
        if not url:
            return ""
        try:
            resp = httpx.get(url, headers=_HEADERS, timeout=20, follow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Try __NEXT_DATA__ first
            script = soup.find("script", {"id": "__NEXT_DATA__"})
            if script and script.string:
                try:
                    data = json.loads(script.string)
                    job_data = (
                        data.get("props", {}).get("pageProps", {}).get("job", {}) or {}
                    )
                    desc_html = job_data.get("description") or ""
                    if desc_html:
                        return (
                            BeautifulSoup(desc_html, "html.parser")
                            .get_text(separator="\n", strip=True)[:3000]
                        )
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass

            # HTML fallback
            div = (
                soup.select_one("[data-testid='job-description']")
                or soup.select_one("div.job-description")
                or soup.select_one("section.description")
                or soup.select_one("main")
            )
            return div.get_text(separator="\n", strip=True)[:3000] if div else ""

        except Exception as exc:
            logger.debug("[wttj] fetch_description failed %s: %s", url, exc)
            return ""

    def search(self, query: str, location: str) -> Iterator[JobPosting]:
        """Legacy fallback path."""
        for stub in self.search_stubs(query, location):
            if not stub.description:
                stub.description = self.fetch_description(stub.url)
            if stub.description:
                yield stub
