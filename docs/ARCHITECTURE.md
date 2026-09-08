# Architecture

## Overview

Research-Pipeline is a small daily-batch ETL: fetch → score → notify. Each
run is one cron-triggered or manual invocation of `research-pipeline run`.
Everything is single-process, file-backed (SQLite + on-disk PDFs), and
opt-in feature-gated.

```
                 +-------------------+
                 |   cron / manual   |
                 |  (research-pipeline run)  |
                 +---------+---------+
                           |
                           v
                +----------+----------+
                |   runtime/runner    |  orchestrator
                +----+----+-----------+
                     |    |
        +------------+    +-----------+
        |                         |
        v                         v
  +-----+------+         +---------+---------+
  | fetch_arxiv |         |       db (SQLite) |
  +-----+------+         +---------+---------+
        |                         ^
        v                         |
  +-----+------+    PDF + score   |
  | pdf_extract|----------------->|
  +-----+------+                  |
        |                         |
        v                         v
  +-----+------+         +---------+---------+
  |   score    |-------->|       notify       |
  | (LLM)      |         | (Telegram)         |
  +------------+         +-------------------+
                                |
                  +-------------+-------------+
                  |             |             |
                  v             v             v
             feature:       feature:       feature:
             daily_summary  weekly_digest  autobuild
```

## Module Map (`src/research_pipeline/`)

| Module | Purpose |
|---|---|
| `cli.py` | `research-pipeline` Click entry point: `run`, `doctor`, `status`, `logs`, `backfill` |
| `config.py` | Frozen `Config` dataclass; `load_config()` reads `.env` |
| `db.py` | SQLite state (papers, runs, ai_events). Connection setup, schema init, CRUD, run lifecycle, AI event log |
| `fetch_arxiv.py` | arXiv API client. `fetch_recent(lookback_hours)`, `download_pdf(arxiv_id, pdf_url)`. Fixture support via `ARXIV_FIXTURE_PATH` |
| `pdf_extract.py` | pypdf wrapper. `extract_text(pdf_path)`, `extract_first_n_chars(pdf_path, n)` for Stage B |
| `score.py` | Two-stage LLM scoring. `score_abstract(paper, cfg)`, `score_deep(paper, pdf_text, cfg)`. Supports Ollama, OpenAI-compat, and Anthropic-compat providers. |
| `notify.py` | Telegram-only notifier. `send_top_picks`, `send_daily_summary`, `send_raw`. Topic-thread support, fail-open |
| `runtime/runner.py` | Orchestrator wiring fetch → score → notify |
| `daily_summary.py` | Feature-gated daily-summary build + send |
| `weekly_digest.py` | Feature-gated weekly-digest build + send (ISO-week grouping, tag clustering) |
| `narrative_review.py` | LLM-generated German narrative that connects the day's / week's papers |
| `autobuild.py` | Feature-gated post-pick background tasks. `launch_autobuild`, `poll_autobuild_sessions`. Generic — wire your own code-execution backend |
| `code_session.py` | Thin `subprocess.Popen` wrapper used by autobuild |
| `backfill.py` | `research-pipeline backfill {stage-a,stage-b,notify}` — re-score historical papers |
| `install/wizard.py` | Interactive install CLI: Ollama check, model pull, Telegram token validation, feature selection, cron registration |
| `install/{ollama,telegram,cron,doctor}.py` | Helpers for the install wizard |
| `prompts/{abstract,deep}_score.txt` | German-language scoring prompts (see `docs/PROMPTS.md`) |
| `logging_setup.py` | Logger config shared across modules |

## Data Model

Single SQLite database at `DB_PATH` (default `data/state.db`).

```sql
papers(
  arxiv_id PRIMARY KEY,
  title, authors, abstract, categories, pdf_url,
  published_at, fetched_at,
  abs_score, abs_reason, abs_tags,
  deep_score, deep_summary, deep_why, deep_tags, deep_analysis,
  deep_score_updated_at,   -- added by backfill migration
  picked, notified_at,
  pdf_status, pdf_reason
)

runs(id, started_at, finished_at, papers_seen, papers_picked, error)

ai_events(id, ts, source, event_type, arxiv_id, title, summary, metadata)
```

Indexes on `published_at DESC`, `abs_score DESC`, `deep_score DESC`,
`picked`, `ai_events.ts DESC`, `ai_events.source`, `ai_events.arxiv_id`.

## Config

All settings live in `.env` (or environment). See `.env.example` for the
full list with defaults. The `Config` dataclass is the single source of
truth at runtime — modules never read `os.getenv` directly.

Required for live Telegram notification: `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`. Without them the pipeline logs picks to stdout but
sends nothing.

## Failure Behavior

- Ollama down → Stage A/B returns zero score with `reason="api_error"`,
  pipeline continues, picks may be empty that day.
- arXiv 5xx/429 → `arxiv` library retries 3× automatically.
- PDF download fails → Stage B skipped for that paper, log warning.
- Telegram not configured → pipeline logs picks, exit 0.
- `detect-secrets scan` is wired into CI to keep secrets out of the repo.

## Extension Points

- **Custom scoring prompts** — edit `prompts/{abstract,deep}_score.txt`,
  no code changes needed. The prompts expect `title`, `abstract`,
  `pdf_text` template variables.
- **Custom LLM provider** — add a new `_chat_<name>` function in
  `score.py` and a detection branch in `_chat()`.
- **Custom notify channel** — `notify.py` is intentionally minimal; add
  new send functions or wrap with a router. (The public repo does **not**
  bundle a multi-target router by design.)
- **Custom autobuild backend** — `autobuild.launch_autobuild` accepts a
  `command` list (default is a no-op stub). Replace with `["claude", "-p", goal]`,
  `["docker", "run", ...]`, or your own runner.
