"""Arbeitnow public job-board API — free, no auth, strong EU coverage.

Arbeitnow aggregates jobs across Europe (heavy DACH + remote presence) and
publishes them through a keyless, paginated JSON API with descriptions inline.

    GET https://www.arbeitnow.com/api/job-board-api?page=N

Docs: https://documenter.getpostman.com/view/18545278/UVJbJdKh
"""

import hashlib
import logging
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from scraper.base import BaseJobScraper, JobPosting

logger = logging.getLogger(__name__)

_API = "https://www.arbeitnow.com/api/job-board-api"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
_MAX_PAGES = 5  # ~100 jobs per page


class ArbeitnowScraper(BaseJobScraper):
    source_name = "arbeitnow"

    def search_stubs(self, query: str, location: str) -> list[JobPosting]:
        """Ignores query/location — pages through the EU board, title filter is downstream."""
        stubs: list[JobPosting] = []
        seen: set[str] = set()

        try:
            with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
                for page in range(1, _MAX_PAGES + 1):
                    resp = client.get(_API, params={"page": page})
                    if resp.status_code != 200:
                        break
                    payload = resp.json()
                    rows = payload.get("data", []) or []
                    if not rows:
                        break

                    for j in rows:
                        stub = self._parse(j)
                        if stub and stub.job_id not in seen:
                            seen.add(stub.job_id)
                            stubs.append(stub)

                    if not (payload.get("links") or {}).get("next"):
                        break

            logger.info("[arbeitnow] %d stubs", len(stubs))
        except Exception as exc:
            logger.warning("[arbeitnow] API call failed: %s", exc)

        return stubs

    def _parse(self, j: dict) -> "JobPosting | None":
        try:
            url = j.get("url") or ""
            if not url:
                return None
            location = j.get("location") or ("Remote" if j.get("remote") else "Europe")
            desc_html = j.get("description") or ""
            desc = (
                BeautifulSoup(desc_html, "html.parser").get_text(separator="\n", strip=True)[:3000]
                if desc_html else ""
            )
            jid = hashlib.md5(f"arbeitnow-{j.get('slug', url)}".encode()).hexdigest()[:12]
            return JobPosting(
                title=j.get("title") or "",
                company=j.get("company_name") or "Unknown",
                location=location,
                description=desc,
                url=url,
                source=self.source_name,
                job_id=jid,
            )
        except Exception as exc:
            logger.debug("[arbeitnow] parse failed: %s", exc)
            return None

    def fetch_description(self, url: str) -> str:
        # Descriptions are always included in the API response.
        return ""

    def search(self, query: str, location: str) -> Iterator[JobPosting]:
        yield from self.search_stubs(query, location)
