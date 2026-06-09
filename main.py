"""
Job Hunter — main entry point.

Usage:
  python main.py                    # full pipeline (scrape + evaluate + generate)
  python main.py --scrape-only      # scrape only, no evaluation
  python main.py --evaluate-only    # evaluate already-scraped jobs
  python main.py --url <URL>        # process a single job URL
  python main.py --query <text>     # add extra search query

Output structure:
  applications/
    [score]_[Company]_[Title]/
      job.txt           ← full job description
      evaluation.json   ← Gemini scoring details
      CV.pdf            ← tailored CV for this role
      CoverLetter.pdf   ← tailored cover letter
"""

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── Pre-flight: make sure setup has been run, with a friendly message ─────────
_PROFILE = Path(__file__).parent / "inputs" / "profile.json"
if not _PROFILE.exists():
    print(
        "\n─────────────────────────────────────────────────────────────\n"
        "  Almost there — this app isn't set up yet!\n"
        "─────────────────────────────────────────────────────────────\n"
        "  It needs to know who it's job-hunting for. To set it up:\n\n"
        "    • Run:  python setup.py   (a friendly wizard)\n"
        "    • Or open Claude and say: \"Set up my job hunter\"\n\n"
        "  See START_HERE.md for the full 3-step guide.\n"
        "─────────────────────────────────────────────────────────────\n"
    )
    sys.exit(1)

import config
from scraper.runner import run_scraper, load_unprocessed

# ── Keyword pre-filter ────────────────────────────────────────────────────────
# Job titles containing any of these words are skipped instantly — no API call.
_SKIP_TITLE_KEYWORDS = {
    "software", "devops", "frontend", "backend", "fullstack", "full-stack",
    "data scientist", "data engineer", "data analyst", "machine learning",
    "cybersecurity", "security engineer", "network engineer", "cloud engineer",
    "marketing", "sales", "hr ", "human resources", "recruiter", "accountant",
    "finance", "legal", "lawyer", "designer", "ux", "ui ", "graphic",
    "journalist", "copywriter", "content", "social media",
    "nursing", "doctor", "physician", "pharmacist",
    "senior process", "lead process", "principal engineer",  # too senior
    # Pharma/biotech (not relevant — Notion feedback showed 🔴 on these)
    "bioprocess", "biologics", "biopharmaceutical", "drug substance",
    "validation engineer", "clinical", "pharmaceutical process",
}

def _is_relevant_title(title: str) -> bool:
    """Return False if the job title is obviously not relevant — saves API tokens."""
    t = title.lower()
    return not any(kw in t for kw in _SKIP_TITLE_KEYWORDS)
from scraper.base import JobPosting
from matcher.evaluator import evaluate_job
from matcher.cv_editor import create_tailored_cv
from matcher.cover_letter import create_cover_letter
from notion.client import create_job_page, get_pending_doc_requests, mark_docs_generated
from notion.feedback import read_feedback, apply_feedback_to_run
from data.target_companies import is_target_company

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.ROOT / "job_hunter.log"),
    ],
)
logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_processed() -> list[dict]:
    if config.JOBS_PROCESSED.exists():
        return json.loads(config.JOBS_PROCESSED.read_text())
    return []


def _save_processed(records: list[dict]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.JOBS_PROCESSED.write_text(json.dumps(records, indent=2, ensure_ascii=False))


def _safe_name(company: str, title: str) -> str:
    """Slug-safe folder name from company + title."""
    raw = f"{company}_{title}"
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in raw)[:55]


# ── Core processing ───────────────────────────────────────────────────────────

def process_job(job: JobPosting) -> dict | None:
    """
    Evaluate one job. If it meets the threshold:
      1. Create application folder  →  applications/[score]_[Company]_[Title]/
      2. Save job.txt and evaluation.json
      3. Generate tailored CV + cover letter IN PARALLEL (saves ~15s per job)
      4. Push to Notion (if configured)

    Returns the evaluation record (always), or None on hard error.
    """
    # ── Keyword pre-filter — zero API tokens ──────────────────────────────
    if not _is_relevant_title(job.title):
        logger.info("  → Pre-filtered (irrelevant title): %s", job.title)
        return {"score": 0, "verdict": "FILTERED", "job_id": job.job_id,
                "title": job.title, "company": job.company,
                "location": job.location, "url": job.url, "source": job.source}

    logger.info("Evaluating: %s @ %s", job.title, job.company)

    evaluation = evaluate_job(job)
    score = evaluation.get("score", 0)
    verdict = evaluation.get("verdict", "UNKNOWN")
    company_tier = evaluation.get("company_tier", "UNKNOWN")

    # ── Target-company booster ────────────────────────────────────────────
    # If the hiring company is one of our 500+ target companies, it is by
    # definition a top corp / notable employer — never let it be SKIP'd.
    if is_target_company(job.company) and company_tier == "SKIP":
        logger.info("  → Target company '%s' — overriding SKIP → TOP_CORP", job.company)
        company_tier = "TOP_CORP"
        evaluation["company_tier"] = "TOP_CORP"

    logger.info("  → Score %d/10 [%s] | Company: %s", score, verdict, company_tier)

    # Skip unknown SMEs and recruitment agencies outright
    if company_tier == "SKIP":
        logger.info("  → Skipped (unknown/small company — not a top corp or notable startup)")
        return {"score": 0, "verdict": "SKIPPED", "company_tier": "SKIP",
                "job_id": job.job_id, "title": job.title, "company": job.company,
                "location": job.location, "url": job.url, "source": job.source}

    record = {
        "job_id":             job.job_id,
        "title":              job.title,
        "company":            job.company,
        "location":           job.location,
        "url":                job.url,
        "source":             job.source,
        "score":              score,
        "verdict":            verdict,
        "notion_url":         None,
        "cv_path":            None,
        "cover_letter_path":  None,
        **evaluation,
    }

    if score < config.MIN_MATCH_SCORE:
        return record

    # ── Application folder — job.txt + evaluation.json only ───────────────
    folder_name = f"{score:02d}_{_safe_name(job.company, job.title)}"
    app_dir = config.APPLICATIONS_DIR / folder_name
    app_dir.mkdir(parents=True, exist_ok=True)

    (app_dir / "job.txt").write_text(
        f"Title:    {job.title}\n"
        f"Company:  {job.company}\n"
        f"Location: {job.location}\n"
        f"Salary:   {job.salary or 'not stated'}\n"
        f"URL:      {job.url}\n"
        f"Source:   {job.source}\n"
        f"Score:    {score}/10  [{verdict}]\n"
        f"\n{'─' * 60}\n\n"
        f"{job.description}",
        encoding="utf-8",
    )

    (app_dir / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── Notion — no CV/CL yet; user triggers generation via "Generate Docs" ─
    try:
        notion_url = create_job_page(job=job, evaluation=evaluation)
        record["notion_url"] = notion_url
        if notion_url:
            logger.info("  → Notion: %s", notion_url)
        time.sleep(0.4)
    except Exception as exc:
        logger.error("  → Notion failed: %s", exc)

    logger.info("  → Saved to: applications/%s/ (CV/CL pending — set Generate Docs → Yes in Notion)", folder_name)
    return record


# ── On-demand doc generation (triggered by Notion "Generate Docs = Yes") ─────

def generate_docs_for_pending() -> None:
    """
    Poll Notion for jobs with Generate Docs = 'Yes'.
    For each, fetch the cached evaluation.json, generate CV + cover letter,
    then update the Notion page to 'Done' with the file paths.
    """
    pending = get_pending_doc_requests()
    if not pending:
        logger.info("[generate-docs] No pending requests in Notion.")
        return

    logger.info("[generate-docs] %d job(s) queued for doc generation.", len(pending))

    for req in pending:
        page_id   = req["page_id"]
        job_url   = req["job_url"]
        job_title = req["job_title"]
        company   = req["company"]
        location  = req["location"]

        logger.info("[generate-docs] Generating docs for: %s @ %s", job_title, company)

        # Find the local evaluation.json by matching on company + title slug
        slug = _safe_name(company, job_title)
        matches = list(config.APPLICATIONS_DIR.glob(f"*{slug[:30]}*/evaluation.json"))

        # Fallback: scan all evaluation.json files for matching URL
        if not matches:
            matches = [
                p for p in config.APPLICATIONS_DIR.glob("*/evaluation.json")
                if job_url and job_url in p.read_text(encoding="utf-8")
            ]

        if not matches:
            logger.error("  → No local evaluation.json found for %s — skipping.", job_title)
            continue

        eval_path = matches[0]
        evaluation = json.loads(eval_path.read_text(encoding="utf-8"))
        app_dir    = eval_path.parent

        # Read job description from job.txt
        job_txt = app_dir / "job.txt"
        description = ""
        salary = ""
        if job_txt.exists():
            raw = job_txt.read_text(encoding="utf-8")
            for line in raw.splitlines():
                if line.startswith("Salary:"):
                    salary = line.split(":", 1)[1].strip()
            desc_start = raw.find("─" * 10)
            if desc_start != -1:
                description = raw[desc_start + 62:].strip()

        # Reconstruct a minimal JobPosting-like object
        from scraper.base import JobPosting
        job_obj = JobPosting(
            title=job_title,
            company=company,
            location=location,
            description=description,
            url=job_url,
            source="notion",
            job_id=page_id,
            salary=salary or None,
        )

        cv_path = None
        cl_path = None
        tailoring_notes = ""

        def _gen_cv():
            return create_tailored_cv(job_obj, evaluation, app_dir)

        def _gen_cl():
            return create_cover_letter(job_obj, evaluation, app_dir)

        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_cv = pool.submit(_gen_cv)
            fut_cl = pool.submit(_gen_cl)
            for fut in as_completed([fut_cv, fut_cl]):
                try:
                    result = fut.result()
                    if fut is fut_cv:
                        cv_path, tailoring_notes = result
                        logger.info("  → CV:           %s", cv_path.name)
                    else:
                        cl_path = result
                        logger.info("  → Cover letter: %s", cl_path.name)
                except Exception as exc:
                    label = "CV" if fut is fut_cv else "Cover letter"
                    logger.error("  → %s generation failed: %s", label, exc)

        mark_docs_generated(
            page_id=page_id,
            cv_path=str(cv_path) if cv_path else "",
            cover_letter_path=str(cl_path) if cl_path else "",
            tailoring_notes=tailoring_notes,
        )
        logger.info("  → Notion updated → Done.")
        time.sleep(0.5)

    logger.info("[generate-docs] Complete.")


# ── Single-URL helper ─────────────────────────────────────────────────────────

def scrape_single_url(url: str) -> JobPosting | None:
    """Fetch and parse a single job URL (used by --url flag)."""
    import httpx
    from bs4 import BeautifulSoup
    import hashlib

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title_el = soup.select_one("h1")
        title = title_el.get_text(strip=True) if title_el else "Unknown Role"

        # Try to extract company name
        company_el = (
            soup.select_one("a.topcard__org-name-link")
            or soup.select_one("span.topcard__flavor")
            or soup.select_one("[data-testid='inlineHeader-companyName']")
        )
        company = company_el.get_text(strip=True) if company_el else "Unknown"

        desc_el = (
            soup.select_one("div.show-more-less-html__markup")
            or soup.select_one("div#jobDescriptionText")
            or soup.select_one("main")
        )
        description = desc_el.get_text(separator="\n", strip=True)[:5000] if desc_el else ""
        job_id = hashlib.md5(url.encode()).hexdigest()[:12]

        return JobPosting(
            title=title, company=company, location="Unknown",
            description=description, url=url, source="manual", job_id=job_id,
        )
    except Exception as exc:
        logger.error("Failed to fetch URL %s: %s", url, exc)
        return None


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Job Hunter — AI-powered job search & application assistant")
    parser.add_argument("--scrape-only",    action="store_true", help="Scrape only, skip evaluation")
    parser.add_argument("--evaluate-only",  action="store_true", help="Evaluate scraped jobs, skip scraping")
    parser.add_argument("--generate-docs",  action="store_true", help="Generate CV+CL for Notion jobs with Generate Docs = Yes")
    parser.add_argument("--url",   type=str, help="Process a single job URL end-to-end")
    parser.add_argument("--query", type=str, help="Add an extra search query for this run")
    args = parser.parse_args()

    # ── Read Notion feedback — improve filters before every run ───────────
    if not args.generate_docs and not args.url:
        logger.info("Reading Notion feedback to improve filters…")
        read_feedback()
        global _SKIP_TITLE_KEYWORDS
        updated_skip, updated_queries = apply_feedback_to_run(
            _SKIP_TITLE_KEYWORDS, config.SEARCH_QUERIES
        )
        _SKIP_TITLE_KEYWORDS = updated_skip
        config.SEARCH_QUERIES = updated_queries

    # ── Generate docs mode ─────────────────────────────────────────────────
    if args.generate_docs:
        generate_docs_for_pending()
        return

    # ── Single URL mode ────────────────────────────────────────────────────
    if args.url:
        job = scrape_single_url(args.url)
        if job:
            processed = _load_processed()
            record = process_job(job)
            if record:
                processed.append(record)
                _save_processed(processed)
        return

    if args.query:
        config.SEARCH_QUERIES.append(args.query)

    # ── Phase 1: Scrape ────────────────────────────────────────────────────
    if not args.evaluate_only:
        logger.info("=" * 60)
        logger.info("PHASE 1: Scraping job boards")
        logger.info("=" * 60)
        run_scraper()

    # ── Phase 2: Evaluate ──────────────────────────────────────────────────
    if not args.scrape_only:
        logger.info("=" * 60)
        logger.info("PHASE 2: Evaluating jobs")
        logger.info("=" * 60)
        jobs = load_unprocessed()
        logger.info("%d unprocessed jobs queued.", len(jobs))

        processed = _load_processed()
        new_matches = 0

        for job in jobs:
            record = process_job(job)
            if record:
                processed.append(record)
                _save_processed(processed)
                if record.get("score", 0) >= config.MIN_MATCH_SCORE:
                    new_matches += 1
            time.sleep(1)

        logger.info("=" * 60)
        logger.info(
            "DONE. %d new matches (score ≥ %d) from %d jobs evaluated.",
            new_matches, config.MIN_MATCH_SCORE, len(jobs),
        )
        if new_matches:
            logger.info("Applications: %s", config.APPLICATIONS_DIR)
        logger.info("=" * 60)


if __name__ == "__main__":
    main()
