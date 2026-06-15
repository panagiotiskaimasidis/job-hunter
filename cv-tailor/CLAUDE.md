# CV Tailor — Agent Instructions

## Trigger Command
When the user says **"Tailor my CV and cover letter for this role"**, execute the full workflow below.

---

## Workflow

### Step 1 — Read all inputs
- `inputs/master-cv.md` — single source of truth for all experience, skills, and facts
- `inputs/career-goals.md` — 10-year direction; use to frame "why this role" authentically
- `inputs/job-description.md` — the target role; extract company name and role title for output filenames

### Step 2 — Analyse the job ad
- Separate **must-haves** (required, eliminates without) from **nice-to-haves** (preferred, additive)
- Extract the **10–15 key ATS keywords** (exact phrasing from the JD where possible)
- Note the tone, seniority level, and any culture signals

### Step 3 — Map requirements to evidence
- For each must-have and nice-to-have, identify the matching bullet/project/skill in master-cv.md
- Flag genuine gaps (requirements with zero evidence in the master CV) — be honest

### Step 4 — Write `outputs/cv-[company]-[role].md`
- Reorder sections and bullets to lead with the most relevant experience for this role
- Rewrite the professional summary specifically for this role and company
- Mirror JD keywords truthfully — only where the underlying experience actually exists
- Quantify every bullet that can be quantified (use numbers already in the master CV)
- ATS-safe format: no tables, no columns, no graphics, no headers/footers
- Target **1 page**; 2 pages maximum for roles explicitly requiring extensive experience
- Use filename format: `cv-[company]-[role].md` (lowercase, hyphens, no spaces)

### Step 5 — Write `outputs/cover-letter-[company]-[role].md`
- Length: **250–350 words** (hard limit)
- Structure:
  1. **Hook** — specific, non-generic opening that shows you know the company/role
  2. **Evidence** — 2–3 concrete achievements from the master CV that directly match the JD
  3. **Why this role fits my goals** — draw from career-goals.md, be genuine and specific
  4. **Confident close** — clear call to action, no grovelling
- Zero clichés: no "I am a highly motivated…", "I believe I would be a great fit…", "Please find attached…"
- Use filename format: `cover-letter-[company]-[role].md`

### Step 6 — Write `outputs/match-analysis-[company]-[role].md`
Format as a structured report:

**Section A — ATS Keywords**
List the 10–15 keywords and whether each is: Present in CV / Partially Present / Missing

**Section B — Requirements Matrix**

| Requirement | Evidence in Master CV | Strength |
|---|---|---|
| [requirement] | [specific bullet or project] | Strong / Partial / Gap |

**Section C — Genuine Gaps**
For each Gap: one honest sentence on what it would take to close it (course, project, certification, reframe).

**Section D — Overall Fit Assessment**
A 3–5 sentence honest read: probability this application gets past screening, what will resonate most, what the interviewer will probe.

---

## HARD RULES — Never Break These

1. **Never invent** experience, dates, titles, metrics, or skills not present in `inputs/master-cv.md`
2. **Never overwrite** `inputs/master-cv.md` — it is read-only
3. **Never output** more than one set of files per role run
4. Tailoring = **selection, emphasis, and honest rephrasing** of real material only
5. If a must-have requirement has zero evidence in the master CV, say so in the match analysis — do not paper over it with vague language
6. If `inputs/master-cv.md` or `inputs/career-goals.md` still contain `[...]` placeholders, **stop and tell the user** which placeholders need filling before proceeding
