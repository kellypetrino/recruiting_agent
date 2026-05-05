"""Stage 2: LLM-based relevance scoring via Claude Haiku 4.5.

Scores each job 0-10 against Kelly's target profile. Results are cached in the
DB by job_id — a job is never re-scored.
"""

import json
import re
import structlog
from datetime import datetime

import anthropic

from src.db import Job, SessionLocal

log = structlog.get_logger(__name__)

MODEL = "claude-haiku-4-5-20251001"

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM = """\
You are a recruiting assistant helping Kelly, an HBS MBA candidate (Class of 2026), \
evaluate job postings. She is recruiting for AI-focused Product Manager, GTM, \
and Forward-Deployed / Deployment roles. She wants to start in June or July 2026. \
She strongly prefers New York City; US-remote roles are acceptable. \
She is targeting post-MBA level roles (APM, PM, Senior PM) — not Director, VP, or Head of.

Your job: read a job posting and score its fit for Kelly on a 0–10 scale.

SCORING GUIDE (use these anchors):
  9–10: Near-perfect fit. AI-focused PM or GTM role, NYC or remote, right level, \
        company on her target list, description matches her background.
        Example: "Product Manager, Foundation Models – New York" at Anthropic.
  7–8:  Strong fit. AI-adjacent PM/GTM, right location, right level, \
        but maybe not pure AI or not a top-tier target company.
        Example: "Senior PM, Enterprise" at a well-known SaaS company with clear AI roadmap.
  5–6:  Possible fit. PM role but not AI-focused, or right domain but wrong location, \
        or level is ambiguous.
  3–4:  Weak fit. PM role at a non-AI company, or AI role that's clearly engineering-not-PM.
  1–2:  Poor fit. Mostly irrelevant — sales, ops, or deeply technical roles mislabeled as PM.
  0:    No fit. Completely wrong function, seniority, or geography.

HARD NEGATIVES (always score ≤ 3):
  - Director, VP, Head of, or C-suite titles
  - Roles explicitly requiring 8+ years of experience
  - Non-US or international-only locations
  - Pure engineering roles labeled as "technical PM" but requiring coding
  - Internships or rotational programs

Respond ONLY with a JSON object — no explanation outside the JSON:
{
  "score": <integer 0-10>,
  "rationale": "<one sentence explaining why this fits or doesn't>",
  "flags": "<one sentence on any red flags, or null if none>"
}"""

_USER_TEMPLATE = """\
Company: {company}
Title: {title}
Location: {location}
Remote policy: {remote_policy}

Job description:
{description}"""


# ── Scoring ───────────────────────────────────────────────────────────────────

def _build_prompt(job: Job) -> str:
    description = (job.description_raw or "")[:4000]  # Haiku context is ample; cap for cost
    if not description:
        description = "(No description available — score based on title and location only)"
    return _USER_TEMPLATE.format(
        company=job.company,
        title=job.title,
        location=job.location,
        remote_policy=job.remote_policy,
        description=description,
    )


def _parse_response(text: str) -> dict:
    """Extract JSON from the model response, tolerating minor formatting issues."""
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object in the text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def score_job(job: Job, client: anthropic.Anthropic) -> dict:
    """Score a single job. Returns parsed dict with score/rationale/flags."""
    prompt = _build_prompt(job)
    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text
    return _parse_response(raw)


def run_scoring(min_score_threshold: float = 0.0, dry_run: bool = False) -> dict:
    """Score all jobs that passed Stage 1 filter but haven't been scored yet.

    Returns summary stats.
    """
    client = anthropic.Anthropic()
    stats = {"scored": 0, "skipped_cached": 0, "errors": 0, "total_passed_filter": 0}

    with SessionLocal() as session:
        jobs = (
            session.query(Job)
            .filter(Job.passed_prefilter == 1, Job.scored_at == None)  # noqa: E711
            .all()
        )
        stats["total_passed_filter"] = len(jobs)
        log.info("score.start", jobs_to_score=len(jobs))

        for job in jobs:
            try:
                result = score_job(job, client)
                score = result.get("score", 0)
                if not dry_run:
                    job.score = float(score)
                    job.score_rationale = result.get("rationale")
                    job.score_flags = result.get("flags")
                    job.scored_at = datetime.utcnow()
                    session.add(job)
                    session.commit()
                stats["scored"] += 1
                log.info(
                    "score.job",
                    company=job.company,
                    title=job.title[:50],
                    score=score,
                    rationale=result.get("rationale", "")[:80],
                )
            except Exception:
                log.exception("score.error", job_id=job.job_id, title=job.title[:50])
                stats["errors"] += 1

    return stats
