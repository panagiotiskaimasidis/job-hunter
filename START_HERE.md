# 👋 Start Here

This app finds jobs for you, scores them, and writes a tailored CV + cover letter
for the good ones. Here's how to get it running. **No coding required.**

---

## What you'll need (all free)

1. A **Groq** account → [console.groq.com](https://console.groq.com) (this is the AI brain)
2. *(Optional)* A **Notion** account for the dashboard → [notion.so](https://notion.so)
3. Your **CV** as a PDF

---

## Setup — 3 simple steps

### Step 1 · Add your CV
Drop your CV PDF into the **`inputs`** folder. That's it.
(Or open `inputs/PUT_YOUR_CV_HERE.txt` and paste your CV as text.)

### Step 2 · Fill in the questionnaire
Open **`inputs/QUESTIONNAIRE.md`** and answer the questions
(your name, the jobs you want, where, and what you're after). Save it.

### Step 3 · Let it set itself up

**The easy way (you have Claude):**
Open Claude in this folder and say:

> **"Set up my job hunter"**

Claude will read your CV and questionnaire, ask you for your free API key,
and get everything ready.

**The manual way (no Claude):**
Open a terminal in this folder and run:

```
pip install -r requirements.txt
python setup.py
```

The wizard asks a few questions and sets everything up.

---

## Using it every day

Once set up, finding jobs is one command (or just ask Claude "find me jobs"):

```
python main.py
```

Go make a coffee. When it finishes, your matches are waiting:
- In the **`applications`** folder (a folder per job, with a tailored CV + cover letter)
- And in your **Notion dashboard** if you connected one

To generate documents for jobs you starred in Notion:

```
python main.py --generate-docs
```

---

## Changing your mind later
Want different job titles, a new CV, or different locations?
Just edit `inputs/QUESTIONNAIRE.md` (or re-run `python setup.py`) and run again.

---

## If something breaks
Tell Claude what happened, or check `job_hunter.log` for the details.
Most issues are a missing API key or an empty questionnaire field.
