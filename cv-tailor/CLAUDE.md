# CV Tailor — Agent Instructions

## WHO YOU ARE TAILORING FOR

Panagiotis Kaimasidis — MSc Mechanical & Aeronautical Engineer (8.36/10, University of Patras, 2025). Early-career but unusually broad: FMCG process engineering at P&G Brussels (computer vision QC, 400% capacity expansion, cross-site with Crailsheim Swiffer plant), propulsion maintenance at the Hellenic Air Force, HSE leadership on Greece's first LEED-certified public facility, and international business development at EUROAVIA (€65,000 raised across Europe in under a year). Multilingual: Greek (native), English (Michigan Proficiency), French (DELF B2). EU citizen — no visa needed for Ireland or any EU country.

His north star: environments where he is never the most experienced person in the room, problems that are genuinely hard, trajectory toward global-scale engineering and commercial leadership. Industry-agnostic. He calls it the "Ironman feeling at work."

---

## TRIGGER 1 — Manual tailoring

**Command:** "Tailor my CV and cover letter for this role"

Read `inputs/job-description.md` for the job ad, then run the full workflow (Steps 1–6 below).

---

## TRIGGER 2 — Notion tailoring

**Command:** "Generate CV from Notion"

### Step N1 — Fetch pending jobs from Notion
Use the Notion MCP tool to query the database "🎯 Job Matches — Panagiotis" (id: `37959fcf-eadd-8112-8a19-d71f5d839922`) for all rows where `Generate Docs = "Yes"`.

For each pending job, extract: Job Title, Company, Location, Application Link.

### Step N2 — Get the job description
Search for the job description using this priority order:
1. Look in `../applications/` for a folder matching `*[Company]*[Title]*` and read `job.txt` from it
2. If not found, scan all `../applications/*/job.txt` files for one containing the Application Link URL
3. If still not found, attempt to fetch the Application Link URL directly

### Step N3 — Run the full tailoring workflow (Steps 1–6 below) for each job
Use the fetched job description as the input instead of `inputs/job-description.md`.
Output files go to `outputs/` as normal: `cv-[company]-[role].md`, `cover-letter-[company]-[role].md`, `match-analysis-[company]-[role].md`.

### Step N4 — Update Notion
After generating each set of documents:
- Set `Generate Docs` → `"Done"` on the Notion page
- Append to `Comments`: `"CV Tailor outputs saved to cv-tailor/outputs/ — [date]"`

Process all pending jobs before stopping.

---

## FULL WORKFLOW (Steps 1–6)

### Step 1 — Read all inputs
- `inputs/master-cv.md` — single source of truth. Read-only. Never modify.
- `inputs/career-goals.md` — 10-year direction; use to frame "why this role" authentically
- Job description — from `inputs/job-description.md` (Trigger 1) or fetched from Notion/local files (Trigger 2)

### Step 2 — Analyse the job ad
- Separate **must-haves** from **nice-to-haves**
- Extract the **10–15 key ATS keywords** (exact phrasing from the JD)
- Note seniority level, tone, and culture signals
- Note what "success in year 1" looks like for this role

### Step 3 — Positioning decision
Panagiotis has three angles — choose the right one and lead with it:
- **Process / manufacturing roles** → lead with P&G (400% capacity expansion, computer vision QC, cross-site Crailsheim collaboration)
- **Project / cross-functional roles** → lead with EUROAVIA international scope + P&G project delivery
- **Technical / R&D adjacent roles** → lead with thesis (Wire DED additive manufacturing simulation) + Air Force propulsion work

### Step 4 — Map requirements to evidence
For every must-have: find the evidence in `master-cv.md` or declare a gap. No papering over.

### Step 5 — Write `outputs/cv-[company]-[role].md`
- Rewritten summary: 3–4 sentences, specific to this role and company, mirrors 2–3 JD keywords
- Sections reordered by relevance using the positioning decision from Step 3
- Every bullet quantified where a number exists in master-cv.md
- ATS-safe: no tables, columns, graphics, or text boxes
- 1 page target; 2 pages maximum

### Step 6 — Write `outputs/cover-letter-[company]-[role].md`
250–350 words. Four beats:
1. **Hook** — specific to this company/role. Never "I am writing to apply for…"
2. **Evidence** — 2–3 achievements from master-cv.md that hit the JD's must-haves. Narrative, not bullets. Numbers where they exist.
3. **Why this role fits my goals** — draw from career-goals.md. Translate his north star into language appropriate for this company. The "Ironman feeling" should come through without using that phrase. Specific: why this company, this role, this moment.
4. **Confident close** — one sentence. No hedging.

### Step 7 — Write `outputs/match-analysis-[company]-[role].md`
- **ATS Keywords:** keyword | Present / Partial / Missing
- **Requirements matrix:** requirement | evidence from master-cv.md | Strong / Partial / Gap
- **Genuine gaps:** one honest sentence per gap on how to close it
- **Trajectory check:** does this role actually serve his goals? Will it keep him challenged, give cross-functional exposure, open doors toward global-scale work?
- **Overall read:** 3–5 sentences — realistic probability past screening, what will land hardest, what the interviewer will probe

---

## HARD RULES — Never Break These

1. **Never invent** experience, dates, titles, metrics, or skills not in `inputs/master-cv.md`
2. **Never overwrite** `inputs/master-cv.md` — it is read-only
3. Tailoring = **selection, emphasis, honest rephrasing** of real material only
4. If a must-have has zero evidence, say so in the match analysis — do not compensate with vague language
5. The cover letter must sound like a specific human who wants this specific role — not a template with names swapped in
6. If `inputs/master-cv.md` or `inputs/career-goals.md` still contain `[...]` placeholders, stop and ask before proceeding

---

## Notion Database Reference
- **Database:** 🎯 Job Matches — Panagiotis
- **ID:** `37959fcf-eadd-8112-8a19-d71f5d839922`
- **Trigger field:** `Generate Docs` — values: `No` / `Yes` / `Done`
- **Local JD cache:** `../applications/[score]_[Company]_[Title]/job.txt`
