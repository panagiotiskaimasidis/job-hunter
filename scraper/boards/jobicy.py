"""Jobicy public remote-jobs API — free, no auth, geo-filterable.

Jobicy publishes remote jobs through a keyless JSON API that supports a
geo filter, letting us pull Europe-eligible remote roles with descriptions inline.

    GET https://jobicy.com/api/v2/remote-jobs?count=50&geo=europe

Docs: https://jobicy.com/jobs-rss-feed
"""

import hashlib
import logging
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from scraper.base import BaseJobScraper, JobPosting

logger = logging.getLogger(__name__)

_API = "https://jobicy.com/api/v2/remote-jobs"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
# Pull both Europe-eligible and worldwide remote roles (worldwide includes EU).
_GEOS = ["europe", "anywhere"]


class JobicyScraper(BaseJobScraper):
    source_name = "jobicy"

    def search_stubs(self, query: str, location: str) -> list[JobPosting]:
        """Ignores query/location — pulls EU-eligible remote jobs."""
        stubs: list[JobPosting] = []
        seen: set[str] = set()

        try:
            with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
                for geo in _GEOS:
                    resp = client.get(_API, params={"count": 50, "geo": geo})
                    if resp.status_code != 200:
                        continue
                    rows = resp.json().get("jobs", []) or []
                    for j in rows:
                        stub = self._parse(j)
                        if stub and stub.job_id not in seen:
                            seen.add(stub.job_id)
                            stubs.append(stub)

            logger.info("[jobicy] %d stubs", len(stubs))
        except Exception as exc:
            logger.warning("[jobicy] API call failed: %s", exc)

        return stubs

    def _parse(self, j: dict) -> "JobPosting | None":
        try:
            url = j.get("url") or ""
            if not url:
                return None
            desc_html = j.get("jobDescription") or j.get("jobExcerpt") or ""
            desc = (
                BeautifulSoup(desc_html, "html.parser").get_text(separator="\n", strip=True)[:3000]
                if desc_html else ""
            )
            jid = hashlib.md5(f"jobicy-{j.get('id', url)}".encode()).hexdigest()[:12]
            return JobPosting(
                title=j.get("jobTitle") or "",
                company=j.get("companyName") or "Unknown",
                location=j.get("jobGeo") or "Remote",
                description=desc,
                url=url,
                source=self.source_name,
                job_id=jid,
            )
        except Exception as exc:
            logger.debug("[jobicy] parse failed: %s", exc)
            return None

    def fetch_description(self, url: str) -> str:
        # Descriptions are always included in the API response.
        return ""

    def search(self, query: str, location: str) -> Iterator[JobPosting]:
        yield from self.search_stubs(query, location)
