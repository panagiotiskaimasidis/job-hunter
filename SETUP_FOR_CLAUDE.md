# Instructions for Claude — Setting Up This Job Hunter

A user has asked you to "set up my job hunter". Follow these steps. Be warm and
non-technical; the user may not know what an API key or JSON is.

## Goal
Produce two files:
- `.env` — their API keys
- `inputs/profile.json` — their identity, CV text, career vision, and search targets

Once both exist, the app runs. Nothing else is required.

## Steps

1. **Install dependencies** (if not already):
   `pip install -r requirements.txt`

2. **Find their CV.** Look in `inputs/` for a `.pdf`. If found, extract the text
   (use pypdf). If none, read `inputs/PUT_YOUR_CV_HERE.txt` for pasted text.
   If neither has real content, ask them to drop their CV in `inputs/`.

3. **Read their answers** from `inputs/QUESTIONNAIRE.md`. If fields are blank,
   ask the user for them conversationally — one or two questions at a time, not a wall.

4. **Get API keys.** Ask for their Groq key (required; free at console.groq.com).
   Ask if they want Gemini (backup) and Notion (dashboard) — both optional.
   Write them to `.env` using `.env.example` as the template.

5. **Write `inputs/profile.json`** with this exact shape:
   ```json
   {
     "name": "...",
     "headline": "...",
     "contact": {"location": "...", "phone": "...", "email": "...", "linkedin": "..."},
     "cv_text": "<full plain-text CV>",
     "career_vision": "<a rich paragraph: industries, company type, scope, growth, what to avoid>",
     "search_queries": ["title 1", "title 2", "..."],
     "search_locations": ["Europe", "Remote", "..."]
   }
   ```
   Make `career_vision` detailed — it drives every score and every tailored document.
   Fold their "seniority" and "avoid" answers into it.

6. **Confirm** by running a quick import check:
   `python -c "import career_profile as c; print(c.NAME, '|', len(c.SEARCH_QUERIES), 'queries')"`
   If it prints their name and query count, setup worked.

7. **Tell them they're done** and that they can now run `python main.py`
   (or just ask you to "find me jobs").

## Notes
- Never invent CV content. If the CV text is thin, tell them — don't pad it.
- `inputs/profile.json` and `.env` are gitignored; reassure them their data stays private.
