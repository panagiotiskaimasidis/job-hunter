"""
Job Hunter — main entry point.

Usage:
  python main.py                    # full pipeline (scrape + evaluate)
  python main.py --scrape-only      # scrape only, no evaluation
  python main.py --evaluate-only    # evaluate already-scraped jobs
  python main.py --url <URL>        # process a single job URL
  python main.py --query <text>     # add extra search query

Output structure:
  applications/
    [score]_[Company]_[Title]/
      job.txt           ← full job description
      evaluation.json   ← AI scoring details
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
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
    # ── Pure tech / non-engineering ───────────────────────────────────────────
    "software", "devops", "frontend", "backend", "fullstack", "full-stack",
    "data scientist", "data engineer", "data analyst", "machine learning",
    "cybersecurity", "security engineer", "network engineer", "cloud engineer",
    "marketing", "sales", "hr ", "human resources", "recruiter", "accountant",
    "finance", "legal", "lawyer", "designer", "ux", "ui ", "graphic",
    "journalist", "copywriter", "content", "social media",
    "nursing", "doctor", "physician", "pharmacist",
    # ── Too senior ────────────────────────────────────────────────────────────
    "senior process", "lead process", "principal engineer",
    "head of", "director", "vp ", "vice president",
    # ── Contract types to avoid (Notion feedback) ────────────────────────────
    "maternity cover", "maternity leave", "fixed term", "fixed-term",
    "temporary contract", "interim",
    # ── Unwanted systems (Notion feedback: "don't like HVAC/HVDC systems") ───
    "hvac", "hvdc", "heating ventilation", "air conditioning",
    # ── Security clearance required (Notion feedback: avoid) ─────────────────
    "security clearance", "sc cleared", "dv cleared", "nato secret",
    "clearance required",
    # ── Electrical design (not his field) ────────────────────────────────────
    "electrical design", "power electronics", "pcb design",
    # ── Pharma/biotech deep-science (not relevant — Notion feedback 🔴) ──────
    "bioprocess", "biologics", "biopharmaceutical", "drug substance",
    "validation engineer", "clinical", "pharmaceutical process",
}

def _is_relevant_title(title: str) -> bool:
    """Return False if the job title is obviously not relevant — saves API tokens."""
    t = title.lower()
    return not any(kw in t for kw in _SKIP_TITLE_KEYWORDS)


# ── Visa restriction filter ───────────────────────────────────────────────────
# As an EU (Greek) citizen, Panagiotis can work freely in EU/EEA + Switzerland.
# Jobs in these regions require a work visa and are filtered out at zero API cost.
_VISA_RESTRICTED_KEYWORDS = {
    # USA
    "united states", " usa", "u.s.a", ", usa",
    "new york", "san francisco", "los angeles", "california",
    "chicago", "boston", "seattle", "austin", "houston",
    "dallas", "denver", "atlanta", "miami", "phoenix",
    "washington, d.c", "washington dc", "silicon valley",
    # Canada
    "canada", "toronto", "vancouver", "montreal", "ottawa", "calgary",
    # Australia
    "australia", "sydney", "melbourne", "brisbane", "perth", "adelaide",
    # New Zealand
    "new zealand", "auckland", "wellington",
    # Singapore
    "singapore",
    # Japan
    "japan", "tokyo", "osaka",
    # China
    "china", "beijing", "shanghai", "guangzhou", "shenzhen",
    # South Korea
    "south korea", "seoul",
    # India
    "india", "mumbai", "bangalore", "bengaluru", "delhi", "hyderabad", "pune",
    # Middle East
    "saudi arabia", "riyadh", "jeddah",
    "united arab emirates", "dubai", "abu dhabi",
    "qatar", "doha",
    "kuwait", "bahrain", "muscat", "oman",
    # Southeast Asia
    "malaysia", "kuala lumpur",
    "indonesia", "jakarta",
    "thailand", "bangkok",
    "vietnam", "hanoi", "ho chi minh",
    # Latin America
    "brazil", "sao paulo", "são paulo", "rio de janeiro",
    "argentina", "buenos aires",
    "mexico city", "mexico,",
    # Africa
    "south africa", "johannesburg", "cape town",
    "nigeria", "lagos",
    # France (user preference — not interested in French-located roles)
    "france", "paris", "lyon", "marseille", "toulouse",
    "bordeaux", "nantes", "strasbourg", "lille", "nice, fr",
}


def _is_visa_accessible(location: str) -> bool:
    """Return False if the job is in a country requiring a work visa for an EU citizen."""
    loc = location.lower()
    return not any(kw in loc for kw in _VISA_RESTRICTED_KEYWORDS)


# ── Seniority filter ──────────────────────────────────────────────────────────
# Panagiotis is early-career (MSc graduated Oct 2025, 0–2 years experience).
# Roles demanding significant seniority are filtered before any AI call.
_SENIORITY_TITLE_KEYWORDS = {
    "senior", "sr.", "sr ", "lead ", "leader", "principal", "staff engineer",
    "head of", "chief", "director", "vp ", "vice president", "manager,",
    "manager -", "manager –", "engineering manager", "plant manager",
    "site manager", "general manager", "executive", "expert ", " expert",
    "specialist iii", "iii ", " iv ", "level 3", "level 4",
}

# Phrases in the description that signal a senior role requiring more experience
# than an early-career graduate has. Conservative — only strong signals.
import re as _re
_SENIORITY_DESC_PATTERNS = [
    _re.compile(r"\b(minimum|at least|min\.?|requires?)\s*(?:of\s*)?(\d{1,2})\+?\s*years?", _re.I),
    _re.compile(r"\b(\d{1,2})\+\s*years?\s+(?:of\s+)?(?:relevant\s+|professional\s+|industry\s+)?experience", _re.I),
    _re.compile(r"\b(\d{1,2})\s*-\s*\d{1,2}\s*years?\s+(?:of\s+)?experience", _re.I),
]
# Below this many required years, an early-career grad is still a plausible fit.
_MAX_REQUIRED_YEARS = 4


def _seniority_ok(title: str, description: str) -> tuple[bool, str]:
    """Return (ok, reason). False if the role is clearly too senior."""
    t = title.lower()
    for kw in _SENIORITY_TITLE_KEYWORDS:
        if kw in t:
            return False, f"senior title keyword '{kw.strip()}'"

    desc = description or ""
    for pat in _SENIORITY_DESC_PATTERNS:
        for m in pat.finditer(desc):
            # The years figure is the last numeric group in the match
            nums = [int(g) for g in m.groups() if g and g.isdigit()]
            if nums and max(nums) > _MAX_REQUIRED_YEARS:
                return False, f"requires {max(nums)}+ years experience"
    return True, ""


# ── Language filter ───────────────────────────────────────────────────────────
# Languages he can work in: English (proficient), French (B2 — working),
# Greek (native). A role that REQUIRES fluency/native level in any other
# language is not accessible. Conservative matching to avoid killing the
# English-language multinational roles he actually wants.
_BLOCKED_LANGUAGE_REQUIREMENTS = [
    # German
    "fluent in german", "fluent german", "native german", "german native",
    "business fluent german", "german (c1", "german (c2", "german c1", "german c2",
    "verhandlungssicher", "fließend deutsch", "fliessend deutsch",
    "sehr gute deutschkenntnisse", "muttersprache deutsch", "deutsch als muttersprache",
    "german is required", "german language is required", "proficiency in german",
    # Spanish
    "fluent in spanish", "native spanish", "spanish native", "spanish (c1", "spanish (c2",
    "español nativo", "nivel nativo de español", "imprescindible español",
    "dominio del español", "spanish is required", "proficiency in spanish",
    # Italian
    "fluent in italian", "native italian", "italian native", "italian (c1", "italian (c2",
    "italiano madrelingua", "ottima conoscenza dell'italiano", "italian is required",
    "proficiency in italian",
    # Dutch
    "fluent in dutch", "native dutch", "dutch native", "dutch (c1", "dutch (c2",
    "vloeiend nederlands", "uitstekende beheersing van het nederlands",
    "dutch is required", "proficiency in dutch",
    # Swedish / Nordic
    "fluent in swedish", "native swedish", "flytande svenska", "swedish is required",
    "fluent in finnish", "native finnish", "finnish is required",
    "fluent in danish", "native danish", "fluent in norwegian", "native norwegian",
    # Other
    "fluent in portuguese", "native portuguese", "portuguese is required",
    "fluent in polish", "native polish", "polish is required",
]


def _language_ok(description: str) -> tuple[bool, str]:
    """Return (ok, reason). False if the role requires a language he lacks."""
    d = (description or "").lower()
    for phrase in _BLOCKED_LANGUAGE_REQUIREMENTS:
        if phrase in d:
            return False, f"requires language he lacks ('{phrase}')"
    return True, ""


from scraper.base import JobPosting
from matcher.evaluator import evaluate_job
from notion.client import create_job_page
from notion.feedback import read_feedback, apply_feedback_to_run
from data.target_companies import is_target_company
from notifier.email_notifier import send_match_digest
from matcher.ai_client import get_token_stats, groq_was_exhausted

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

def process_job(job: JobPosting, allow_ai: bool = True) -> dict | None:
    """
    Evaluate one job. If it meets the threshold:
      1. Create application folder  →  applications/[score]_[Company]_[Title]/
      2. Save job.txt and evaluation.json
      3. Push to Notion (if configured)

    Free pre-filters (title/visa/seniority/language) always run. The expensive
    AI evaluation only runs when `allow_ai` is True — otherwise the job is
    returned with verdict "DEFERRED" so the caller can roll it over to the next
    run (protecting the daily API quota).

    Returns the evaluation record (always), or None on hard error.
    """
    # ── Keyword pre-filter — zero API tokens ──────────────────────────────
    if not _is_relevant_title(job.title):
        logger.info("  → Pre-filtered (irrelevant title): %s", job.title)
        return {"score": 0, "verdict": "FILTERED", "job_id": job.job_id,
                "title": job.title, "company": job.company,
                "location": job.location, "url": job.url, "source": job.source}

    # ── Visa restriction filter — zero API tokens ─────────────────────────
    if not _is_visa_accessible(job.location):
        logger.info("  → Visa-restricted location (%s): %s @ %s", job.location, job.title, job.company)
        return {"score": 0, "verdict": "VISA_RESTRICTED", "job_id": job.job_id,
                "title": job.title, "company": job.company,
                "location": job.location, "url": job.url, "source": job.source}

    # ── Seniority filter — zero API tokens ────────────────────────────────
    sen_ok, sen_reason = _seniority_ok(job.title, job.description)
    if not sen_ok:
        logger.info("  → Too senior (%s): %s @ %s", sen_reason, job.title, job.company)
        return {"score": 0, "verdict": "SENIORITY_MISMATCH", "job_id": job.job_id,
                "title": job.title, "company": job.company,
                "location": job.location, "url": job.url, "source": job.source}

    # ── Language filter — zero API tokens ─────────────────────────────────
    lang_ok, lang_reason = _language_ok(job.description)
    if not lang_ok:
        logger.info("  → Language mismatch (%s): %s @ %s", lang_reason, job.title, job.company)
        return {"score": 0, "verdict": "LANGUAGE_MISMATCH", "job_id": job.job_id,
                "title": job.title, "company": job.company,
                "location": job.location, "url": job.url, "source": job.source}

    # ── AI budget gate — roll this job over to the next run if exhausted ──
    if not allow_ai:
        return {"score": 0, "verdict": "DEFERRED", "job_id": job.job_id,
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

    logger.info("  → Saved to: applications/%s/", folder_name)
    return record


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


# ── Run summary ───────────────────────────────────────────────────────────────

def _write_run_summary(stats: dict, new_matches: list[dict]) -> Path:
    """Write a human-readable run summary to data/run_summary.txt and return its path."""
    tok = get_token_stats()
    groq = tok["groq"]
    gem  = tok.get("gemini", {})
    failover = groq_was_exhausted()

    total_req   = groq["requests"] + gem.get("requests", 0)
    total_prompt = groq["prompt"] + gem.get("prompt", 0)
    total_comp  = groq["completion"] + gem.get("completion", 0)
    total_tok   = groq["total"] + gem.get("total", 0)

    # Groq free-tier reference limits for llama-3.3-70b-versatile
    GROQ_REQ_LIMIT = 14_400
    groq_req_remaining = max(0, GROQ_REQ_LIMIT - groq["requests"])

    w = 62  # line width
    sep = "═" * w

    score_labels = {
        10: "STRONG_MATCH", 9: "STRONG_MATCH",
        8: "GOOD_MATCH",    7: "GOOD_MATCH",
        6: "PARTIAL_MATCH", 5: "PARTIAL_MATCH",
        4: "WEAK_MATCH",    3: "WEAK_MATCH",
        2: "NO_MATCH",      1: "NO_MATCH",
    }

    lines = [
        sep,
        f"  JOB HUNTER — Run Summary  ·  {stats['run_date']}",
        sep,
        "",
        "SCRAPING",
        f"  Total raw jobs in database   : {stats['raw_total']:>5}",
        f"  New (unprocessed this run)   : {stats['jobs_to_evaluate']:>5}",
        f"  Already seen / skipped       : {stats['already_seen']:>5}",
        "",
        "FILTERING  (zero API cost)",
        f"  Title pre-filter             : {stats['pre_filtered_title']:>5}",
        f"  Visa-restricted location     : {stats['pre_filtered_visa']:>5}",
        f"  Too senior (experience)      : {stats['pre_filtered_seniority']:>5}",
        f"  Language mismatch            : {stats['pre_filtered_language']:>5}",
        f"  {'─' * 36}",
        f"  Passed to AI evaluation      : {stats['ai_evaluated'] + stats['skipped_company_tier'] + stats['evaluation_errors']:>5}",
        "",
        "AI EVALUATION",
        f"  AI evals used / cap          : {stats['ai_evaluated'] + stats['skipped_company_tier'] + stats['evaluation_errors']:>5} / {stats['ai_cap']}",
        f"  Deferred to next run         : {stats['deferred']:>5}",
        f"  Company tier = SKIP          : {stats['skipped_company_tier']:>5}  (unknown/small company)",
        f"  Evaluation errors            : {stats['evaluation_errors']:>5}",
        f"  Scored jobs                  : {stats['ai_evaluated']:>5}",
    ]

    # Score breakdown
    sb = stats.get("score_breakdown", {})
    if any(sb.values()):
        lines.append("    Score breakdown:")
        for s in range(10, 0, -1):
            count = sb.get(s, 0)
            label = score_labels.get(s, "")
            lines.append(f"      {s:>2} — {label:<13} : {count:>3}")

    lines += [
        "",
        "MATCHES",
        f"  New matches (score ≥ {stats['min_score']})      : {stats['new_matches']:>5}",
        f"  Pushed to Notion             : {stats['notion_pushed']:>5}",
        "",
        "TOKEN USAGE",
        f"  {'Provider':<14} {'Requests':>9}  {'Prompt':>10}  {'Completion':>11}  {'Total':>8}",
        f"  {'─' * 56}",
        f"  {'Groq':<14} {groq['requests']:>9}  {groq['prompt']:>10,}  {groq['completion']:>11,}  {groq['total']:>8,}",
        f"  {'Gemini':<14} {gem.get('requests',0):>9}  {gem.get('prompt',0):>10,}  {gem.get('completion',0):>11,}  {gem.get('total',0):>8,}",
        f"  {'─' * 56}",
        f"  {'Total':<14} {total_req:>9}  {total_prompt:>10,}  {total_comp:>11,}  {total_tok:>8,}",
        "",
        f"  Groq daily quota  (llama-3.3-70b-versatile free tier)",
        f"    Requests used / limit      : {groq['requests']:>5} / {GROQ_REQ_LIMIT:,}",
        f"    Est. remaining requests    : {groq_req_remaining:>5,}",
        f"  Groq→Gemini failover         : {'TRIGGERED' if failover else 'not triggered'}",
    ]

    # Top matches
    if new_matches:
        lines += ["", "TOP NEW MATCHES"]
        for i, m in enumerate(new_matches[:10], 1):
            score   = m.get("score", 0)
            verdict = m.get("verdict", "")
            title   = m.get("title", "")
            company = m.get("company", "")
            loc     = m.get("location", "")
            lines.append(f"  {i:>2}. [{score:>2}/10] {verdict:<13} — {title} @ {company}  ·  {loc}")

    lines += ["", sep, ""]

    summary_path = config.DATA_DIR / "run_summary.txt"
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("[summary] Run summary written → %s", summary_path)
    return summary_path


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Job Hunter — AI-powered job search & application assistant")
    parser.add_argument("--scrape-only",   action="store_true", help="Scrape only, skip evaluation")
    parser.add_argument("--evaluate-only", action="store_true", help="Evaluate scraped jobs, skip scraping")
    parser.add_argument("--url",   type=str, help="Process a single job URL end-to-end")
    parser.add_argument("--query", type=str, help="Add an extra search query for this run")
    args = parser.parse_args()

    # ── Read Notion feedback — improve filters before every run ───────────
    if not args.url:
        logger.info("Reading Notion feedback to improve filters…")
        read_feedback()
        global _SKIP_TITLE_KEYWORDS
        updated_skip, updated_queries = apply_feedback_to_run(
            _SKIP_TITLE_KEYWORDS, config.SEARCH_QUERIES
        )
        _SKIP_TITLE_KEYWORDS = updated_skip
        config.SEARCH_QUERIES = updated_queries

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

        raw_total = 0
        if config.JOBS_RAW.exists():
            try:
                raw_total = len(json.loads(config.JOBS_RAW.read_text()))
            except Exception:
                pass

        stats = {
            "run_date":            datetime.utcnow().strftime("%Y-%m-%d  %H:%M UTC"),
            "raw_total":           raw_total,
            "jobs_to_evaluate":    len(jobs),
            "already_seen":        max(0, raw_total - len(jobs)),
            "pre_filtered_title":  0,
            "pre_filtered_visa":   0,
            "pre_filtered_seniority": 0,
            "pre_filtered_language":  0,
            "skipped_company_tier": 0,
            "evaluation_errors":   0,
            "ai_evaluated":        0,
            "score_breakdown":     {s: 0 for s in range(1, 11)},
            "new_matches":         0,
            "notion_pushed":       0,
            "min_score":           config.MIN_MATCH_SCORE,
            "ai_cap":              config.MAX_AI_EVALS_PER_RUN,
            "deferred":            0,
        }

        # Verdicts that cost no AI call (free pre-filters)
        FREE_VERDICTS = {"FILTERED", "VISA_RESTRICTED", "SENIORITY_MISMATCH", "LANGUAGE_MISMATCH"}

        processed = _load_processed()
        new_matches: list[dict] = []
        ai_used = 0

        for job in jobs:
            allow_ai = ai_used < config.MAX_AI_EVALS_PER_RUN
            record = process_job(job, allow_ai=allow_ai)
            if not record:
                time.sleep(1)
                continue

            verdict = record.get("verdict", "")
            score   = record.get("score", 0)

            # Budget exhausted: leave this job unprocessed so it rolls over.
            if verdict == "DEFERRED":
                stats["deferred"] += 1
                continue

            if verdict == "FILTERED":
                stats["pre_filtered_title"] += 1
            elif verdict == "VISA_RESTRICTED":
                stats["pre_filtered_visa"] += 1
            elif verdict == "SENIORITY_MISMATCH":
                stats["pre_filtered_seniority"] += 1
            elif verdict == "LANGUAGE_MISMATCH":
                stats["pre_filtered_language"] += 1
            elif verdict == "SKIPPED":
                stats["skipped_company_tier"] += 1
                ai_used += 1
            elif verdict == "ERROR":
                stats["evaluation_errors"] += 1
                ai_used += 1
            else:
                stats["ai_evaluated"] += 1
                ai_used += 1
                if 1 <= score <= 10:
                    stats["score_breakdown"][score] += 1

            if score >= config.MIN_MATCH_SCORE:
                new_matches.append(record)
                stats["new_matches"] += 1
                if record.get("notion_url"):
                    stats["notion_pushed"] += 1

            processed.append(record)
            _save_processed(processed)

            # Only pause after a real API call — free pre-filters need no delay.
            if verdict not in FREE_VERDICTS:
                time.sleep(1)

        if stats["deferred"]:
            logger.info(
                "AI cap (%d) reached — %d job(s) deferred to the next run.",
                config.MAX_AI_EVALS_PER_RUN, stats["deferred"],
            )

        logger.info("=" * 60)
        logger.info(
            "DONE. %d new matches (score ≥ %d) | %d AI evals used (cap %d) | %d deferred.",
            len(new_matches), config.MIN_MATCH_SCORE, ai_used,
            config.MAX_AI_EVALS_PER_RUN, stats["deferred"],
        )
        if new_matches:
            logger.info("Applications: %s", config.APPLICATIONS_DIR)
            send_match_digest(new_matches)

        _write_run_summary(stats, new_matches)
        logger.info("=" * 60)


if __name__ == "__main__":
    main()
