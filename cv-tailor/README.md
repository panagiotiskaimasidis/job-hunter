# CV Tailor

A personal CV and cover letter tailoring system powered by Claude. One master CV, zero invented content, one tailored output set per role.

---

## One-Time Setup

### 1. Fill in your master CV
Open `inputs/master-cv.md` and replace every `[...]` placeholder with real information. This file is the single source of truth — the agent reads it but never overwrites it.

Key placeholders to fill:
- GitHub profile URL (if you have one)
- Available start date and notice period
- Driving licence details
- Project details: job-scraping app and EU261 dashboard (tech stack, outcomes)
- P&G internship extras: specific product lines, team size, tools
- EUROAVIA extras: events run, number of members
- Certifications (NEBOSH, Six Sigma, etc.) — or confirm none yet
- Year you earned Michigan Proficiency and DELF B2
- Relevant coursework from your MSc

### 2. Fill in your career goals
Open `inputs/career-goals.md` and replace every `[...]` with your actual preferences:
- Target industries (ranked)
- Salary floor
- What your ideal day-to-day looks like in 1–2 sentences
- Why you want to move to Ireland specifically
- What motivates you in engineering (in your own words)

---

## Per-Application Workflow

### Step 1 — Paste the job ad
Open `inputs/job-description.md`, delete the placeholder text, and paste the **full** job advertisement (responsibilities, requirements, company blurb — everything).

Update the heading: `# Job Description — [Company] — [Role Title]`

### Step 2 — Run the command
In a Claude Code session in this directory, say:

> **Tailor my CV and cover letter for this role**

Claude will read all three input files and produce three output files in `outputs/`:
- `cv-[company]-[role].md`
- `cover-letter-[company]-[role].md`
- `match-analysis-[company]-[role].md`

### Step 3 — Review before sending
1. Read `match-analysis-[company]-[role].md` first — check the honest gaps section
2. Review the CV for any bullet that feels overstated — if it does, cut it
3. Read the cover letter aloud — if any sentence sounds like it could apply to any company, rewrite it
4. Convert to PDF using your preferred tool before submitting (the `.md` files are working drafts)

### Step 4 — Reset for the next role
Overwrite `inputs/job-description.md` with the next job ad. The `outputs/` folder accumulates a record of every application.

---

## Project Structure

```
cv-tailor/
├── CLAUDE.md                          # Agent instructions (do not delete)
├── README.md                          # This file
├── inputs/
│   ├── master-cv.md                   # Your complete background — edit freely, never auto-overwritten
│   ├── career-goals.md                # Your 1/3/10-year direction — edit freely
│   └── job-description.md             # Paste a new job ad here for each application
├── templates/
│   ├── cv-template.md                 # Reference structure (agent uses CLAUDE.md rules, not this template)
│   └── cover-letter-template.md       # Reference structure
└── outputs/
    ├── .gitkeep
    ├── cv-[company]-[role].md         # Generated per application
    ├── cover-letter-[company]-[role].md
    └── match-analysis-[company]-[role].md
```

---

## Rules the Agent Follows

- **Never invents** experience, metrics, dates, or skills not in `master-cv.md`
- **Never overwrites** `master-cv.md`
- Tailoring = selection, emphasis, and honest rephrasing only
- Flags genuine gaps in the match analysis rather than papering over them
- Stops and asks if `[...]` placeholders remain in the inputs before proceeding
