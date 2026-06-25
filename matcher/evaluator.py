"""
Gemini-powered job fit evaluator.

Returns a structured score (1–10) with detailed reasoning, matched skills, gaps,
and career-vision alignment for each job posting.
"""

import json
import logging
import re

import config
from career_profile import SYSTEM_CONTEXT, NAME
from matcher.ai_client import generate as _ai_generate
from scraper.base import JobPosting

logger = logging.getLogger(__name__)


def _generate(prompt: str) -> str:
    """Generate via shared AI client (Groq → Gemini failover)."""
    return _ai_generate(prompt, system=SYSTEM_CONTEXT, max_tokens=1024)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that Claude sometimes adds."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ── Batched triage ──────────────────────────────────────────────────────────
# A cheap, high-throughput first pass that scores many jobs in a single request
# using the fast triage model. Only jobs that look promising here are sent for
# full evaluation, so one run can cover the entire fresh-job pool instead of
# stalling on per-job rate limits.

_TRIAGE_INSTRUCTIONS = f"""You are rapidly triaging job postings for {NAME or "this candidate"}.
For EACH job, give a quick fit score from 1-10 using these non-negotiable rules:

- EARLY-CAREER ONLY: MSc graduated Oct 2025, 0-2 years experience. Senior/lead/
  principal/managerial roles, or roles requiring >4 years experience → score ≤ 4.
- LANGUAGES: works in English, French (B2), Greek only. If the role REQUIRES
  fluency in another language (German, Spanish, Italian, Dutch, etc.) → score ≤ 3.
- WORK AUTH: EU citizen. Roles needing a non-EU visa (USA, Canada, UAE, etc.) → score ≤ 3.
- Otherwise score by fit to his profile: process / manufacturing / operations /
  project / mechanical / industrial engineering and graduate programmes at strong
  employers score highest.

Also classify the company:
- "TOP_CORP": globally recognised corporation (Fortune 500 / DAX / CAC 40 / FTSE 100).
- "NOTABLE_STARTUP": funded scale-up or well-known tech/engineering company.
- "SKIP": unknown SME, tiny local firm, or recruitment agency with no named client.

Return ONLY a compact JSON array, one object per job, no preamble or markdown:
[{{"id":"<job_id>","s":<1-10>,"t":"<TOP_CORP|NOTABLE_STARTUP|SKIP>"}}]
Include every job id exactly once."""


def triage_batch(jobs: list[JobPosting]) -> dict[str, dict]:
    """
    Score a batch of jobs in a single cheap API call.

    Returns {job_id: {"score": int, "tier": str}}. Raises on API/parse failure
    so the caller can fall back to treating the batch as un-triaged.
    """
    if not jobs:
        return {}

    blocks = []
    for j in jobs:
        desc = (j.description or "")[:280].replace("\n", " ")
        blocks.append(
            f"id: {j.job_id}\n"
            f"title: {j.title}\n"
            f"company: {j.company}\n"
            f"location: {j.location}\n"
            f"desc: {desc}"
        )

    prompt = (
        _TRIAGE_INSTRUCTIONS
        + "\n\nJOBS TO TRIAGE:\n"
        + "\n---\n".join(blocks)
    )

    raw = _ai_generate(
        prompt,
        system=SYSTEM_CONTEXT,
        max_tokens=80 * len(jobs) + 200,
        model=config.GROQ_TRIAGE_MODEL,
        mark_exhausted=False,   # a triage rate-limit must not starve deep evals of Groq
    )
    arr = json.loads(_strip_fences(raw))

    out: dict[str, dict] = {}
    for d in arr:
        jid = d.get("id")
        if not jid:
            continue
        try:
            score = int(d.get("s", 0))
        except (TypeError, ValueError):
            score = 0
        out[jid] = {"score": max(0, min(10, score)), "tier": d.get("t", "")}
    return out


_BATCH_EVAL_INSTRUCTIONS = f"""You are evaluating multiple job postings for {NAME or "this candidate"}.
Score each rigorously and honestly using the same hard rules as for a single evaluation.

CANDIDATE HARD CONSTRAINTS (non-negotiable):
- Seniority: EARLY-CAREER. MSc graduated Oct 2025, 0–2 years professional experience.
  NOT a fit for senior, lead, principal, staff, managerial, or "X+ years required" (X > 4).
  Graduate / junior / associate / entry-level roles are ideal.
- Languages: English (C2), French (B2), Greek (native).
  Does NOT speak German, Spanish, Italian, Dutch, Swedish, Finnish, Danish, Norwegian,
  Portuguese, Polish, or any other language at a professional level.
- Work authorisation: EU citizen (Greece). Roles requiring non-EU work visa are not viable.

HARD RULES (override all scoring weights):
1. Role REQUIRES fluency/native in any language other than English, French, or Greek
   → score MUST be ≤ 3 and language_fit = "BLOCKER"
2. Senior/lead/principal/managerial OR demands more than 4 years experience
   → score MUST be ≤ 4 and seniority_fit = "TOO_SENIOR"
3. Non-EU work visa required → score ≤ 3

SCORING SCALE:
9-10: Exceptional — nearly perfect fit, apply immediately
7-8:  Strong match — clear fit, worth a tailored application
5-6:  Partial match — some alignment, notable gaps
3-4:  Weak match / blocked by a hard rule
1-2:  Not a fit

COMPANY TIER:
- "TOP_CORP": Globally recognised corporation (Fortune 500, FTSE 100, DAX, CAC 40 — e.g. Siemens, Airbus, Pfizer, Shell, BMW, LVMH, McKinsey, BCG, Deloitte)
- "NOTABLE_STARTUP": Funded startup, scale-up, or well-known tech/engineering company
- "SKIP": Unknown SME, small local firm, recruitment agency posting for unnamed client

Return ONLY a JSON array, one object per job, in the same order as the input. No preamble, no markdown:
[
  {{
    "job_id": "<exact job_id from input>",
    "company_tier": "<TOP_CORP|NOTABLE_STARTUP|SKIP>",
    "score": <integer 1-10>,
    "verdict": "<STRONG_MATCH|GOOD_MATCH|PARTIAL_MATCH|WEAK_MATCH|NO_MATCH>",
    "seniority_fit": "<GOOD|STRETCH|TOO_SENIOR>",
    "language_fit": "<OK|BLOCKER>",
    "required_languages": ["<language and level explicitly required, or 'English only' / 'not stated'>"],
    "one_line_summary": "<20 words max — what this role is and why it fits/doesn't>",
    "why_it_fits": "<2-3 sentences — specific CV evidence that matches>",
    "why_it_doesnt_fit": "<1-2 sentences — honest gaps, or empty string if none>",
    "matched_skills": ["<skill1>", "<skill2>"],
    "skill_gaps": ["<gap1>"],
    "career_vision_alignment": "<2-3 sentences — how this role advances 10-year goals>",
    "career_path_potential": "<2-3 sentences — where this leads in 3-5 years>",
    "suggested_cv_angles": ["<which experience/bullet to lead with>"],
    "salary_assessment": "<assessment of salary vs target, or 'not stated'>"
  }}
]
Include every job_id exactly once."""


def evaluate_batch(jobs: list[JobPosting]) -> list[dict]:
    """
    Evaluate multiple jobs in a single API call.

    Uses the same scoring rules as evaluate_job() but batches 4 jobs per request,
    cutting API calls ~4× and per-job token cost ~40% vs individual calls.

    Returns a list of dicts (same structure as evaluate_job). Falls back to
    individual evaluate_job() calls if the batch response cannot be parsed.
    """
    if not jobs:
        return []
    if len(jobs) == 1:
        return [evaluate_job(jobs[0])]

    blocks = []
    for j in jobs:
        desc = (j.description or "")[:800].replace("\n", " ")
        blocks.append(
            f"job_id: {j.job_id}\n"
            f"Title: {j.title}\n"
            f"Company: {j.company}\n"
            f"Location: {j.location}\n"
            f"Salary: {j.salary or 'not stated'}\n"
            f"URL: {j.url}\n"
            f"Description: {desc}"
        )

    prompt = (
        _BATCH_EVAL_INSTRUCTIONS
        + "\n\nJOBS TO EVALUATE:\n"
        + "\n---\n".join(blocks)
    )

    try:
        raw = _generate(prompt)
        arr = json.loads(_strip_fences(raw))
        if not isinstance(arr, list):
            raise ValueError(f"Expected JSON array, got {type(arr).__name__}")

        id_to_job = {j.job_id: j for j in jobs}
        results: list[dict] = []
        found_ids: set[str] = set()

        for item in arr:
            jid = item.get("job_id", "")
            job = id_to_job.get(jid)
            if not job:
                continue
            item["job_id"]    = job.job_id
            item["job_title"] = job.title
            item["company"]   = job.company
            found_ids.add(jid)
            results.append(item)

        # Fall back individually for any job the model missed
        for job in jobs:
            if job.job_id not in found_ids:
                logger.warning("[evaluator] Batch missing result for %s — falling back", job.job_id)
                results.append(evaluate_job(job))

        return results

    except json.JSONDecodeError as exc:
        logger.error("[evaluator] Batch JSON parse error: %s — falling back to individual calls", exc)
    except Exception as exc:
        logger.error("[evaluator] Batch eval failed (%s) — falling back to individual calls", exc)

    # Full fallback: evaluate each job individually
    return [evaluate_job(job) for job in jobs]


def evaluate_job(job: JobPosting) -> dict:
    """
    Score a job posting against the candidate's CV and career vision.

    Returns:
        {
          "score": int (1-10),
          "verdict": "STRONG_MATCH" | "GOOD_MATCH" | "WEAK_MATCH" | "NO_MATCH",
          "one_line_summary": str,
          "why_it_fits": str,
          "why_it_doesnt_fit": str,
          "matched_skills": [str],
          "skill_gaps": [str],
          "career_vision_alignment": str,
          "career_path_potential": str,
          "suggested_cv_angles": [str],   # which CV bullets to emphasise
          "salary_assessment": str
        }
    """
    prompt = f"""
You are evaluating a job posting for {NAME or "this candidate"}. Score it rigorously and honestly.

CANDIDATE HARD CONSTRAINTS (non-negotiable):
- Seniority: EARLY-CAREER. MSc graduated Oct 2025, 0–2 years professional experience.
  He is NOT a fit for senior, lead, principal, staff, managerial, or "X+ years required"
  (where X > 4) roles. Graduate / junior / associate / entry-level roles are ideal.
- Languages he can work in: English (proficient, C2), French (B2 — working proficiency),
  Greek (native). He does NOT speak German, Spanish, Italian, Dutch, Swedish, Polish,
  Portuguese, or any other language at a professional level.
- Work authorisation: EU citizen (Greece). Can work across EU/EEA + Switzerland + UK
  visa-free or via the UK Graduate route. Roles requiring a non-EU work visa are not viable.

JOB POSTING:
Title: {job.title}
Company: {job.company}
Location: {job.location}
Salary: {job.salary or "not stated"}
URL: {job.url}

DESCRIPTION (first 1200 chars):
{job.description[:1200]}

---
SCORING CRITERIA (weighted):
- Experience / CV fit: Does his REAL experience and seniority match what the role needs?
  Is the required experience level realistic for a 0–2 year graduate? (35%)
- Career vision fit: Does this role advance his 10-year goals? (25%)
- Practical fit: seniority level, REQUIRED languages vs his (EN/FR/EL), work authorisation,
  location. (25%)
- Growth potential: Will this role challenge him and open elite doors? (15%)

HARD RULES (apply BEFORE anything else — these override the weighting):
1. If the role REQUIRES fluency/native level in a language he lacks (anything other than
   English, French, or Greek) → score MUST be ≤ 3 and language_fit = "BLOCKER".
2. If the role is senior/lead/principal/managerial OR demands more than 4 years of
   experience → score MUST be ≤ 4 and seniority_fit = "TOO_SENIOR".
3. If the role requires a non-EU work visa (e.g. USA, Canada, UAE, Singapore) → score ≤ 3.
Only roles that pass ALL hard rules may score 5 or above.

SCORING SCALE:
9-10: Exceptional — nearly perfect fit, apply immediately
7-8:  Strong match — clear fit, worth a tailored application
5-6:  Partial match — some alignment, but notable gaps
3-4:  Weak match / blocked by a hard rule
1-2:  Not a fit — do not waste time

COMPANY TIER — classify the hiring company:
- "TOP_CORP": Globally recognised corporation (Fortune 500, FTSE 100, DAX, CAC 40, well-known multinationals — e.g. Siemens, Airbus, Pfizer, Unilever, Shell, BMW, LVMH, McKinsey, BCG, Deloitte, etc.)
- "NOTABLE_STARTUP": Funded startup, scale-up, or well-known tech/engineering company (e.g. SpaceX, Rimac, Northvolt, any Series A+ startup with a real brand)
- "SKIP": Unknown SME, small local firm, recruitment agency posting on behalf of an unnamed client, or any company with no recognisable brand

Return ONLY a JSON object with exactly these keys (no preamble, no markdown):
{{
  "company_tier": "<TOP_CORP|NOTABLE_STARTUP|SKIP>",
  "score": <integer 1-10>,
  "verdict": "<STRONG_MATCH|GOOD_MATCH|PARTIAL_MATCH|WEAK_MATCH|NO_MATCH>",
  "seniority_fit": "<GOOD|STRETCH|TOO_SENIOR>",
  "language_fit": "<OK|BLOCKER>",
  "required_languages": ["<language and level explicitly required by the posting, or 'English only' / 'not stated'>"],
  "one_line_summary": "<20 words max — what this role is and why it fits/doesn't>",
  "why_it_fits": "<2-3 sentences — specific CV evidence that matches the role>",
  "why_it_doesnt_fit": "<1-2 sentences — honest gaps or misalignments, empty string if none>",
  "matched_skills": ["<skill1>", "<skill2>", "..."],
  "skill_gaps": ["<gap1>", "..."],
  "career_vision_alignment": "<2-3 sentences — how this role advances his 10-year goals>",
  "career_path_potential": "<2-3 sentences — where this role leads in 3-5 years>",
  "suggested_cv_angles": ["<which experience/bullet to lead with>", "..."],
  "salary_assessment": "<assessment of whether stated/implied salary matches his target, or 'not stated'>"
}}
"""

    try:
        raw = _generate(prompt)
        result = json.loads(_strip_fences(raw))
        result["job_id"] = job.job_id
        result["job_title"] = job.title
        result["company"] = job.company
        return result

    except json.JSONDecodeError as exc:
        logger.error("[evaluator] JSON parse error for %s @ %s: %s", job.title, job.company, exc)
        return {"score": 0, "verdict": "ERROR", "job_id": job.job_id}
    except Exception as exc:
        logger.error("[evaluator] API error: %s", exc)
        return {"score": 0, "verdict": "ERROR", "job_id": job.job_id}
