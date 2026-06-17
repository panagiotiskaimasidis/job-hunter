"""Remotive public API scraper — remote engineering jobs, EU-friendly.

Remotive publishes a free JSON API with no auth required.
Descriptions are included in the API response, so no second fetch is needed.
"""

import hashlib
import logging
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from scraper.base import BaseJobScraper, JobPosting

logger = logging.getLogger(__name__)

_API = "https://remotive.com/api/remote-jobs"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}
_US_ONLY = {"usa only", "us only", "canada only", "us, canada", "north america only"}


class RemotiveScraper(BaseJobScraper):
    source_name = "remotive"

    def search_stubs(self, query: str, location: str) -> list[JobPosting]:
        """Returns complete postings — descriptions come directly from the API."""
        stubs: list[JobPosting] = []
        try:
            resp = httpx.get(
                _API,
                params={"search": query, "limit": self.max_jobs * 2},
                headers=_HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            jobs_data = resp.json().get("jobs", [])

            for j in jobs_data:
                candidate_loc = (j.get("candidate_required_location") or "").lower()
                # Skip jobs explicitly restricted to North America
                if any(kw in candidate_loc for kw in _US_ONLY):
                    continue

                desc_html = j.get("description") or ""
                desc = (
                    BeautifulSoup(desc_html, "html.parser")
                    .get_text(separator="\n", strip=True)[:3000]
                    if desc_html
                    else ""
                )

                jid = hashlib.md5(f"remotive-{j['id']}".encode()).hexdigest()[:12]
                stubs.append(
                    JobPosting(
                        title=j.get("title") or "",
                        company=j.get("company_name") or "Unknown",
                        location=j.get("candidate_required_location") or "Remote",
                        description=desc,
                        url=j.get("url") or "",
                        source=self.source_name,
                        salary=j.get("salary") or "",
                        job_id=jid,
                    )
                )
                if len(stubs) >= self.max_jobs:
                    break

        except Exception as exc:
            logger.warning("[remotive] API call failed: %s", exc)

        return stubs

    def fetch_description(self, url: str) -> str:
        """Fallback fetch — only called if description was empty in the API response."""
        try:
            resp = httpx.get(url, headers=_HEADERS, timeout=20, follow_redirects=True)
            soup = BeautifulSoup(resp.text, "html.parser")
            div = soup.select_one("div.job-description") or soup.select_one("main")
            return div.get_text(separator="\n", strip=True)[:3000] if div else ""
        except Exception as exc:
            logger.debug("[remotive] fetch_description failed %s: %s", url, exc)
            return ""

    def search(self, query: str, location: str) -> Iterator[JobPosting]:
        """Legacy fallback path."""
        for stub in self.search_stubs(query, location):
            if not stub.description:
                stub.description = self.fetch_description(stub.url)
            if stub.description:
                yield stub
