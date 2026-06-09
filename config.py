"""Central configuration — all tunables live here, never scattered in modules."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
CV_BASE = ROOT / "cv" / "base_cv.pdf"
CV_TAILORED_DIR = ROOT / "cv" / "tailored"
COVER_LETTERS_DIR = ROOT / "cover_letters"
APPLICATIONS_DIR = ROOT / "applications"
DATA_DIR = ROOT / "data"
JOBS_RAW = DATA_DIR / "jobs_raw.json"
JOBS_PROCESSED = DATA_DIR / "jobs_processed.json"

# ── API keys ───────────────────────────────────────────────────────────────
GROQ_API_KEY: str = os.environ["GROQ_API_KEY"]
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
NOTION_API_KEY: str = os.getenv("NOTION_API_KEY", "")
NOTION_DATABASE_ID: str = os.getenv("NOTION_DATABASE_ID", "")

# ── Models ─────────────────────────────────────────────────────────────────
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# ── Pipeline settings ──────────────────────────────────────────────────────
MIN_MATCH_SCORE: int = int(os.getenv("MIN_MATCH_SCORE", "7"))
SCRAPE_DELAY_SECONDS: float = float(os.getenv("SCRAPE_DELAY_SECONDS", "1"))
MAX_JOBS_PER_BOARD: int = int(os.getenv("MAX_JOBS_PER_BOARD", "15"))
SCRAPE_WORKERS: int = int(os.getenv("SCRAPE_WORKERS", "4"))   # parallel job fetches

# ── LinkedIn (optional auth) ───────────────────────────────────────────────
LINKEDIN_EMAIL: str = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD: str = os.getenv("LINKEDIN_PASSWORD", "")

# ── Job search queries — tuned to Panagiotis's profile and 10-year vision ──
SEARCH_QUERIES = [
    "Graduate Process Engineer",
    "Manufacturing Engineer graduate",
    "Operations Excellence Engineer",
    "Technical Program Manager graduate",
    "Process Improvement Engineer",
    "Aerospace Engineer graduate",
    "Production Engineer FMCG",
    "Supply Chain Engineer graduate",
    "Reliability Engineer graduate",
]

SEARCH_LOCATIONS = [
    "Europe",
]
