# recruiting-agent

A personal daily job-scraping pipeline for AI PM / GTM / Deployment roles. Pulls from Greenhouse, Lever, and Ashby APIs, filters by title/location/age, scores with Claude Haiku, and delivers a ranked email digest every morning.

## How it works

1. **Ingest** — pulls open jobs from configured ATS boards (no auth required)
2. **Filter** — drops irrelevant roles by title keyword, location, and posting age
3. **Score** — Claude Haiku 4.5 scores each remaining job 0–10 against the target profile
4. **Digest** — sends a ranked HTML email via Resend at 7am ET daily

## Setup

```bash
conda activate recruiting-agent
pip install -e ".[dev]"
cp .env.example .env
# fill in ANTHROPIC_API_KEY and RESEND_API_KEY in .env
```

## Usage

```bash
# Run the full pipeline manually
python -m src.cli ingest
python -m src.cli filter
python -m src.cli score
python -m src.cli digest --preview   # preview email in terminal
python -m src.cli digest             # send it

# Inspect data
python -m src.cli dump --scored      # scored jobs, sorted by score
python -m src.cli dump --passed      # all jobs that passed Stage 1 filter

# Dashboard
streamlit run dashboard/app.py
```

## Automation

Runs daily at 7am ET via GitHub Actions. Requires two repository secrets:
- `ANTHROPIC_API_KEY`
- `RESEND_API_KEY`

Set these in: Settings → Secrets and variables → Actions

## Target companies

Configured in [config/target_companies.yaml](config/target_companies.yaml). Currently tracking Anthropic, Figma, Scale AI, and Mistral via their public ATS APIs. Google, Meta, OpenAI, and Cursor are listed but use custom job systems — add them manually or via email alerts.

## Stack

Python 3.11 · httpx · SQLite + SQLAlchemy · Claude Haiku 4.5 · Resend · Streamlit · GitHub Actions
