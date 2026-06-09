"""
Indeed job scraper.

Indeed's HTML structure changes frequently — we extract via semantic signals
(job title tag, company tag, salary section) not brittle CSS selectors.
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
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_BASE = "https://www.indeed.com"


class IndeedScraper(BaseJobScraper):
    source_name = "indeed"

    def search(self, query: str, location: str) -> Iterator[JobPosting]:
        params = {"q": query, "l": location, "fromage": "3"}  # last 3 days
        url = f"{_BASE}/jobs?{urlencode(params)}"

        with httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.warning("[indeed] HTTP %s for %s", exc.response.status_code, url)
                return

            soup = BeautifulSoup(resp.text, "html.parser")

            # Indeed uses data-jk attribute for job keys
            cards = soup.select("div[data-jk]")
            if not cards:
                cards = soup.select("td.resultContent")

            for card in cards:
                try:
                    title_el = card.select_one("h2.jobTitle span") or card.select_one("h2 a span")
                    company_el = card.select_one("span.companyName") or card.select_one("[data-testid='company-name']")
                    location_el = card.select_one("div.companyLocation") or card.select_one("[data-testid='job-location']")
                    salary_el = card.select_one("div.salary-snippet") or card.select_one("[data-testid='attribute_snippet_testid']")

                    jk = card.get("data-jk") or ""
                    job_url = f"{_BASE}/viewjob?jk={jk}" if jk else ""

                    if not title_el or not job_url:
                        continue

                    title = title_el.get_text(strip=True)
                    company = company_el.get_text(strip=True) if company_el else "Unknown"
                    loc = location_el.get_text(strip=True) if location_el else location
                    salary = salary_el.get_text(strip=True) if salary_el else ""

                    description = self._fetch_description(client, job_url)
                    time.sleep(self.delay)

                    job_id = hashlib.md5(f"{title}{company}{loc}".encode()).hexdigest()[:12]

                    yield JobPosting(
                        title=title,
                        company=company,
                        location=loc,
                        description=description,
                        url=job_url,
                        source=self.source_name,
                        salary=salary,
                        job_id=job_id,
                    )

                except Exception as exc:
                    logger.debug("[indeed] Failed to parse card: %s", exc)
                    continue

                time.sleep(self.delay)

    def _fetch_description(self, client: httpx.Client, url: str) -> str:
        try:
            resp = client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            desc = soup.select_one("div#jobDescriptionText") or \
                   soup.select_one("div.jobsearch-jobDescriptionText")
            return desc.get_text(separator="\n", strip=True) if desc else ""
        except Exception as exc:
            logger.debug("[indeed] Could not fetch description from %s: %s", url, exc)
            return ""
