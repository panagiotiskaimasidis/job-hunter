# 🎯 Job Hunter

An AI-powered job search & application assistant:
**Scrape → Score → Tailor CV → Write Cover Letter → Log to a dashboard**

> **New here? Read [`START_HERE.md`](START_HERE.md) first** — it's the no-code,
> 3-step setup guide. This README is the technical reference.

---

## What it does

1. **Scrapes** LinkedIn, Indeed, EuroJobs, and company career pages for roles
   matching the candidate's profile.
2. **Scores** every job 1–10 with an AI, evaluating CV fit + career-vision alignment.
3. For jobs scoring ≥ `MIN_MATCH_SCORE` (default 7), it:
   - Creates an `applications/<score>_<company>_<title>/` folder
   - Generates a **tailored CV PDF** reframing real experience for that role
   - Generates a **cover letter PDF** — confident, human, company-specific
   - Creates a **dashboard page** (Notion) with the match analysis and a status tracker

Every personal detail — name, CV, career goals, search terms — comes from the
candidate's profile (`inputs/profile.json`), generated at setup. The code itself
contains no personal data, so it works for anyone.

---

## Setup

**The easy way:** follow [`START_HERE.md`](START_HERE.md) — drop in a CV, fill the
questionnaire, then run `python setup.py` (or ask Claude to "set up my job hunter").

**What setup produces:**
- `.env` — API keys (Groq required; Gemini + Notion optional)
- `inputs/profile.json` — identity, CV text, career vision, search queries

| Key | Where to get it |
|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) (required) |
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (optional backup) |
| `NOTION_API_KEY` | [notion.so/my-integrations](https://www.notion.so/my-integrations) (optional) |
| `NOTION_DATABASE_ID` | run `python setup_notion.py` (optional) |

> **Skip Notion?** Leave the Notion keys blank — the pipeline still writes local
> application folders with CVs and cover letters.

---

## Usage

```bash
python main.py                  # full pipeline — scrape then evaluate
python main.py --scrape-only    # scrape only (no AI evaluation)
python main.py --evaluate-only  # evaluate already-scraped jobs
python main.py --generate-docs  # build CV+letter for jobs flagged in Notion
python main.py --url "<url>"     # process a single job URL
python main.py --query "<text>" # add an extra search query for this run
```

---

## Output structure

```
applications/
  09_Acme_Brand_Manager/
    job.txt              # full job description
    evaluation.json      # AI scoring + full analysis
    <NAME>_CV.pdf         # tailored CV for this role
    <NAME>_COVERLETTER.pdf

data/
  jobs_raw.json          # all scraped postings (cache)
  jobs_processed.json    # all evaluated jobs (dedupe)

job_hunter.log           # full run log
```

---

## Tuning

| Setting (in `.env`) | Default | Effect |
|---|---|---|
| `MIN_MATCH_SCORE` | `7` | Lower to see more matches; raise for stricter filtering |
| `SCRAPE_DELAY_SECONDS` | `2` | Increase if getting rate-limited |
| `MAX_JOBS_PER_BOARD` | `15` | Jobs fetched per search |

To change which **roles/regions** get searched, edit `inputs/QUESTIONNAIRE.md` and
re-run `python setup.py` — or edit `inputs/profile.json` directly.

---

## Important rules

- **No fabrications** — the AI is instructed to only reframe real experience.
- **Deduplication** — jobs already in `jobs_processed.json` are never re-evaluated.
- **Rate limits respected** — minimum `SCRAPE_DELAY_SECONDS` between requests.
- **Privacy** — `.env`, `inputs/profile.json`, and any CV PDF are gitignored.

---

## Troubleshooting

- **App says "not set up yet"** → run `python setup.py`.
- **`KeyError: GROQ_API_KEY`** → your `.env` is missing or the key is blank.
- **LinkedIn returns nothing** → it blocks scrapers aggressively; use `--url` to
  paste job links manually, or rely on the other boards.
- **Notion `401`** → share your database with the integration at notion.so/my-integrations.
- **Anything else** → check `job_hunter.log`, or ask Claude what went wrong.
