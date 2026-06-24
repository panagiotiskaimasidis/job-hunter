"""
Orchestrates all board scrapers and merges results into jobs_raw.json.

Speed optimisations:
- Job description pages are fetched in parallel (SCRAPE_WORKERS threads)
- Stubs that already carry a description (e.g. Remotive API) skip the fetch step
- Remotive is called once per query (no location loop) since it's remote-only
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from scraper.base import JobPosting
from scraper.boards.eurojobs import EuroJobsScraper
from scraper.boards.remotive import RemotiveScraper
from scraper.boards.themuse import TheMuseScraper
from scraper.boards.arbeitnow import ArbeitnowScraper
from scraper.boards.jobicy import JobicyScraper
from scraper.boards.company_careers import CompanyCareerscraper
from scraper.boards.remoteok import RemoteOKScraper

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


def _fetch_descriptions(
    scraper,
    stubs: list[JobPosting],
    existing_ids: set[str],
    new_postings: list[JobPosting],
    workers: int,
) -> None:
    """Fetch descriptions in parallel; add complete jobs to new_postings."""
    # Stubs with description already (e.g. from Remotive API) — add directly
    for stub in stubs:
        if stub.description.strip() and stub.job_id not in existing_ids:
            new_postings.append(stub)
            existing_ids.add(stub.job_id)

    to_fetch = [s for s in stubs if not s.description.strip()]
    if not to_fetch:
        return

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

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch, stub): stub for stub in to_fetch}
        for fut in as_completed(futures):
            job = fut.result()
            if job and job.job_id not in existing_ids:
                new_postings.append(job)
                existing_ids.add(job.job_id)


def run_scraper() -> list[JobPosting]:
    """
    Scrape all boards for all queries/locations.
    Returns new (unseen) postings.
    """
    processed_ids = _load_processed_ids()
    existing_raw = _load_raw()
    existing_ids = {j["job_id"] for j in existing_raw if "job_id" in j}
    workers = getattr(config, "SCRAPE_WORKERS", 4)

    # Location-aware boards (query × location loops). Indeed (Cloudflare-blocked)
    # and WTTJ (returns HTTP 202 bot-wall) were removed — they cost hundreds of
    # wasted requests per run and yielded nothing.
    board_scrapers = [
        EuroJobsScraper(delay_seconds=config.SCRAPE_DELAY_SECONDS, max_jobs=config.MAX_JOBS_PER_BOARD),
    ]

    # Remote-only boards — called once per query, no location loop
    remote_scrapers = [
        RemotiveScraper(delay_seconds=config.SCRAPE_DELAY_SECONDS, max_jobs=config.MAX_JOBS_PER_BOARD),
    ]

    # Aggregator APIs — keyless JSON feeds with descriptions inline. Each is
    # called ONCE (they ignore query/location and page through internally), so
    # they add hundreds of fresh, relevant stubs at a fraction of the request
    # cost of the query×location loops.
    aggregator_scrapers = [
        TheMuseScraper(delay_seconds=config.SCRAPE_DELAY_SECONDS, max_jobs=config.MAX_JOBS_PER_BOARD),
        ArbeitnowScraper(delay_seconds=config.SCRAPE_DELAY_SECONDS, max_jobs=config.MAX_JOBS_PER_BOARD),
        JobicyScraper(delay_seconds=config.SCRAPE_DELAY_SECONDS, max_jobs=config.MAX_JOBS_PER_BOARD),
        RemoteOKScraper(delay_seconds=config.SCRAPE_DELAY_SECONDS, max_jobs=config.MAX_JOBS_PER_BOARD),
    ]

    company_scraper = CompanyCareerscraper(
        delay_seconds=config.SCRAPE_DELAY_SECONDS,
        max_jobs=config.MAX_JOBS_PER_BOARD,
    )

    new_postings: list[JobPosting] = []

    # ── Phase A: Company career pages (run once — no query/location loop) ──
    logger.info(
        "[runner] Scraping %d company career pages directly…",
        len(__import__("scraper.boards.company_careers", fromlist=["TARGET_COMPANIES"]).TARGET_COMPANIES),
    )
    company_stubs = [
        s for s in company_scraper.search_stubs("", "")
        if s.job_id not in processed_ids and s.job_id not in existing_ids
    ]
    logger.info("[runner] company_careers → %d fresh stubs", len(company_stubs))

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

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for job in pool.map(_fetch_wd, workday_stubs):
                if job and job.job_id not in existing_ids:
                    ready_jobs.append(job)
                    existing_ids.add(job.job_id)

    for job in ready_jobs:
        if job.job_id not in existing_ids:
            new_postings.append(job)
            existing_ids.add(job.job_id)

    # ── Phase B: Location-aware job boards (query × location loops) ─────────
    for scraper in board_scrapers:
        for query in config.SEARCH_QUERIES:
            for location in config.SEARCH_LOCATIONS:
                logger.info("[runner] %s | '%s' in '%s'", scraper.source_name, query, location)

                stubs = list(scraper.search_stubs(query, location))
                fresh_stubs = [
                    s for s in stubs
                    if s.job_id not in processed_ids and s.job_id not in existing_ids
                ]

                if not fresh_stubs:
                    continue

                _fetch_descriptions(scraper, fresh_stubs, existing_ids, new_postings, workers)
                time.sleep(config.SCRAPE_DELAY_SECONDS)

    # ── Phase C: Remote-only boards (query loop only, no location) ──────────
    for scraper in remote_scrapers:
        for query in config.SEARCH_QUERIES:
            logger.info("[runner] %s | '%s' (remote-only)", scraper.source_name, query)

            stubs = list(scraper.search_stubs(query, "Remote"))
            fresh_stubs = [
                s for s in stubs
                if s.job_id not in processed_ids and s.job_id not in existing_ids
            ]

            if not fresh_stubs:
                continue

            _fetch_descriptions(scraper, fresh_stubs, existing_ids, new_postings, workers)
            time.sleep(config.SCRAPE_DELAY_SECONDS)

    # ── Phase D: Aggregator APIs (called once each, no query/location loop) ──
    for scraper in aggregator_scrapers:
        logger.info("[runner] %s (aggregator — single call)", scraper.source_name)

        stubs = list(scraper.search_stubs("", ""))
        fresh_stubs = [
            s for s in stubs
            if s.job_id not in processed_ids and s.job_id not in existing_ids
        ]
        logger.info("[runner] %s → %d fresh stubs", scraper.source_name, len(fresh_stubs))

        if not fresh_stubs:
            continue

        _fetch_descriptions(scraper, fresh_stubs, existing_ids, new_postings, workers)
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
