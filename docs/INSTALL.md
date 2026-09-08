# Install

A guided, end-to-end walkthrough. If you just want the fast path, the
README's Quickstart is enough — this document covers every knob the
install CLI exposes and what to do when something breaks.

## Prerequisites

- Linux (tested on Debian/Ubuntu)
- Python 3.11 or 3.12
- 8 GB RAM minimum, 16 GB recommended
- Outbound HTTPS to `arxiv.org`, `export.arxiv.org`, and (if you use
  Telegram) `api.telegram.org`
- For Ollama: x86_64 CPU is fine, GPU optional

## Step 1: Clone

```bash
git clone https://github.com/DavidVossebuerger/Research-Pipeline.git
cd Research-Pipeline
```

## Step 2: Virtualenv + editable install

```bash
python3.11 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e ".[dev]"
```

`.[dev]` pulls in `ruff` and `pytest` for local checks. If you only want
the runtime, `pip install -e .` is enough.

## Step 3: Run the install wizard

```bash
.venv/bin/research-pipeline-install install
```

The wizard walks you through 8 steps:

1. **Ollama check** — if `ollama` is not on `$PATH`, prints the install
   command (`curl -fsSL https://ollama.com/install.sh | sh`). Re-run the
   wizard after installing.
2. **Model pull** — defaults to `phi3.5:3.8b`. The wizard runs
   `ollama pull <model>` and waits. Skip if already present.
3. **Telegram bot token** — paste from `@BotFather`. The wizard validates
   by calling `getMe` and showing the bot's username.
4. **Telegram chat ID** — paste your personal chat id (from `@userinfobot`
   or `getUpdates`). The wizard sends a one-line test message and waits
   for confirmation that you saw it.
5. **Features** — multi-select. Defaults: Daily Summary on, the rest off.
   - Daily Summary — end-of-day Markdown stats to Telegram
   - Weekly Digest — Sunday-evening cluster + narrative
   - AutoBuild — spawn per-pick background tasks (you wire the backend)
   - Telegram Bot — interactive `/ask`, `/last`, etc. (legacy from v1;
     currently disabled by default, can be enabled if you implement the
     command handler)
   - Backfill CLI — re-score historical papers (`research-pipeline backfill …`)
6. **Daily run time** — cron entry, default `07:30` local.
7. **`.env` preview** — the wizard shows the diff vs. `.env.example` and
   asks you to confirm before writing.
8. **Cron registration** — `crontab -l` is shown, the new entry is
   appended, and the wizard verifies it landed.

The wizard never deletes your existing crontab entries. It only appends
the `RESEARCH_PIPELINE` block.

## Step 4: Smoke test

```bash
# Dry run: full fetch → score → notify path, but no Telegram send
.venv/bin/research-pipeline run --dry-run
```

Expected output: pipeline summary line, possibly `0 papers seen` if arXiv
returned nothing in the lookback window. Inspect `data/state.db`:

```bash
sqlite3 data/state.db "SELECT arxiv_id, title, abs_score, deep_score FROM papers ORDER BY deep_score DESC NULLS LAST LIMIT 10;"
```

Real run:

```bash
.venv/bin/research-pipeline run
```

Top picks should appear in your Telegram within ~60s.

## Step 5: Diagnostics

```bash
.venv/bin/research-pipeline doctor
```

Reports ✓ / ✗ / ⚠ for each subsystem:
- Ollama reachable + model loaded
- Telegram `getMe` returns 200
- arXiv API reachable (last successful query timestamp)
- Cron entry present
- Threshold hit-rate over last 30 days

If something is ✗, run `research-pipeline-install diagnose` for raw
probe output.

## Manual Cron (skip the wizard)

If you prefer to wire cron yourself:

```bash
# Edit crontab
crontab -e
# Add:
RESEARCH_PIPELINE_HOME=/path/to/Research-Pipeline
30 7 * * * cd $RESEARCH_PIPELINE_HOME && .venv/bin/research-pipeline run >> logs/cron.log 2>&1
```

Make sure the venv is fully-qualified in cron — cron has a stripped
`$PATH`.

## Switching LLM provider

The pipeline supports three LLM backends:

### Ollama (default)

```bash
LLM_PROVIDER=ollama
LLM_MODEL=phi3.5:3.8b
LLM_BASE_URL=http://localhost:11434
LLM_API_KEY=
```

### OpenAI-compatible

Use OpenAI direct, OpenRouter, Together, Groq, or any other OpenAI-compatible endpoint:

```bash
LLM_PROVIDER=openai_compat
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
```

### Anthropic-compatible

Use Anthropic direct, or any provider that speaks the Anthropic Messages API:

```bash
LLM_PROVIDER=anthropic_compat
LLM_MODEL=claude-3-5-sonnet-20241022
LLM_BASE_URL=https://api.anthropic.com
LLM_API_KEY=sk-ant-...
```

The `anthropic_compat` option works with any provider that exposes an
Anthropic-format `/v1/messages` endpoint — useful for proxies, local
deployments, or alternative providers.

## Customizing the scoring prompts

See `docs/PROMPTS.md`. Edit the text files in `prompts/` — no code
change needed. Stage A prompt expects `{title}` and `{abstract}`; Stage B
adds `{pdf_text}`.

## Uninstallation

```bash
.venv/bin/research-pipeline-install uninstall
# removes the cron entry, optionally deletes .env
```

To remove the data directory as well: `rm -rf data/ pdfs/ logs/`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Ollama not reachable` in `doctor` | `ollama serve` not running | `systemctl enable --now ollama` or run manually |
| Stage A returns `parse_error` for every paper | Model too small, doesn't follow JSON format | Switch to `qwen2.5:7b` or larger, or use OpenRouter with `claude-3.5-sonnet` |
| Telegram 400 "can't parse entities" | Markdown in picks breaks parser | `notify.py` retries as plain text automatically; if persistent, edit the formatter |
| `arxiv` 5xx errors | arXiv API hiccup | `arxiv` library retries 3×; if persistent, the install's daily cron will catch up next run |
| Cron doesn't run | Wrong `$PATH` in cron | Use absolute paths in the cron entry, see above |
| Disk full from PDFs | `pdfs/` grows unbounded | Rotate or add a `find pdfs/ -mtime +30 -delete` line in the cron entry |
