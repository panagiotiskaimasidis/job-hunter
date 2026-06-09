"""
LinkedIn job scraper — optimised for speed.

Two-phase approach:
1. search_stubs()  — hits the search page once, collects all job cards quickly (no description)
2. fetch_description() — fetches one job page; called in parallel by the runner

This means 15 jobs that used to take 15 × 7s = 105s now take ~7s (all parallel).
"""

import hashlib
import time
import logging
from typing import Iterator
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from scraper.base import BaseJobScraper, JobPosting

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class LinkedInScraper(BaseJobScraper):
    source_name = "linkedin"

    def search_stubs(self, query: str, location: str) -> list[JobPosting]:
        """
        Hit the search page once and return lightweight stubs (no description).
        Very fast — single HTTP request per query/location pair.
        """
        params = {
            "keywords": query,
            "location": location,
            "f_TPR": "r86400",  # last 24 hours
            "position": 1,
            "pageNum": 0,
        }
        search_url = f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"
        stubs = []

        try:
            with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
                resp = client.get(search_url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.select("div.base-card") or soup.select("li.jobs-search-results__list-item")

                for card in cards[:self.max_jobs]:
                    try:
                        title_el   = card.select_one("h3.base-search-card__title") or card.select_one("h3")
                        company_el = card.select_one("h4.base-search-card__subtitle") or card.select_one("h4")
                        loc_el     = card.select_one("span.job-search-card__location")
                        link_el    = card.select_one("a.base-card__full-link") or card.select_one("a")

                        if not (title_el and link_el):
                            continue

                        title   = title_el.get_text(strip=True)
                        company = company_el.get_text(strip=True) if company_el else "Unknown"
                        loc     = loc_el.get_text(strip=True) if loc_el else location
                        url     = link_el.get("href", "").split("?")[0]

                        if not url.startswith("http"):
                            continue

                        job_id = hashlib.md5(f"{title}{company}{loc}".encode()).hexdigest()[:12]
                        stubs.append(JobPosting(
                            title=title, company=company, location=loc,
                            description="",   # filled in later by fetch_description
                            url=url, source=self.source_name, job_id=job_id,
                        ))
                    except Exception as exc:
                        logger.debug("[linkedin] Card parse error: %s", exc)

        except Exception as exc:
            logger.warning("[linkedin] Search failed for '%s' in '%s': %s", query, location, exc)

        return stubs

    def fetch_description(self, url: str) -> str:
        """Fetch full job description from a single LinkedIn job page."""
        try:
            with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                desc = (
                    soup.select_one("div.show-more-less-html__markup")
                    or soup.select_one("div.description__text")
                    or soup.select_one("section.description")
                )
                return desc.get_text(separator="\n", strip=True)[:5000] if desc else ""
        except Exception as exc:
            logger.debug("[linkedin] fetch_description failed for %s: %s", url, exc)
            return ""

    # ── Legacy path (used by safe_search fallback) ─────────────────────────
    def search(self, query: str, location: str) -> Iterator[JobPosting]:
        stubs = self.search_stubs(query, location)
        for stub in stubs:
            stub.description = self.fetch_description(stub.url)
            time.sleep(self.delay)
            yield stub
