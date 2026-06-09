"""
EuroEngineering / Eurojobs scraper — targets European roles across the major
markets (Greece, Belgium, Netherlands, Germany, UK, etc.).

Uses EuroJobs.com public search — no login required.
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
}


class EuroJobsScraper(BaseJobScraper):
    source_name = "eurojobs"

    def search(self, query: str, location: str) -> Iterator[JobPosting]:
        params = {"q": query, "l": location}
        url = f"https://eurojobs.com/search-jobs/?{urlencode(params)}"

        with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                logger.warning("[eurojobs] Failed to fetch search page: %s", exc)
                return

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("article.job") or soup.select("div.job-listing")

            for card in cards:
                try:
                    title_el = card.select_one("h2") or card.select_one("h3") or card.select_one(".job-title")
                    company_el = card.select_one(".company") or card.select_one(".employer")
                    location_el = card.select_one(".location") or card.select_one(".job-location")
                    link_el = card.select_one("a[href]")

                    if not title_el or not link_el:
                        continue

                    href = link_el.get("href", "")
                    if not href.startswith("http"):
                        href = "https://eurojobs.com" + href

                    title = title_el.get_text(strip=True)
                    company = company_el.get_text(strip=True) if company_el else "Unknown"
                    loc = location_el.get_text(strip=True) if location_el else location

                    description = self._fetch_description(client, href)
                    time.sleep(self.delay)

                    job_id = hashlib.md5(f"{title}{company}{loc}".encode()).hexdigest()[:12]

                    yield JobPosting(
                        title=title,
                        company=company,
                        location=loc,
                        description=description,
                        url=href,
                        source=self.source_name,
                        job_id=job_id,
                    )

                except Exception as exc:
                    logger.debug("[eurojobs] Failed to parse card: %s", exc)
                    continue

                time.sleep(self.delay)

    def _fetch_description(self, client: httpx.Client, url: str) -> str:
        try:
            resp = client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            desc = soup.select_one(".job-description") or soup.select_one("div.description") or soup.select_one("main")
            return desc.get_text(separator="\n", strip=True)[:3000] if desc else ""
        except Exception as exc:
            logger.debug("[eurojobs] Could not fetch description: %s", exc)
            return ""
