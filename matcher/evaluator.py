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
You are evaluating a job posting for {NAME or "this candidate"}. Score it rigorously.

JOB POSTING:
Title: {job.title}
Company: {job.company}
Location: {job.location}
Salary: {job.salary or "not stated"}
URL: {job.url}

DESCRIPTION (first 800 chars):
{job.description[:800]}

---
SCORING CRITERIA:
- CV fit: Does his real experience directly match what the role needs? (40% of score)
- Career vision fit: Does this role advance his 10-year goals? (30% of score)
- Growth potential: Will this role challenge him and open elite doors? (20% of score)
- Practical fit: Location, seniority, language, visa requirements. (10% of score)

SCORING SCALE:
9-10: Exceptional — nearly perfect fit, apply immediately
7-8:  Strong match — clear fit, worth a tailored application
5-6:  Partial match — some alignment, but notable gaps or misalignments
3-4:  Weak match — apply only if nothing better available
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
  "one_line_summary": "<20 words max — what this role is and why it fits/doesn't>",
  "why_it_fits": "<2-3 sentences — specific CV evidence that matches the role>",
  "why_it_doesnt_fit": "<1-2 sentences — honest gaps or misalignments, empty string if none>",
  "matched_skills": ["<skill1>", "<skill2>", "..."],
  "skill_gaps": ["<gap1>", "..."],
  "career_vision_alignment": "<2-3 sentences — how this role advances his 10-year goals>",
  "career_path_potential": "<2-3 sentences — where this role leads in 3-5 years>",
  "suggested_cv_angles": ["<which experience/bullet to lead with>", "..."],
  "salary_assessment": "<assessment of whether stated/implied salary matches his 6-figure target, or 'not stated'>"
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
