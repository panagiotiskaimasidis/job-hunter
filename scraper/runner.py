"""
Orchestrates all board scrapers and merges results into jobs_raw.json.

Speed optimisations vs v1:
- Job description pages are fetched in parallel (SCRAPE_WORKERS threads)
- Locations reduced to Europe / Greece / Remote (no duplicate city sweeps)
- MAX_JOBS_PER_BOARD and SCRAPE_DELAY_SECONDS lowered in config
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from scraper.base import JobPosting
from scraper.boards.linkedin import LinkedInScraper
from scraper.boards.indeed import IndeedScraper
from scraper.boards.eurojobs import EuroJobsScraper
from scraper.boards.company_careers import CompanyCareerscraper

logger = logging.getLogger(__name__)


def _load_processed_ids() -> set[str]:
    if config.JOBS_PROCESSED.exists():
        data = json.loads(config.JOBS_PROCESSED.read_text())
        return {j["job_id"] for j in data if "job_id" in j}
    return set()


def _load_raw() -> list[dict]:
    if config.JOBS_RAW.exists():
        return json.loads(config.JOBS_RAW.read_text())
    return []


def _save_raw(jobs: list[dict]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.JOBS_RAW.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))


def run_scraper() -> list[JobPosting]:
    """
    Scrape all boards for all queries/locations.
    Job description pages are fetched in parallel for speed.
    Returns new (unseen) postings.
    """
    processed_ids = _load_processed_ids()
    existing_raw = _load_raw()
    existing_ids = {j["job_id"] for j in existing_raw if "job_id" in j}

    board_scrapers = [
        LinkedInScraper(delay_seconds=config.SCRAPE_DELAY_SECONDS, max_jobs=config.MAX_JOBS_PER_BOARD),
        IndeedScraper(delay_seconds=config.SCRAPE_DELAY_SECONDS, max_jobs=config.MAX_JOBS_PER_BOARD),
        EuroJobsScraper(delay_seconds=config.SCRAPE_DELAY_SECONDS, max_jobs=config.MAX_JOBS_PER_BOARD),
    ]
    company_scraper = CompanyCareerscraper(
        delay_seconds=config.SCRAPE_DELAY_SECONDS,
        max_jobs=config.MAX_JOBS_PER_BOARD,
    )

    new_postings: list[JobPosting] = []

    # ── Phase A: Company career pages (run once — no query/location loop) ──
    logger.info("[runner] Scraping %d company career pages directly…",
                len(__import__("scraper.boards.company_careers",
                               fromlist=["TARGET_COMPANIES"]).TARGET_COMPANIES))
    company_stubs = [
        s for s in company_scraper.search_stubs("", "")
        if s.job_id not in processed_ids and s.job_id not in existing_ids
    ]
    logger.info("[runner] company_careers → %d fresh stubs", len(company_stubs))

    # Greenhouse/Lever jobs already have descriptions; Workday stubs need fetching
    workday_stubs = [s for s in company_stubs if not s.description and "myworkdayjobs.com" in s.url]
    ready_jobs    = [s for s in company_stubs if s.description]

    if workday_stubs:
        def _fetch_wd(stub: JobPosting) -> JobPosting | None:
            try:
                desc = company_scraper.fetch_description(stub.url)
                if desc.strip():
                    stub.description = desc
                    return stub
            except Exception as exc:
                logger.debug("[runner] Workday desc fetch failed %s: %s", stub.url, exc)
            return None

        workers = getattr(config, "SCRAPE_WORKERS", 4)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for job in pool.map(_fetch_wd, workday_stubs):
                if job and job.job_id not in existing_ids:
                    ready_jobs.append(job)
                    existing_ids.add(job.job_id)

    for job in ready_jobs:
        if job.job_id not in existing_ids:
            new_postings.append(job)
            existing_ids.add(job.job_id)

    # ── Phase B: Job boards (query × location loops) ───────────────────────
    for scraper in board_scrapers:
        for query in config.SEARCH_QUERIES:
            for location in config.SEARCH_LOCATIONS:
                logger.info("[runner] %s | '%s' in '%s'", scraper.source_name, query, location)

                # Get job stubs (title, company, url) quickly — no description yet
                stubs = list(scraper.search_stubs(query, location))

                # Filter out already-seen jobs before fetching descriptions
                fresh_stubs = [
                    s for s in stubs
                    if s.job_id not in processed_ids and s.job_id not in existing_ids
                ]

                if not fresh_stubs:
                    continue

                # Fetch descriptions in parallel
                def _fetch(stub: JobPosting) -> JobPosting | None:
                    try:
                        desc = scraper.fetch_description(stub.url)
                        if not desc.strip():
                            return None
                        stub.description = desc
                        return stub
                    except Exception as exc:
                        logger.debug("[runner] Failed to fetch %s: %s", stub.url, exc)
                        return None

                workers = getattr(config, "SCRAPE_WORKERS", 4)
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {pool.submit(_fetch, stub): stub for stub in fresh_stubs}
                    for fut in as_completed(futures):
                        job = fut.result()
                        if job and job.job_id not in existing_ids:
                            new_postings.append(job)
                            existing_ids.add(job.job_id)

                time.sleep(config.SCRAPE_DELAY_SECONDS)

    all_raw = existing_raw + [j.to_dict() for j in new_postings]
    _save_raw(all_raw)
    logger.info("[runner] %d new postings scraped. Total raw: %d", len(new_postings), len(all_raw))
    return new_postings


def load_unprocessed() -> list[JobPosting]:
    """Return raw jobs that haven't been evaluated yet."""
    processed_ids = _load_processed_ids()
    raw = _load_raw()
    return [
        JobPosting.from_dict(j)
        for j in raw
        if j.get("job_id") not in processed_ids and j.get("description", "").strip()
    ]
