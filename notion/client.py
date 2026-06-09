"""
Notion integration — creates a rich page per matched job in the configured database.

Each page contains:
- Job metadata (title, company, location, salary, URL)
- Match score + verdict
- Full match analysis with career path potential
- CV tailoring notes
- Skills matched / gaps
- Status tracker (To Apply → Applied → Interview → Offer)
"""

import logging
import time
from datetime import datetime

import httpx

import config

logger = logging.getLogger(__name__)

_API = "https://api.notion.com/v1"
_VERSION = "2022-06-28"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.NOTION_API_KEY}",
        "Notion-Version": _VERSION,
        "Content-Type": "application/json",
    }


def _rich_text(text: str, bold: bool = False) -> list:
    return [{"type": "text", "text": {"content": text[:2000]},
             "annotations": {"bold": bold}}]


def _paragraph(text: str, bold: bool = False) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(text, bold=bold)},
    }


def _heading2(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": _rich_text(text)},
    }


def _heading3(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": _rich_text(text)},
    }


def _bullet(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text(text)},
    }


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _score_emoji(score: int) -> str:
    if score >= 9:
        return "🔥"
    if score >= 8:
        return "✅"
    if score >= 5:
        return "🟡"
    return "🔴"


def create_job_page(job: object, evaluation: dict) -> str | None:
    """
    Create a Notion page for this matched job. Returns the page URL or None on failure.
    CV and cover letter are NOT generated here — set "Generate Docs" to "Yes" in Notion
    to trigger generation on demand via: python main.py --generate-docs
    """
    """
    Create a Notion page for this matched job. Returns the page URL or None on failure.
    Rate limit: 3 req/s — caller should add delays between bulk creates.
    """
    if not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID:
        logger.warning("[notion] API key or database ID not configured — skipping Notion.")
        return None

    score = evaluation.get("score", 0)
    verdict = evaluation.get("verdict", "UNKNOWN")
    emoji = _score_emoji(score)

    # ── Page properties ───────────────────────────────────────────────────
    properties = {
        "Job Title": {
            "title": [{"text": {"content": f"{emoji} {job.title}"}}]
        },
        "Company": {
            "rich_text": _rich_text(job.company)
        },
        "Location": {
            "rich_text": _rich_text(job.location)
        },
        "Match Score": {
            "number": score
        },
        "Verdict": {
            "select": {"name": verdict}
        },
        "Status": {
            "select": {"name": "To Apply"}
        },
        "Application Link": {
            "url": job.url
        },
        "Source": {
            "select": {"name": job.source}
        },
        "Date Found": {
            "date": {"start": datetime.utcnow().strftime("%Y-%m-%d")}
        },
        "Generate Docs": {
            "select": {"name": "No"}
        },
    }

    if job.salary:
        properties["Salary"] = {"rich_text": _rich_text(job.salary)}

    # ── Page body blocks ───────────────────────────────────────────────────
    blocks = [
        _heading2("📋 Match Summary"),
        _paragraph(evaluation.get("one_line_summary", ""), bold=True),
        _paragraph(f"Score: {score}/10 · {verdict}"),
        _divider(),

        _heading2("✅ Why It Fits"),
        _paragraph(evaluation.get("why_it_fits", "")),

        _heading2("⚡ Career Vision Alignment"),
        _paragraph(evaluation.get("career_vision_alignment", "")),

        _heading2("🚀 Career Path Potential"),
        _paragraph(evaluation.get("career_path_potential", "")),
    ]

    if evaluation.get("why_it_doesnt_fit"):
        blocks += [
            _heading2("⚠️ Honest Gaps / Watch-outs"),
            _paragraph(evaluation.get("why_it_doesnt_fit", "")),
        ]

    blocks.append(_divider())
    blocks.append(_heading2("🎯 Matched Skills"))
    for skill in evaluation.get("matched_skills", []):
        blocks.append(_bullet(skill))

    if evaluation.get("skill_gaps"):
        blocks.append(_heading2("📚 Skill Gaps"))
        for gap in evaluation.get("skill_gaps", []):
            blocks.append(_bullet(gap))

    blocks.append(_divider())
    blocks.append(_heading2("📄 CV & Cover Letter"))
    blocks.append(_paragraph(
        "👆 Set 'Generate Docs' → Yes above to generate a tailored CV + cover letter for this role."
    ))

    if evaluation.get("salary_assessment"):
        blocks.append(_divider())
        blocks.append(_heading2("💰 Salary Assessment"))
        blocks.append(_paragraph(evaluation.get("salary_assessment", "")))

    blocks.append(_divider())
    blocks.append(_heading2("📝 Application Notes"))
    blocks.append(_paragraph("Add your notes here..."))

    payload = {
        "parent": {"database_id": config.NOTION_DATABASE_ID},
        "properties": properties,
        "children": blocks[:100],  # Notion limits children per request
    }

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(f"{_API}/pages", json=payload, headers=_headers())
            resp.raise_for_status()
            page = resp.json()
            url = page.get("url", "")
            logger.info("[notion] Page created: %s", url)
            return url

    except httpx.HTTPStatusError as exc:
        logger.error("[notion] HTTP %s creating page: %s", exc.response.status_code, exc.response.text[:300])
        return None
    except Exception as exc:
        logger.error("[notion] Unexpected error: %s", exc)
        return None


def get_pending_doc_requests() -> list[dict]:
    """
    Query Notion for all job pages where Generate Docs = 'Yes'.
    Returns list of dicts: {page_id, job_url, job_title, company, location}.
    """
    if not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID:
        return []

    payload = {
        "filter": {
            "property": "Generate Docs",
            "select": {"equals": "Yes"}
        }
    }

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{_API}/databases/{config.NOTION_DATABASE_ID}/query",
                json=payload,
                headers=_headers(),
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])

        pages = []
        for p in results:
            props = p.get("properties", {})
            title_list = props.get("Job Title", {}).get("title", [])
            title = title_list[0]["text"]["content"] if title_list else "Unknown"
            # Strip leading emoji from title
            title = title.lstrip("🔥✅🟡🔴 ")

            company_rt = props.get("Company", {}).get("rich_text", [])
            company = company_rt[0]["text"]["content"] if company_rt else "Unknown"

            loc_rt = props.get("Location", {}).get("rich_text", [])
            location = loc_rt[0]["text"]["content"] if loc_rt else ""

            url = props.get("Application Link", {}).get("url", "")

            pages.append({
                "page_id": p["id"],
                "job_title": title,
                "company": company,
                "location": location,
                "job_url": url,
            })

        return pages

    except Exception as exc:
        logger.error("[notion] Failed to query pending docs: %s", exc)
        return []


def mark_docs_generated(page_id: str, cv_path: str, cover_letter_path: str,
                         tailoring_notes: str) -> None:
    """
    Update the Notion page after docs are generated:
    - Set Generate Docs → Done
    - Append CV path + cover letter path + tailoring notes to the page body
    """
    if not config.NOTION_API_KEY:
        return

    # Update the Generate Docs property → Done
    try:
        with httpx.Client(timeout=15) as client:
            client.patch(
                f"{_API}/pages/{page_id}",
                json={"properties": {"Generate Docs": {"select": {"name": "Done"}}}},
                headers=_headers(),
            ).raise_for_status()
    except Exception as exc:
        logger.error("[notion] Failed to mark docs as done: %s", exc)

    # Append CV details as new blocks
    new_blocks = []
    if tailoring_notes:
        new_blocks.append(_heading3("CV Tailoring Notes"))
        new_blocks.append(_paragraph(tailoring_notes))
    if cv_path:
        new_blocks.append(_paragraph(f"✅ CV: {cv_path}"))
    if cover_letter_path:
        new_blocks.append(_paragraph(f"✅ Cover Letter: {cover_letter_path}"))

    if not new_blocks:
        return

    try:
        with httpx.Client(timeout=15) as client:
            client.patch(
                f"{_API}/blocks/{page_id}/children",
                json={"children": new_blocks},
                headers=_headers(),
            ).raise_for_status()
    except Exception as exc:
        logger.error("[notion] Failed to append doc paths to page: %s", exc)
