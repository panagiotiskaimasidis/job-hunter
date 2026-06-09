"""
Career profile loader — the single source of truth for WHO the app works for.

All personal data lives in `inputs/profile.json`, which is generated during setup
(run `python setup.py`, or ask Claude to set it up for you). This file simply
loads that profile and builds the values the rest of the app imports:

    NAME, HEADLINE, CONTACT_LINE   → used on the generated CV / cover letter
    CV_TEXT                        → the candidate's real CV, in plain text
    CAREER_VISION                  → what kind of roles/seniority they want
    SYSTEM_CONTEXT                 → the full instruction block fed to the AI
    SEARCH_QUERIES, SEARCH_LOCATIONS → what the scraper searches for

If no profile.json exists yet, the app raises a clear, friendly error telling
the user to run setup first — instead of crashing with a confusing traceback.
"""

import json
from pathlib import Path

ROOT = Path(__file__).parent
PROFILE_PATH = ROOT / "inputs" / "profile.json"


class ProfileNotFound(Exception):
    pass


def _load_profile() -> dict:
    if not PROFILE_PATH.exists():
        raise ProfileNotFound(
            "\n\n"
            "─────────────────────────────────────────────────────────────\n"
            "  No profile found yet!\n"
            "─────────────────────────────────────────────────────────────\n"
            "  This app needs to know who it's job-hunting for.\n\n"
            "  To set it up, do ONE of these:\n\n"
            "    • Run:  python setup.py\n"
            "      (a friendly wizard that asks a few questions)\n\n"
            "    • Or open Claude and say: \"Set up my job hunter\"\n"
            "      (after dropping your CV in the inputs/ folder)\n"
            "─────────────────────────────────────────────────────────────\n"
        )
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


_p = _load_profile()

# ── Identity (used on generated documents) ──────────────────────────────────
NAME: str = _p.get("name", "")
HEADLINE: str = _p.get("headline", "")
_contact = _p.get("contact", {})
CONTACT_LINE: str = "  |  ".join(
    str(v) for v in [
        _contact.get("location", ""),
        _contact.get("phone", ""),
        _contact.get("email", ""),
        _contact.get("linkedin", ""),
    ] if v
)

# ── Content fed to the AI ────────────────────────────────────────────────────
CV_TEXT: str = _p.get("cv_text", "")
CAREER_VISION: str = _p.get("career_vision", "")

# ── Scraper targets ──────────────────────────────────────────────────────────
SEARCH_QUERIES: list[str] = _p.get("search_queries", [])
SEARCH_LOCATIONS: list[str] = _p.get("search_locations", ["Europe"])

SYSTEM_CONTEXT = f"""You are an expert career advisor and hiring specialist with 20 years of experience
placing high-potential candidates in elite roles. You know exactly what makes a CV and cover letter
stand out in competitive applicant pools.

You are working exclusively for {NAME or "this candidate"}. Everything you produce must:
1. Be 100% truthful — never invent experience, skills, metrics, or claims not supported by their real CV.
2. Be strategically positioned — emphasise the most relevant real experience using the strongest possible language.
3. Maximise their hiring chances by mirroring job-description language and demonstrating clear fit.
4. Sound human, confident, and direct — never generic, never hollow.

THEIR CV:
{CV_TEXT}

THEIR CAREER VISION:
{CAREER_VISION}
"""
