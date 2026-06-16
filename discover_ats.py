"""
ATS endpoint discovery — finds the OFFICIAL careers-API endpoint for each
target company, so the scraper can pull jobs straight from the source instead
of relying on LinkedIn.

The problem this solves
-----------------------
There is no universal "company careers API". Every employer uses a different
Applicant Tracking System (Workday, Greenhouse, Lever, SmartRecruiters, …) and
to query any of them you need that company's EXACT tenant slug. You cannot
reliably guess it. So this script brute-forces the public APIs with a handful
of name-derived slug candidates and records only the ones that actually return
data. The daily scraper then reads these CONFIRMED endpoints.

Covered (clean public APIs, no auth):
  - Greenhouse     boards-api.greenhouse.io/v1/boards/{slug}/jobs
  - Lever          api.lever.co/v0/postings/{slug}
  - SmartRecruiters api.smartrecruiters.com/v1/companies/{slug}/postings

NOT covered automatically: Workday / SuccessFactors / Taleo / iCIMS. Those need
an unguessable tenant number AND board path, so they must be captured manually
into data/target_companies_ats.json (Boeing & Thales already are).

Run this in CI (open network) — NOT in the dev sandbox (allowlisted):
    python discover_ats.py
It merges results into data/target_companies_ats.json.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from data.target_companies import company_names

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("discover_ats")

OUT_PATH = Path(__file__).parent / "data" / "target_companies_ats.json"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Corporate suffixes / filler stripped when building slug candidates
_SUFFIXES = {
    "group", "inc", "incorporated", "corporation", "corp", "company", "co",
    "plc", "ag", "sa", "se", "nv", "spa", "srl", "ltd", "limited", "gmbh",
    "holding", "holdings", "international", "technologies", "technology",
    "systems", "industries", "the",
}


def _slug_candidates(name: str) -> list[str]:
    """Generate likely ATS slug variants from a company name."""
    base = name.lower().strip()
    base = base.replace("&", "and")
    words = re.findall(r"[a-z0-9]+", base)
    core = [w for w in words if w not in _SUFFIXES] or words

    joined      = "".join(words)            # "johnsoncontrols"
    joined_core = "".join(core)             # "johnsoncontrols" (suffix-stripped)
    hyphen      = "-".join(words)           # "johnson-controls"
    hyphen_core = "-".join(core)
    first       = core[0] if core else (words[0] if words else "")

    # Order matters — tightest match first; dedupe preserving order
    cands = [joined_core, joined, hyphen_core, hyphen, first]
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _sr_candidates(name: str) -> list[str]:
    """SmartRecruiters slugs are usually PascalCase (e.g. 'BoschGroup')."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    pascal = "".join(w[:1].upper() + w[1:] for w in words)      # "JohnsonControls"
    first  = words[0] if words else ""
    return [c for c in (pascal, first, first.capitalize()) if c]


def _probe_greenhouse(client: httpx.Client, slug: str):
    try:
        r = client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        if r.status_code == 200:
            jobs = r.json().get("jobs", [])
            return {"ats": "greenhouse",
                    "endpoint": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                    "verified": True, "sample_jobs": len(jobs)}
    except Exception:
        pass
    return None


def _probe_lever(client: httpx.Client, slug: str):
    try:
        r = client.get(f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=1")
        if r.status_code == 200 and isinstance(r.json(), list):
            return {"ats": "lever",
                    "endpoint": f"https://api.lever.co/v0/postings/{slug}",
                    "verified": True, "sample_jobs": len(r.json())}
    except Exception:
        pass
    return None


def _probe_smartrecruiters(client: httpx.Client, slug: str):
    try:
        r = client.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1")
        if r.status_code == 200:
            data = r.json()
            return {"ats": "smartrecruiters",
                    "endpoint": f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                    "verified": True, "sample_jobs": data.get("totalFound", 0)}
    except Exception:
        pass
    return None


def discover_one(name: str) -> tuple[str, dict | None]:
    """Probe all platforms for a single company; return the first solid hit."""
    with httpx.Client(timeout=8, headers=_HEADERS, follow_redirects=True) as client:
        for slug in _slug_candidates(name):
            hit = _probe_greenhouse(client, slug) or _probe_lever(client, slug)
            if hit and hit.get("sample_jobs", 0) > 0:
                return name, hit
        for slug in _sr_candidates(name):
            hit = _probe_smartrecruiters(client, slug)
            if hit and hit.get("sample_jobs", 0) > 0:
                return name, hit
    return name, None


def main() -> None:
    existing: dict = {}
    if OUT_PATH.exists():
        try:
            existing = json.loads(OUT_PATH.read_text())
        except Exception:
            existing = {}

    names = company_names()
    logger.info("Probing %d companies across Greenhouse / Lever / SmartRecruiters…", len(names))

    found = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(discover_one, n) for n in names]
        for fut in as_completed(futures):
            name, hit = fut.result()
            if hit:
                found += 1
                # Never clobber a manually-verified Workday entry with a weaker guess
                prev = existing.get(name)
                if prev and prev.get("ats") == "workday":
                    continue
                existing[name] = hit
                logger.info("  ✓ %-32s %-15s (%s jobs)", name, hit["ats"], hit["sample_jobs"])

    OUT_PATH.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    logger.info("\nDiscovered %d company-direct endpoints. Total in map: %d → %s",
                found, len(existing), OUT_PATH)


if __name__ == "__main__":
    main()
