"""
Gemini-powered cover letter generator.

Produces a professional, human-sounding letter tailored to the specific role.
Max ~380 words. Grounded entirely in real experience — no fabrications.
"""

import logging
import re
from pathlib import Path
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

import config
from career_profile import SYSTEM_CONTEXT
from matcher.ai_client import generate as _ai_generate

logger = logging.getLogger(__name__)


def _generate(prompt: str) -> str:
    """Generate via shared AI client (Groq → Gemini failover)."""
    return _ai_generate(prompt, system=SYSTEM_CONTEXT, max_tokens=800)

_DARK = colors.HexColor("#1a1a2e")
_MID = colors.HexColor("#444444")
_LIGHT = colors.HexColor("#888888")


def generate_cover_letter_text(job_title: str, company: str, job_description: str,
                                 evaluation: dict) -> str:
    """Ask Claude to write the cover letter. Returns plain text."""
    why_fits = evaluation.get("why_it_fits", "")
    vision = evaluation.get("career_vision_alignment", "")
    matched = evaluation.get("matched_skills", [])

    prompt = f"""
Write a professional cover letter for Panagiotis Kaimasidis applying to:

ROLE: {job_title}
COMPANY: {company}
KEY MATCHED SKILLS: {', '.join(matched)}
WHY HE FITS: {why_fits}
CAREER VISION ALIGNMENT: {vision}

JOB DESCRIPTION:
{job_description[:1000]}

REQUIREMENTS:
- Maximum 380 words, minimum 280 words.
- 4 paragraphs: (1) hook + why this company/role, (2) most relevant experience with specifics,
  (3) second proof point + what you bring that others won't, (4) call to action.
- Tone: confident, direct, human — not a template. Sound like a sharp engineer who knows his worth.
- Reference the company by name at least twice. Mirror 2-3 key phrases from the JD.
- Ground every claim in his real CV — no inventions.
- Do NOT include address blocks, date, or "Dear Hiring Manager" header — just the body paragraphs.
- End with a specific, confident CTA — not generic "I look forward to hearing from you."

Return ONLY the letter text, no markdown, no commentary.
"""

    return _generate(prompt).strip()


def build_cover_letter_pdf(letter_text: str, output_path: Path,
                            job_title: str, company: str) -> None:
    """Render the cover letter as a clean, professional PDF."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=25*mm,
        rightMargin=25*mm,
        topMargin=20*mm,
        bottomMargin=20*mm,
    )

    header_style = ParagraphStyle("CLHeader", fontSize=11, leading=14, textColor=_DARK,
                                   fontName="Helvetica-Bold", spaceAfter=2)
    sub_style = ParagraphStyle("CLSub", fontSize=9, leading=12, textColor=_LIGHT,
                                fontName="Helvetica", spaceAfter=12)
    date_style = ParagraphStyle("CLDate", fontSize=9, leading=12, textColor=_LIGHT,
                                 fontName="Helvetica", spaceAfter=16)
    body_style = ParagraphStyle("CLBody", fontSize=10, leading=15, textColor=_MID,
                                 fontName="Helvetica", spaceAfter=10)
    sign_style = ParagraphStyle("CLSign", fontSize=10, leading=14, textColor=_DARK,
                                 fontName="Helvetica-Bold", spaceBefore=16)

    story = []

    # Letterhead
    story.append(Paragraph("PANAGIOTIS KAIMASIDIS", header_style))
    story.append(Paragraph(
        "panagiotiskaimasidis@gmail.com · +30 6980423845 · linkedin.com/in/PKaimasidis",
        sub_style
    ))
    story.append(Paragraph(datetime.now().strftime("%B %d, %Y"), date_style))
    story.append(Paragraph(f"Re: {job_title} — {company}", sub_style))
    story.append(Spacer(1, 6*mm))

    # Body paragraphs
    for para in letter_text.split("\n\n"):
        para = para.strip()
        if para:
            story.append(Paragraph(para.replace("\n", " "), body_style))

    story.append(Paragraph("Sincerely,", sign_style))
    story.append(Paragraph("Panagiotis Kaimasidis", sign_style))

    doc.build(story)
    logger.info("[cover_letter] PDF written: %s", output_path)


def create_cover_letter(job: object, evaluation: dict, output_dir: Path) -> Path:
    """Full pipeline: generate text → build PDF. Returns pdf_path."""
    text = generate_cover_letter_text(
        job_title=job.title,
        company=job.company,
        job_description=job.description,
        evaluation=evaluation,
    )

    pdf_path = output_dir / "KAIMASIDIS_PANAGIOTIS_COVERLETTER.pdf"
    build_cover_letter_pdf(text, pdf_path, job.title, job.company)

    return pdf_path
