"""
One-time Notion setup script.

Run this ONCE to create the Jobs database in your Notion workspace.
It will print the database ID — copy it into your .env file.

Usage:
  python setup_notion.py
"""

import httpx
import os
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("NOTION_API_KEY", "")
if not API_KEY:
    print("ERROR: Set NOTION_API_KEY in your .env file first.")
    exit(1)

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

def get_root_page() -> str | None:
    """Find a page to create the database under (uses first accessible page)."""
    resp = httpx.post(
        "https://api.notion.com/v1/search",
        json={"filter": {"property": "object", "value": "page"}, "page_size": 5},
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if results:
        return results[0]["id"]
    return None


def create_jobs_database(parent_page_id: str) -> dict:
    """Create the Job Matches database with all required properties."""
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": "🎯 Job Matches"}}],
        "properties": {
            "Job Title":        {"title": {}},
            "Company":          {"rich_text": {}},
            "Location":         {"rich_text": {}},
            "Salary":           {"rich_text": {}},
            "Match Score":      {"number": {"format": "number"}},
            "Verdict": {
                "select": {
                    "options": [
                        {"name": "STRONG_MATCH",  "color": "green"},
                        {"name": "GOOD_MATCH",    "color": "blue"},
                        {"name": "PARTIAL_MATCH", "color": "yellow"},
                        {"name": "WEAK_MATCH",    "color": "orange"},
                        {"name": "NO_MATCH",      "color": "red"},
                        {"name": "ERROR",         "color": "gray"},
                    ]
                }
            },
            "Status": {
                "select": {
                    "options": [
                        {"name": "To Apply",   "color": "blue"},
                        {"name": "Applied",    "color": "yellow"},
                        {"name": "Interview",  "color": "green"},
                        {"name": "Offer",      "color": "purple"},
                        {"name": "Rejected",   "color": "red"},
                        {"name": "Withdrawn",  "color": "gray"},
                    ]
                }
            },
            "Source": {
                "select": {
                    "options": [
                        {"name": "linkedin",  "color": "blue"},
                        {"name": "indeed",    "color": "purple"},
                        {"name": "eurojobs",  "color": "orange"},
                        {"name": "manual",    "color": "gray"},
                    ]
                }
            },
            "Application Link": {"url": {}},
            "Date Found":       {"date": {}},
        },
    }

    resp = httpx.post(
        "https://api.notion.com/v1/databases",
        json=payload,
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    print("🔍 Finding a Notion page to host the database...")
    parent_id = get_root_page()
    if not parent_id:
        print("ERROR: No accessible pages found. Create a page in Notion first,")
        print("       then share it with your integration.")
        exit(1)

    print(f"   Using parent page: {parent_id}")
    print("📦 Creating Jobs database...")

    db = create_jobs_database(parent_id)
    db_id = db["id"]
    db_url = db.get("url", "")

    print()
    print("=" * 60)
    print("✅ Database created successfully!")
    print(f"   URL: {db_url}")
    print()
    print("👉 Add this to your .env file:")
    print(f"   NOTION_DATABASE_ID={db_id}")
    print("=" * 60)


if __name__ == "__main__":
    main()
