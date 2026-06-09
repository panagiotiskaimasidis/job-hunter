"""
Workday / ATS endpoint verifier.

Workday tenant URLs cannot be guessed reliably — each has an unguessable
subdomain, server number (wd1/wd2/wd3/wd5/wd103…) and board name. This script
PROBES a matrix of realistic patterns for each target company and records ONLY
the endpoints that actually return jobs. Nothing is ever guessed at scrape time.

Output:  data/target_companies_ats.json
  {
    "Procter & Gamble": {
      "ats": "workday",
      "endpoint": "https://pg.wd5.myworkdayjobs.com/wday/cxs/pg/External/jobs",
      "verified": true
    },
    ...
  }

Run:
  python verify_workday.py            # verify all companies
  python verify_workday.py --limit 50 # verify first 50 (quick test)

This is slow (hundreds of HTTP probes) and is meant to be run occasionally —
NOT on every scrape. The scraper reads the cached JSON it produces.
"""

import argparse
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from pathlib import Path
from data.target_companies import TARGET_COMPANIES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# Standalone — does NOT require a candidate profile (config.py loads one).
_DATA_DIR = Path(__file__).parent / "data"
_OUT = _DATA_DIR / "target_companies_ats.json"

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# Workday server shards seen in the wild
_WD_SHARDS = ["wd1", "wd2", "wd3", "wd5", "wd103", "wd10", "wd12"]
# Common board/site identifiers
_WD_SITES = ["External_Career_Site", "External", "Careers", "careers",
             "External_Careers", "en-US", "Global_Careers"]


def _slugify(name: str) -> list[str]:
    """Generate candidate Workday tenant slugs from a company name."""
    base = name.lower().strip()
    base = re.sub(r"&", "and", base)
    base = re.sub(r"[^a-z0-9 ]", "", base)
    words = base.split()
    candidates = set()
    if words:
        candidates.add("".join(words))           # procterandgamble
        candidates.add(words[0])                  # procter
        candidates.add("".join(w[0] for w in words))  # pag
        if len(words) >= 2:
            candidates.add(words[0] + words[1])   # proctergamble
        # Strip common suffixes
        joined = "".join(words)
        for suf in ("group", "international", "technologies", "company", "corporation",
                    "industries", "plc", "ag", "sa", "se", "inc"):
            if joined.endswith(suf):
                candidates.add(joined[:-len(suf)])
    return [c for c in candidates if 2 <= len(c) <= 30]


def _probe_workday(slug: str, client: httpx.Client) -> str | None:
    """Try the Workday CXS API across shards/sites. Return endpoint if jobs found."""
    payload = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": "engineer"}
    for shard in _WD_SHARDS:
        for site in _WD_SITES:
            url = f"https://{slug}.{shard}.myworkdayjobs.com/wday/cxs/{slug}/{site}/jobs"
            try:
                r = client.post(url, json=payload, timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    if "jobPostings" in data or "total" in data:
                        return url
            except Exception:
                continue
    return None


def _probe_greenhouse(slug: str, client: httpx.Client) -> str | None:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        r = client.get(url, timeout=8)
        if r.status_code == 200 and r.json().get("jobs") is not None:
            return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    except Exception:
        pass
    return None


def _probe_lever(slug: str, client: httpx.Client) -> str | None:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=1"
    try:
        r = client.get(url, timeout=8)
        if r.status_code == 200 and isinstance(r.json(), list):
            return f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=50"
    except Exception:
        pass
    return None


def verify_company(entry: tuple) -> dict:
    name, sector, country = entry
    result = {"name": name, "ats": None, "endpoint": None, "verified": False}

    with httpx.Client(headers=_HEADERS, follow_redirects=True) as client:
        for slug in _slugify(name):
            # Greenhouse / Lever first (cheap single GET)
            gh = _probe_greenhouse(slug, client)
            if gh:
                result.update(ats="greenhouse", endpoint=gh, verified=True, slug=slug)
                return result
            lv = _probe_lever(slug, client)
            if lv:
                result.update(ats="lever", endpoint=lv, verified=True, slug=slug)
                return result
            # Workday (matrix probe — more expensive)
            wd = _probe_workday(slug, client)
            if wd:
                result.update(ats="workday", endpoint=wd, verified=True, slug=slug)
                return result

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="Verify only first N companies")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    companies = TARGET_COMPANIES[: args.limit] if args.limit else TARGET_COMPANIES
    logger.info("Verifying ATS endpoints for %d companies (%d workers)…",
                len(companies), args.workers)

    verified: dict[str, dict] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(verify_company, c): c for c in companies}
        for fut in as_completed(futures):
            res = fut.result()
            done += 1
            if res["verified"]:
                verified[res["name"]] = {
                    "ats": res["ats"], "endpoint": res["endpoint"], "verified": True,
                }
                logger.info("[%d/%d] ✅ %s → %s", done, len(companies), res["name"], res["ats"])
            if done % 25 == 0:
                pct = int(done / len(companies) * 100)
                logger.info("[%d%%] %d/%d probed — %d confirmed so far",
                            pct, done, len(companies), len(verified))

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(verified, indent=2, ensure_ascii=False))
    logger.info("DONE. %d/%d companies have a confirmed direct ATS endpoint.",
                len(verified), len(companies))
    logger.info("Saved → %s", _OUT)
    logger.info("(The rest are still covered via LinkedIn company-filtered search.)")


if __name__ == "__main__":
    main()
