"""
Gemini-powered CV tailoring + PDF builder.

Strategy:
1. Ask Gemini to produce a tailored version of the CV *text* for the specific job.
2. Rebuild the PDF from scratch using reportlab, preserving the original visual design.

Constraint: Never invent experience. Gemini is explicitly instructed to only
reframe, reorder, and emphasise existing real content.
"""

import json
import logging
import re
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

import config
from career_profile import SYSTEM_CONTEXT, CV_TEXT, NAME, HEADLINE, CONTACT_LINE
from matcher.ai_client import generate as _ai_generate

logger = logging.getLogger(__name__)


def _generate(prompt: str) -> str:
    """Generate via shared AI client (Groq → Gemini failover)."""
    return _ai_generate(prompt, system=SYSTEM_CONTEXT, max_tokens=2048)

# ── Colour palette matching the original CV aesthetic ─────────────────────
_DARK = colors.HexColor("#1a1a2e")
_ACCENT = colors.HexColor("#2c5f8a")
_MID = colors.HexColor("#444444")
_LIGHT = colors.HexColor("#666666")
_LINE = colors.HexColor("#d0d0d0")


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_tailored_cv_content(job_title: str, company: str, job_description: str,
                                  evaluation: dict) -> dict:
    """
    Ask Claude to produce tailored CV content for this specific job.

    Returns a structured dict with sections ready for PDF generation.
    The output is 100% grounded in real CV content — no fabrications.
    """
    cv_angles = evaluation.get("suggested_cv_angles", [])
    matched_skills = evaluation.get("matched_skills", [])

    prompt = f"""
You are tailoring {NAME or "the candidate"}'s CV for a specific job application.

TARGET ROLE: {job_title} at {company}
KEY SKILLS THE ROLE NEEDS: {', '.join(matched_skills)}
CV ANGLES TO EMPHASISE: {', '.join(cv_angles)}

JOB DESCRIPTION (first 1000 chars):
{job_description[:1000]}

YOUR TASK:
Produce a tailored version of his CV optimised for this specific role.

STRICT RULES:
- NEVER invent, exaggerate, or fabricate any experience, metric, skill, or claim.
- ONLY reframe, reorder, and emphasise real content from the base CV provided.
- Mirror job-description language where his real experience genuinely matches.
- Lead with the most relevant experience for this role.
- Quantify impact where the base CV already provides numbers (400%, €60k, 8.36/10, etc.).
- Keep the professional summary sharp, specific to this role, max 3 sentences.
- Each bullet point must be action-verb led and outcome-focused.
- Remove or deprioritise experience least relevant to this role.
- Skills section should list only skills the JD values that he genuinely has.

Return ONLY a JSON object (no markdown fences, no preamble):
{{
  "professional_summary": "<3 sentences — who he is, what he brings to THIS role>",
  "experience": [
    {{
      "title": "<exact job title>",
      "company": "<company>",
      "location": "<location>",
      "period": "<dates>",
      "bullets": ["<bullet 1>", "<bullet 2>", ...]
    }}
  ],
  "education": [
    {{
      "degree": "<degree>",
      "institution": "<university>",
      "location": "<location>",
      "period": "<dates>",
      "details": ["<detail 1>", "<detail 2>"]
    }}
  ],
  "skills": {{
    "core_engineering": ["<skill1>", "..."],
    "software_tools": ["<tool1>", "..."],
    "languages": ["<lang1>", "..."]
  }},
  "tailoring_notes": "<1-2 sentences explaining what you changed and why>"
}}
"""

    raw = _generate(prompt)
    return json.loads(_strip_fences(raw))


def build_cv_pdf(cv_data: dict, output_path: Path, job_title: str, company: str) -> None:
    """Render the tailored CV data into a professional PDF."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18*mm,
        rightMargin=18*mm,
        topMargin=15*mm,
        bottomMargin=15*mm,
    )

    # ── Styles ────────────────────────────────────────────────────────────
    name_style = ParagraphStyle("Name", fontSize=20, leading=24, textColor=_DARK,
                                 fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=2)
    tagline_style = ParagraphStyle("Tagline", fontSize=10, leading=13, textColor=_ACCENT,
                                    fontName="Helvetica", alignment=TA_CENTER, spaceAfter=3)
    contact_style = ParagraphStyle("Contact", fontSize=8.5, leading=11, textColor=_MID,
                                    fontName="Helvetica", alignment=TA_CENTER, spaceAfter=8)
    section_style = ParagraphStyle("Section", fontSize=9.5, leading=12, textColor=_ACCENT,
                                    fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=3,
                                    textTransform="uppercase", letterSpacing=0.8)
    summary_style = ParagraphStyle("Summary", fontSize=9, leading=13, textColor=_MID,
                                    fontName="Helvetica", spaceAfter=6)
    job_title_style = ParagraphStyle("JobTitle", fontSize=9.5, leading=12, textColor=_DARK,
                                      fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=1)
    company_style = ParagraphStyle("Company", fontSize=8.5, leading=11, textColor=_LIGHT,
                                    fontName="Helvetica", spaceAfter=3)
    bullet_style = ParagraphStyle("Bullet", fontSize=8.5, leading=12, textColor=_MID,
                                   fontName="Helvetica", leftIndent=10, spaceAfter=1)
    edu_style = ParagraphStyle("Edu", fontSize=9, leading=12, textColor=_DARK,
                                fontName="Helvetica-Bold", spaceBefore=5, spaceAfter=1)
    edu_detail_style = ParagraphStyle("EduDetail", fontSize=8.5, leading=12, textColor=_MID,
                                       fontName="Helvetica", leftIndent=10, spaceAfter=1)
    skills_label_style = ParagraphStyle("SkillsLabel", fontSize=8.5, leading=11, textColor=_DARK,
                                         fontName="Helvetica-Bold", spaceAfter=1)
    skills_value_style = ParagraphStyle("SkillsVal", fontSize=8.5, leading=11, textColor=_MID,
                                         fontName="Helvetica", spaceAfter=4)

    story = []

    # ── Header (loaded from the candidate's profile) ──────────────────────
    story.append(Paragraph(NAME.upper(), name_style))
    if HEADLINE:
        story.append(Paragraph(HEADLINE, tagline_style))
    if CONTACT_LINE:
        story.append(Paragraph(CONTACT_LINE.replace("|", "&nbsp;|&nbsp;"), contact_style))
    story.append(HRFlowable(width="100%", thickness=1, color=_ACCENT, spaceAfter=6))

    # ── Professional Summary ───────────────────────────────────────────────
    if cv_data.get("professional_summary"):
        story.append(Paragraph("PROFESSIONAL SUMMARY", section_style))
        story.append(HRFlowable(width="100%", thickness=0.4, color=_LINE, spaceAfter=4))
        story.append(Paragraph(cv_data["professional_summary"], summary_style))

    # ── Experience ────────────────────────────────────────────────────────
    if cv_data.get("experience"):
        story.append(Paragraph("EXPERIENCE", section_style))
        story.append(HRFlowable(width="100%", thickness=0.4, color=_LINE, spaceAfter=4))
        for exp in cv_data["experience"]:
            story.append(Paragraph(exp.get("title", ""), job_title_style))
            company_line = f"{exp.get('company', '')} — {exp.get('location', '')} | {exp.get('period', '')}"
            story.append(Paragraph(company_line, company_style))
            for bullet in exp.get("bullets", []):
                story.append(Paragraph(f"• {bullet}", bullet_style))

    # ── Education ─────────────────────────────────────────────────────────
    if cv_data.get("education"):
        story.append(Paragraph("EDUCATION", section_style))
        story.append(HRFlowable(width="100%", thickness=0.4, color=_LINE, spaceAfter=4))
        for edu in cv_data["education"]:
            story.append(Paragraph(edu.get("degree", ""), edu_style))
            inst_line = f"{edu.get('institution', '')} — {edu.get('location', '')} | {edu.get('period', '')}"
            story.append(Paragraph(inst_line, company_style))
            for detail in edu.get("details", []):
                story.append(Paragraph(f"• {detail}", edu_detail_style))

    # ── Skills ────────────────────────────────────────────────────────────
    skills = cv_data.get("skills", {})
    if skills:
        story.append(Paragraph("TECHNICAL SKILLS &amp; LANGUAGES", section_style))
        story.append(HRFlowable(width="100%", thickness=0.4, color=_LINE, spaceAfter=4))
        if skills.get("core_engineering"):
            story.append(Paragraph("Core Engineering:", skills_label_style))
            story.append(Paragraph(", ".join(skills["core_engineering"]), skills_value_style))
        if skills.get("software_tools"):
            story.append(Paragraph("Software Tools:", skills_label_style))
            story.append(Paragraph(", ".join(skills["software_tools"]), skills_value_style))
        if skills.get("languages"):
            story.append(Paragraph("Languages:", skills_label_style))
            story.append(Paragraph(", ".join(skills["languages"]), skills_value_style))

    doc.build(story)
    logger.info("[cv_editor] PDF written: %s", output_path)


def create_tailored_cv(job: object, evaluation: dict, output_dir: Path) -> tuple[Path, str]:
    """
    Full pipeline: generate tailored content → build PDF.
    Returns (pdf_path, tailoring_notes).
    """
    cv_data = generate_tailored_cv_content(
        job_title=job.title,
        company=job.company,
        job_description=job.description,
        evaluation=evaluation,
    )

    _slug = "".join(c for c in NAME.upper() if c.isalnum() or c == " ").strip().replace(" ", "_") or "CANDIDATE"
    pdf_path = output_dir / f"{_slug}_CV.pdf"
    build_cv_pdf(cv_data, pdf_path, job.title, job.company)

    return pdf_path, cv_data.get("tailoring_notes", "")
