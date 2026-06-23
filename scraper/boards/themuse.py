"""The Muse public jobs API — free, no auth, rich engineering coverage.

The Muse exposes a public, keyless endpoint with native filters that map almost
perfectly onto this candidate's profile: a real "Engineering" category and an
"Entry Level" seniority filter. Descriptions are returned inline, so no second
fetch is needed.

    GET https://www.themuse.com/api/public/jobs?category=Engineering&level=Entry%20Level&page=N

Docs: https://www.themuse.com/developers/api/v2
"""

import hashlib
import logging
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from scraper.base import BaseJobScraper, JobPosting

logger = logging.getLogger(__name__)

_API = "https://www.themuse.com/api/public/jobs"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Categories on The Muse that overlap the candidate's target roles.
_CATEGORIES = [
    "Engineering",
    "Mechanical Engineering",
    "Project Management",
    "Operations",
]
# Only early-career seniority — matches the 0-2 year profile.
_LEVELS = ["Entry Level", "Mid Level", "Internship"]
_MAX_PAGES = 4  # ~20 jobs per page


class TheMuseScraper(BaseJobScraper):
    source_name = "themuse"

    def search_stubs(self, query: str, location: str) -> list[JobPosting]:
        """Ignores query/location — pages through Engineering/early-career jobs."""
        stubs: list[JobPosting] = []
        seen: set[str] = set()

        params = [("category", c) for c in _CATEGORIES] + [("level", lv) for lv in _LEVELS]

        try:
            with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
                for page in range(_MAX_PAGES):
                    resp = client.get(_API, params=params + [("page", page)])
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    results = data.get("results", []) or []
                    if not results:
                        break

                    for j in results:
                        stub = self._parse(j)
                        if stub and stub.job_id not in seen:
                            seen.add(stub.job_id)
                            stubs.append(stub)

                    if page + 1 >= data.get("page_count", 1):
                        break

            logger.info("[themuse] %d stubs", len(stubs))
        except Exception as exc:
            logger.warning("[themuse] API call failed: %s", exc)

        return stubs

    def _parse(self, j: dict) -> "JobPosting | None":
        try:
            refs = j.get("refs") or {}
            url = refs.get("landing_page") or ""
            if not url:
                return None
            locations = j.get("locations") or []
            loc = ", ".join(l.get("name", "") for l in locations if l.get("name")) or "Not specified"
            company = (j.get("company") or {}).get("name") or "Unknown"
            desc_html = j.get("contents") or ""
            desc = (
                BeautifulSoup(desc_html, "html.parser").get_text(separator="\n", strip=True)[:3000]
                if desc_html else ""
            )
            jid = hashlib.md5(f"themuse-{j.get('id', url)}".encode()).hexdigest()[:12]
            return JobPosting(
                title=j.get("name") or "",
                company=company,
                location=loc,
                description=desc,
                url=url,
                source=self.source_name,
                job_id=jid,
            )
        except Exception as exc:
            logger.debug("[themuse] parse failed: %s", exc)
            return None

    def fetch_description(self, url: str) -> str:
        # Descriptions are always included in the search response.
        return ""

    def search(self, query: str, location: str) -> Iterator[JobPosting]:
        yield from self.search_stubs(query, location)
