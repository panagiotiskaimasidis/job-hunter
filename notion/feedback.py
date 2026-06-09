"""
Notion feedback reader — improves search queries and skip filters over time.

Reads your Job Matches database and looks for signals:
  - Status = "Rejected"    → title keywords to add to the skip list
  - Status = "Interview"   → query patterns that are working well (boost them)
  - Comments field         → free-text notes you've left on job pages

Outputs a feedback_cache.json with learned improvements, and patches
config.SEARCH_QUERIES + main.py's _SKIP_TITLE_KEYWORDS at runtime.
"""

import json
import logging
import re
from collections import Counter
from pathlib import Path

import httpx

import config

logger = logging.getLogger(__name__)

_API = "https://api.notion.com/v1"
_VERSION = "2022-06-28"
_CACHE = config.DATA_DIR / "feedback_cache.json"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.NOTION_API_KEY}",
        "Notion-Version": _VERSION,
        "Content-Type": "application/json",
    }


def _query_database(filter_payload: dict) -> list[dict]:
    pages = []
    cursor = None
    with httpx.Client(timeout=15) as client:
        while True:
            body = {**filter_payload, "page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            resp = client.post(
                f"{_API}/databases/{config.NOTION_DATABASE_ID}/query",
                json=body,
                headers=_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            pages.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
    return pages


def _get_prop_text(props: dict, key: str) -> str:
    prop = props.get(key, {})
    ptype = prop.get("type", "")
    if ptype == "title":
        items = prop.get("title", [])
    elif ptype == "rich_text":
        items = prop.get("rich_text", [])
    else:
        return ""
    return "".join(i.get("text", {}).get("content", "") for i in items)


def _get_select(props: dict, key: str) -> str:
    sel = props.get(key, {}).get("select") or {}
    return sel.get("name", "")


def read_feedback() -> dict:
    """
    Fetch all job pages from Notion and extract learning signals.

    Returns:
      {
        "skip_keywords":    [str],   # new title keywords to skip
        "boost_queries":    [str],   # queries that led to interviews
        "avoid_companies":  [str],   # companies that rejected without interview
        "comments":         [str],   # raw free-text notes from user
        "stats": {...}
      }
    """
    if not config.NOTION_API_KEY or not config.NOTION_DATABASE_ID:
        logger.warning("[feedback] Notion not configured — skipping feedback read.")
        return {}

    try:
        all_pages = _query_database({})
    except Exception as exc:
        logger.error("[feedback] Failed to query Notion: %s", exc)
        return {}

    rejected_titles: list[str] = []
    interview_titles: list[str] = []
    avoid_companies: list[str] = []
    comments: list[str] = []

    for page in all_pages:
        props = page.get("properties", {})
        status  = _get_select(props, "Status")
        title   = _get_prop_text(props, "Job Title").lstrip("🔥✅🟡🔴 ").strip()
        company = _get_prop_text(props, "Company").strip()
        comment = _get_prop_text(props, "Comments").strip()
        score   = props.get("Match Score", {}).get("number", 0) or 0

        if comment:
            comments.append(f"{title} @ {company}: {comment}")

        if status == "Rejected":
            rejected_titles.append(title.lower())
            if score < 7:
                avoid_companies.append(company.lower())

        elif status in ("Interview", "Offer"):
            interview_titles.append(title.lower())

    # Extract recurring title words from rejections (2+ occurrences)
    rejected_words = Counter()
    for t in rejected_titles:
        for word in re.findall(r'\b[a-z]{4,}\b', t):
            if word not in {"engineer", "senior", "lead", "junior", "the", "and", "for"}:
                rejected_words[word] += 1

    skip_keywords = [w for w, count in rejected_words.items() if count >= 2]

    # Extract query patterns from interview-winning titles
    boost_queries = list({
        t for t in interview_titles
        if any(kw in t for kw in ["process", "operations", "program", "manufacturing"])
    })[:5]

    result = {
        "skip_keywords":   skip_keywords,
        "boost_queries":   boost_queries,
        "avoid_companies": list(set(avoid_companies))[:20],
        "comments":        comments[:50],
        "stats": {
            "total_pages":   len(all_pages),
            "rejected":      len(rejected_titles),
            "interviews":    len(interview_titles),
            "with_comments": len(comments),
        }
    }

    # Cache for use by the pipeline
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    logger.info(
        "[feedback] Read %d pages — %d rejected, %d interviews, %d new skip keywords",
        len(all_pages), len(rejected_titles), len(interview_titles), len(skip_keywords)
    )
    if comments:
        logger.info("[feedback] User notes found:")
        for c in comments[:5]:
            logger.info("  • %s", c)

    return result


def apply_feedback_to_run(skip_keywords_set: set, search_queries: list) -> tuple[set, list]:
    """
    Load cached feedback and apply it to the current run's filters.
    Returns updated (skip_keywords_set, search_queries).
    """
    if not _CACHE.exists():
        return skip_keywords_set, search_queries

    try:
        data = json.loads(_CACHE.read_text())
    except Exception:
        return skip_keywords_set, search_queries

    # Add learned skip keywords
    new_skips = set(data.get("skip_keywords", []))
    if new_skips:
        logger.info("[feedback] Applying %d learned skip keywords: %s",
                    len(new_skips), ", ".join(sorted(new_skips)))
        skip_keywords_set = skip_keywords_set | new_skips

    # Surface boost queries that aren't already in the list
    for q in data.get("boost_queries", []):
        if q and not any(q.lower() in existing.lower() for existing in search_queries):
            logger.info("[feedback] Adding boosted query from interviews: '%s'", q)
            search_queries = search_queries + [q.title()]

    return skip_keywords_set, search_queries
