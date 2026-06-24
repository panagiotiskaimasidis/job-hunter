"""RemoteOK public JSON API — free, no auth, engineering-focused.

RemoteOK publishes all remote jobs via a public API. The first element of the
response array is a metadata object, the rest are job listings. Descriptions
are included inline (HTML stripped to plain text).

    GET https://remoteok.io/api

Docs: https://remoteok.io/api (unofficial, always-on)
"""

import hashlib
import logging
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from scraper.base import BaseJobScraper, JobPosting

logger = logging.getLogger(__name__)

_API = "https://remoteok.io/api"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Engineering-relevant tag keywords — skip pure marketing/sales/design jobs
_ENGINEERING_TAGS = {
    "engineering", "mechanical", "manufacturing", "industrial", "process",
    "aerospace", "automotive", "energy", "robotics", "automation",
    "embedded", "hardware", "electronics", "operations", "supply chain",
    "project management", "product", "r&d", "research", "python",
    "dev", "backend", "frontend", "fullstack", "devops", "ml", "ai",
    "data", "cloud", "systems", "infrastructure", "qa", "testing",
}


def _is_relevant(tags: list[str]) -> bool:
    """Return True if any tag suggests a technical/engineering role."""
    lowered = {t.lower() for t in tags}
    return bool(lowered & _ENGINEERING_TAGS)


class RemoteOKScraper(BaseJobScraper):
    source_name = "remoteok"

    def search_stubs(self, query: str, location: str) -> list[JobPosting]:
        """Ignores query/location — pulls all remote tech/engineering listings."""
        stubs: list[JobPosting] = []
        try:
            with httpx.Client(headers=_HEADERS, timeout=25, follow_redirects=True) as client:
                resp = client.get(_API)
                if resp.status_code != 200:
                    logger.warning("[remoteok] HTTP %d", resp.status_code)
                    return stubs
                rows = resp.json()

            # First element is a metadata object, skip it
            for j in rows[1:]:
                stub = self._parse(j)
                if stub and len(stubs) < self.max_jobs:
                    stubs.append(stub)

            logger.info("[remoteok] %d stubs", len(stubs))
        except Exception as exc:
            logger.warning("[remoteok] API call failed: %s", exc)
        return stubs

    def _parse(self, j: dict) -> "JobPosting | None":
        try:
            tags = j.get("tags") or []
            if not _is_relevant(tags):
                return None

            url = j.get("url") or j.get("apply_url") or ""
            if not url:
                return None
            if not url.startswith("http"):
                url = "https://remoteok.io" + url

            desc_html = j.get("description") or ""
            desc = (
                BeautifulSoup(desc_html, "html.parser").get_text(separator="\n", strip=True)[:3000]
                if desc_html else ""
            )
            if not desc.strip():
                return None

            slug = j.get("slug") or j.get("id") or url
            jid = hashlib.md5(f"remoteok-{slug}".encode()).hexdigest()[:12]

            return JobPosting(
                title=j.get("position") or "",
                company=j.get("company") or "Unknown",
                location="Remote",
                description=desc,
                url=url,
                source=self.source_name,
                job_id=jid,
            )
        except Exception as exc:
            logger.debug("[remoteok] parse failed: %s", exc)
            return None

    def fetch_description(self, url: str) -> str:
        return ""

    def search(self, query: str, location: str) -> Iterator[JobPosting]:
        yield from self.search_stubs(query, location)
