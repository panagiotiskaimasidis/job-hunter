"""
Direct company career page scraper.

Supports three ATS platforms that cover the majority of target companies:
  - Workday   → P&G, Shell, Siemens, GE, Unilever, ABB, Bosch, BMW, BASF, Airbus, Rolls-Royce…
  - Greenhouse → SpaceX (not public), Rimac, Northvolt, many Series A+ startups
  - Lever      → another common startup ATS

Also supports a handful of companies with bespoke career sites.

Each company entry in TARGET_COMPANIES specifies:
  - ats:  "workday" | "greenhouse" | "lever" | "custom"
  - slug: the subdomain or org identifier used by the ATS
  - url:  (custom only) direct URL to scrape

No query/location loops — we go straight to the source and filter by keyword.
"""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from scraper.base import BaseJobScraper, JobPosting

logger = logging.getLogger(__name__)

# ── Verified ATS endpoints ─────────────────────────────────────────────────────
# Produced by verify_workday.py — only endpoints CONFIRMED to return jobs.
# Never guessed at scrape time; if the file is missing we fall back to the
# legacy slug list below (and LinkedIn covers everything by company name).
_VERIFIED_PATH = Path(__file__).parent.parent.parent / "data" / "target_companies_ats.json"


def _load_verified() -> dict:
    if _VERIFIED_PATH.exists():
        try:
            return json.loads(_VERIFIED_PATH.read_text())
        except Exception as exc:
            logger.warning("[company_careers] Could not read verified endpoints: %s", exc)
    return {}

# ── Target companies ──────────────────────────────────────────────────────────
# Add / remove entries freely. slug = the Workday/Greenhouse tenant identifier.
TARGET_COMPANIES: list[dict] = [
    # ── Workday ────────────────────────────────────────────────────────────
    {"name": "Procter & Gamble",      "ats": "workday",    "slug": "pg"},
    {"name": "Shell",                  "ats": "workday",    "slug": "shell"},
    {"name": "Siemens",                "ats": "workday",    "slug": "siemens"},
    {"name": "GE Vernova",             "ats": "workday",    "slug": "gevernova"},
    {"name": "Unilever",               "ats": "workday",    "slug": "unilever"},
    {"name": "ABB",                    "ats": "workday",    "slug": "abb"},
    {"name": "Bosch",                  "ats": "workday",    "slug": "bosch"},
    {"name": "BMW Group",              "ats": "workday",    "slug": "bmwgroup"},
    {"name": "BASF",                   "ats": "workday",    "slug": "basf"},
    {"name": "Rolls-Royce",            "ats": "workday",    "slug": "rollsroyce"},
    {"name": "Airbus",                 "ats": "workday",    "slug": "airbus"},
    {"name": "Philips",                "ats": "workday",    "slug": "philips"},
    {"name": "Nestlé",                 "ats": "workday",    "slug": "nestle"},
    {"name": "Schneider Electric",     "ats": "workday",    "slug": "schneiderelectric"},
    {"name": "Honeywell",              "ats": "workday",    "slug": "honeywell"},
    {"name": "Eaton",                  "ats": "workday",    "slug": "eaton"},
    {"name": "Danone",                 "ats": "workday",    "slug": "danone"},
    {"name": "Safran",                 "ats": "workday",    "slug": "safran"},
    {"name": "Thales",                 "ats": "workday",    "slug": "thales"},
    {"name": "Leonardo",               "ats": "workday",    "slug": "leonardo"},
    # ── Greenhouse ────────────────────────────────────────────────────────
    {"name": "Northvolt",              "ats": "greenhouse", "slug": "northvolt"},
    {"name": "Rimac Technology",       "ats": "greenhouse", "slug": "rimac"},
    {"name": "Lilium",                 "ats": "greenhouse", "slug": "lilium"},
    {"name": "H2 Green Steel",         "ats": "greenhouse", "slug": "h2greensteel"},
    {"name": "Einride",                "ats": "greenhouse", "slug": "einride"},
    {"name": "Climeworks",             "ats": "greenhouse", "slug": "climeworks"},
    {"name": "Verkor",                 "ats": "greenhouse", "slug": "verkor"},
    {"name": "Wayve",                  "ats": "greenhouse", "slug": "wayve"},
    {"name": "Helsing",                "ats": "greenhouse", "slug": "helsing"},
    {"name": "Isar Aerospace",         "ats": "greenhouse", "slug": "isaraerospace"},
    {"name": "The Exploration Company", "ats": "greenhouse", "slug": "theexplorationcompany"},
    # ── Lever ─────────────────────────────────────────────────────────────
    {"name": "Volocopter",             "ats": "lever",      "slug": "volocopter"},
    {"name": "Wandercraft",            "ats": "lever",      "slug": "wandercraft"},
    {"name": "Exotec",                 "ats": "lever",      "slug": "exotec"},
    # ── SmartRecruiters ───────────────────────────────────────────────────
    # Large multinationals that publish to SmartRecruiters' open API.
    {"name": "Bosch",                  "ats": "smartrecruiters", "slug": "BoschGroup"},
    {"name": "Visa",                   "ats": "smartrecruiters", "slug": "Visa"},
    {"name": "Ubisoft",                "ats": "smartrecruiters", "slug": "Ubisoft"},
    {"name": "IKEA",                   "ats": "smartrecruiters", "slug": "Ingka"},
    {"name": "Avery Dennison",         "ats": "smartrecruiters", "slug": "AveryDennison"},
    {"name": "Equinix",                "ats": "smartrecruiters", "slug": "Equinix"},
    {"name": "Bayer",                  "ats": "smartrecruiters", "slug": "Bayer"},
    {"name": "McDonald's",             "ats": "smartrecruiters", "slug": "McDonalds"},
]

# Keywords to filter job titles on — aligned with the candidate's profile
_TITLE_KEYWORDS = [
    "process engineer", "manufacturing engineer", "operations engineer",
    "production engineer", "industrial engineer", "continuous improvement",
    "process improvement", "lean engineer", "project engineer",
    "program manager", "technical program", "graduate engineer",
    "graduate programme", "graduate program", "engineering graduate",
    "operations excellence", "supply chain engineer", "reliability engineer",
    "mechanical engineer", "aeronautical", "aerospace engineer",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json, text/html, */*",
}


def _job_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _title_matches(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _TITLE_KEYWORDS)


# ── Workday scraper ───────────────────────────────────────────────────────────

def _scrape_workday(company: dict, max_jobs: int) -> list[JobPosting]:
    """
    Workday public API — works for all Workday-hosted career sites.
    Endpoint: https://{slug}.wd{N}.myworkdayjobs.com/wday/cxs/{slug}/{board}/jobs
    We try a few common board names and Workday API versions.
    """
    slug = company["slug"]
    name = company["name"]
    jobs: list[JobPosting] = []

    # Common Workday board path patterns
    board_paths = [
        f"https://{slug}.wd3.myworkdayjobs.com/wday/cxs/{slug}/External_Career_Site/jobs",
        f"https://{slug}.wd1.myworkdayjobs.com/wday/cxs/{slug}/External_Career_Site/jobs",
        f"https://{slug}.wd5.myworkdayjobs.com/wday/cxs/{slug}/External_Career_Site/jobs",
    ]

    payload = {
        "appliedFacets": {},
        "limit": min(max_jobs * 2, 20),
        "offset": 0,
        "searchText": "engineer",
    }

    with httpx.Client(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
        for url in board_paths:
            try:
                resp = client.post(url, json=payload)
                if resp.status_code != 200:
                    continue

                data = resp.json()
                postings = data.get("jobPostings", [])

                for p in postings:
                    title = p.get("title", "")
                    if not _title_matches(title):
                        continue

                    ext_url = p.get("externalPath", "")
                    # Build the full job URL
                    base = url.split("/wday/cxs/")[0]
                    job_url = f"{base}{ext_url}" if ext_url.startswith("/") else ext_url

                    location_nodes = p.get("locationsText", "") or p.get("locations", "")
                    if isinstance(location_nodes, list):
                        location = ", ".join(location_nodes)
                    else:
                        location = str(location_nodes)

                    jobs.append(JobPosting(
                        title=title,
                        company=name,
                        location=location,
                        description="",  # fetched separately
                        url=job_url,
                        source="company_careers",
                        job_id=_job_id(job_url),
                    ))

                    if len(jobs) >= max_jobs:
                        break

                if jobs:
                    logger.info("[company_careers] Workday %s → %d stubs", name, len(jobs))
                    return jobs

            except Exception as exc:
                logger.debug("[company_careers] Workday %s @ %s: %s", name, url, exc)
                continue

    if not jobs:
        logger.debug("[company_careers] Workday %s — no results (may need slug fix)", name)
    return jobs


def _fetch_workday_description(url: str) -> str:
    """Fetch a Workday job description page and extract the text."""
    try:
        with httpx.Client(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            el = (
                soup.select_one("div[data-automation-id='jobPostingDescription']")
                or soup.select_one("div.css-cygeeu")
                or soup.select_one("section.css-1t2rs9d")
                or soup.find("div", {"class": lambda c: c and "description" in c.lower()})
            )
            return el.get_text(separator="\n", strip=True)[:5000] if el else ""
    except Exception as exc:
        logger.debug("[company_careers] Workday desc fetch failed %s: %s", url, exc)
        return ""


# ── Greenhouse scraper ────────────────────────────────────────────────────────

def _scrape_greenhouse(company: dict, max_jobs: int) -> list[JobPosting]:
    slug = company["slug"]
    name = company["name"]
    jobs: list[JobPosting] = []

    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    try:
        with httpx.Client(timeout=15, headers=_HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        for j in data.get("jobs", []):
            title = j.get("title", "")
            if not _title_matches(title):
                continue

            job_url = j.get("absolute_url", "")
            location = j.get("location", {}).get("name", "")
            description_html = j.get("content", "")
            description = BeautifulSoup(description_html, "html.parser").get_text(
                separator="\n", strip=True
            )[:5000] if description_html else ""

            jobs.append(JobPosting(
                title=title,
                company=name,
                location=location,
                description=description,
                url=job_url,
                source="company_careers",
                job_id=_job_id(job_url),
            ))

            if len(jobs) >= max_jobs:
                break

        if jobs:
            logger.info("[company_careers] Greenhouse %s → %d jobs", name, len(jobs))

    except Exception as exc:
        logger.debug("[company_careers] Greenhouse %s failed: %s", name, exc)

    return jobs


# ── Lever scraper ─────────────────────────────────────────────────────────────

def _scrape_lever(company: dict, max_jobs: int) -> list[JobPosting]:
    slug = company["slug"]
    name = company["name"]
    jobs: list[JobPosting] = []

    url = f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=50"
    try:
        with httpx.Client(timeout=15, headers=_HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
            postings = resp.json()

        for p in postings:
            title = p.get("text", "")
            if not _title_matches(title):
                continue

            job_url = p.get("hostedUrl", "")
            location = p.get("categories", {}).get("location", "")
            lists = p.get("lists", [])
            description = "\n".join(
                BeautifulSoup(item.get("content", ""), "html.parser").get_text(strip=True)
                for item in lists
            )[:5000]

            jobs.append(JobPosting(
                title=title,
                company=name,
                location=location,
                description=description,
                url=job_url,
                source="company_careers",
                job_id=_job_id(job_url),
            ))

            if len(jobs) >= max_jobs:
                break

        if jobs:
            logger.info("[company_careers] Lever %s → %d jobs", name, len(jobs))

    except Exception as exc:
        logger.debug("[company_careers] Lever %s failed: %s", name, exc)

    return jobs


# ── SmartRecruiters scraper ───────────────────────────────────────────────────

def _scrape_smartrecruiters(company: dict, max_jobs: int) -> list[JobPosting]:
    """
    SmartRecruiters public Posting API — no auth required.
      List:   https://api.smartrecruiters.com/v1/companies/{slug}/postings
      Detail: https://api.smartrecruiters.com/v1/companies/{slug}/postings/{id}
    The list endpoint omits the description, so we fetch detail per posting
    (bounded by max_jobs) and pull the job-ad sections.
    """
    slug = company["slug"]
    name = company["name"]
    jobs: list[JobPosting] = []

    list_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"
    try:
        with httpx.Client(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
            resp = client.get(list_url)
            resp.raise_for_status()
            postings = resp.json().get("content", [])

            for p in postings:
                title = p.get("name", "")
                if not _title_matches(title):
                    continue

                pid = p.get("id", "")
                loc = p.get("location", {}) or {}
                location = ", ".join(
                    str(v) for v in [loc.get("city"), loc.get("region"), loc.get("country")] if v
                )
                job_url = f"https://jobs.smartrecruiters.com/{slug}/{pid}"

                # Fetch the full job ad for the description
                description = ""
                try:
                    d = client.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{pid}")
                    if d.status_code == 200:
                        ad = d.json().get("jobAd", {}).get("sections", {})
                        parts = [
                            ad.get("jobDescription", {}).get("text", ""),
                            ad.get("qualifications", {}).get("text", ""),
                            ad.get("additionalInformation", {}).get("text", ""),
                        ]
                        html = "\n".join(x for x in parts if x)
                        description = BeautifulSoup(html, "html.parser").get_text(
                            separator="\n", strip=True
                        )[:5000]
                except Exception as exc:
                    logger.debug("[company_careers] SR detail fetch failed %s: %s", job_url, exc)

                jobs.append(JobPosting(
                    title=title,
                    company=name,
                    location=location,
                    description=description,
                    url=job_url,
                    source="company_careers",
                    job_id=_job_id(job_url),
                ))

                if len(jobs) >= max_jobs:
                    break

        if jobs:
            logger.info("[company_careers] SmartRecruiters %s → %d jobs", name, len(jobs))

    except Exception as exc:
        logger.debug("[company_careers] SmartRecruiters %s failed: %s", name, exc)

    return jobs


# ── Verified-endpoint scraper ───────────────────────────────────────────────

def _scrape_verified_workday(name: str, endpoint: str, max_jobs: int) -> list[JobPosting]:
    """Scrape a CONFIRMED Workday CXS endpoint (from verify_workday.py)."""
    jobs: list[JobPosting] = []
    base = endpoint.split("/wday/cxs/")[0]
    payload = {"appliedFacets": {}, "limit": min(max_jobs * 2, 20), "offset": 0, "searchText": "engineer"}
    try:
        with httpx.Client(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
            resp = client.post(endpoint, json=payload)
            if resp.status_code != 200:
                return jobs
            for p in resp.json().get("jobPostings", []):
                title = p.get("title", "")
                if not _title_matches(title):
                    continue
                ext = p.get("externalPath", "")
                job_url = f"{base}{ext}" if ext.startswith("/") else ext
                loc = p.get("locationsText", "")
                jobs.append(JobPosting(
                    title=title, company=name, location=str(loc),
                    description="", url=job_url,
                    source="company_careers", job_id=_job_id(job_url),
                ))
                if len(jobs) >= max_jobs:
                    break
        if jobs:
            logger.info("[company_careers] ✅ %s (verified Workday) → %d jobs", name, len(jobs))
    except Exception as exc:
        logger.debug("[company_careers] verified Workday %s failed: %s", name, exc)
    return jobs


# ── Main scraper class ────────────────────────────────────────────────────────

class CompanyCareerscraper(BaseJobScraper):
    """
    Scrapes career pages directly from target company ATS platforms.
    Prioritises CONFIRMED endpoints from data/target_companies_ats.json;
    falls back to the legacy slug list for anything not yet verified.
    Ignores query/location — goes straight to source and filters by title keywords.
    """

    source_name = "company_careers"

    def search_stubs(self, query: str, location: str) -> list[JobPosting]:
        """
        query and location are ignored — we scrape all target companies directly.
        Called once per pipeline run (runner deduplicates extra calls).
        """
        all_jobs: list[JobPosting] = []

        # ── Phase 1: CONFIRMED endpoints (reliable, no guessing) ───────────
        verified = _load_verified()
        verified_names = set()
        for name, info in verified.items():
            verified_names.add(name)
            ats = info.get("ats")
            endpoint = info.get("endpoint", "")
            try:
                if ats == "workday":
                    all_jobs.extend(_scrape_verified_workday(name, endpoint, self.max_jobs))
                elif ats == "greenhouse":
                    slug = endpoint.split("/boards/")[1].split("/")[0]
                    all_jobs.extend(_scrape_greenhouse({"name": name, "slug": slug}, self.max_jobs))
                elif ats == "lever":
                    slug = endpoint.split("/postings/")[1].split("?")[0]
                    all_jobs.extend(_scrape_lever({"name": name, "slug": slug}, self.max_jobs))
                time.sleep(self.delay)
            except Exception as exc:
                logger.error("[company_careers] verified %s failed: %s", name, exc)

        # ── Phase 2: Legacy slug guesses (only for non-verified companies) ──
        for company in TARGET_COMPANIES:
            if company["name"] in verified_names:
                continue  # already covered by a confirmed endpoint
            ats = company["ats"]
            try:
                if ats == "workday":
                    all_jobs.extend(_scrape_workday(company, self.max_jobs))
                elif ats == "greenhouse":
                    all_jobs.extend(_scrape_greenhouse(company, self.max_jobs))
                elif ats == "lever":
                    all_jobs.extend(_scrape_lever(company, self.max_jobs))
                elif ats == "smartrecruiters":
                    all_jobs.extend(_scrape_smartrecruiters(company, self.max_jobs))
                time.sleep(self.delay)
            except Exception as exc:
                logger.error("[company_careers] %s failed: %s", company["name"], exc)

        logger.info("[company_careers] Total %d job stubs from company sites", len(all_jobs))
        return all_jobs

    def fetch_description(self, url: str) -> str:
        """Fetch description for Workday stubs (Greenhouse/Lever already include it)."""
        if "myworkdayjobs.com" in url:
            return _fetch_workday_description(url)
        # For Greenhouse/Lever the description was already populated in search_stubs
        return ""

    def search(self, query: str, location: str) -> Iterator[JobPosting]:
        """Legacy path — not used by the parallel runner."""
        yield from self.search_stubs(query, location)
