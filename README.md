# 🎯 Job Hunter — Panagiotis Kaimasidis

Automated job application pipeline:
**Scrape → Score → Tailor CV → Write Cover Letter → Log to Notion**

---

## What it does

1. **Scrapes** LinkedIn, Indeed, and EuroJobs for engineering/ops roles matching your profile
2. **Scores** every job 1–10 using Claude, evaluating CV fit + career vision alignment
3. For jobs scoring ≥ 7 (`MIN_MATCH_SCORE`), it:
   - Creates an `applications/<score>_<company>/` folder
   - Generates a **tailored CV PDF** reframing your real experience for that specific role
   - Generates a **cover letter PDF** — confident, human, company-specific, ~350 words
   - Creates a **Notion page** with match analysis, career path potential, and a status tracker

---

## Setup (5 minutes)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure secrets
```bash
cp .env.example .env
```
Edit `.env` and fill in:

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys |
| `NOTION_API_KEY` | [notion.so/my-integrations](https://www.notion.so/my-integrations) → New integration |
| `NOTION_DATABASE_ID` | Run `python setup_notion.py` (see step 3) |

### 3. Create your Notion database (one-time)
```bash
python setup_notion.py
```
Copy the printed `NOTION_DATABASE_ID` into your `.env`.

> **Skip Notion?** Leave `NOTION_API_KEY` and `NOTION_DATABASE_ID` blank —
> the pipeline still creates local application folders with CVs and cover letters.

---

## Usage

```bash
# Full pipeline — scrape all boards then evaluate
python main.py

# Scrape only (no AI evaluation)
python main.py --scrape-only

# Evaluate already-scraped jobs (no scraping)
python main.py --evaluate-only

# Process a single job URL (paste from browser)
python main.py --url "https://www.linkedin.com/jobs/view/..."

# Add an extra search query to this run
python main.py --query "Digital Manufacturing Engineer"
```

---

## Output structure

```
applications/
  09_Siemens_Energy_Process_Engineer/
    job_description.txt          # full JD saved for reference
    evaluation.json              # Claude's scoring + full analysis
    CV_Siemens_Energy_...pdf     # tailored CV for this role
    CoverLetter_Siemens_...pdf   # tailored cover letter

data/
  jobs_raw.json                  # all scraped postings (cache)
  jobs_processed.json            # all evaluated jobs with scores

job_hunter.log                   # full run log
```

---

## Tuning

All settings live in `.env` / `config.py`:

| Setting | Default | Effect |
|---|---|---|
| `MIN_MATCH_SCORE` | `7` | Lower to see more matches; raise for stricter filtering |
| `SCRAPE_DELAY_SECONDS` | `3` | Increase if getting rate-limited |
| `MAX_JOBS_PER_BOARD` | `30` | Jobs fetched per query/location combo |
| `CLAUDE_MODEL` | `claude-sonnet-4-5-20251022` | Swap model if needed |

Edit `config.py` → `SEARCH_QUERIES` and `SEARCH_LOCATIONS` to tune which roles and regions get scraped.

---

## Important rules

- **`cv/base_cv.pdf` is sacred** — never overwritten. All tailored versions go to `applications/`.
- **No fabrications** — Claude is explicitly instructed to only reframe real experience. Every claim in the tailored CV and cover letter is grounded in your actual CV.
- **Deduplication** — jobs already in `jobs_processed.json` are never re-evaluated.
- **Rate limits respected** — minimum `SCRAPE_DELAY_SECONDS` between requests.

---

## Notion database columns

| Column | Type | Notes |
|---|---|---|
| Job Title | Title | Includes score emoji (🔥✅🟡) |
| Company | Text | |
| Location | Text | |
| Match Score | Number | 1–10 |
| Verdict | Select | STRONG_MATCH / GOOD_MATCH / etc. |
| Status | Select | To Apply → Applied → Interview → Offer |
| Application Link | URL | Direct link to apply |
| Source | Select | linkedin / indeed / eurojobs / manual |
| Date Found | Date | |

Each page body contains: match summary, why it fits, career path potential, honest gaps, matched skills, CV tailoring notes.

---

## Troubleshooting

**LinkedIn returns no results** — LinkedIn aggressively blocks scrapers. Try:
- Setting `LINKEDIN_EMAIL` + `LINKEDIN_PASSWORD` in `.env`
- Using `--url` flag to manually paste job URLs instead

**`KeyError: ANTHROPIC_API_KEY`** — your `.env` file is missing or the key is blank

**Notion `401 Unauthorized`** — share your Notion page/database with the integration at notion.so/my-integrations

**PDF looks wrong** — delete the `applications/` folder and re-run; a corrupt run can leave partial files
