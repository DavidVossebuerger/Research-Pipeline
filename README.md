# Research-Pipeline

Automated daily pipeline that fetches new arXiv papers in quantitative finance
and related ML, scores them locally with a small LLM, and notifies you via
Telegram about the top picks.

## Quickstart

```bash
# 1. Install (interactive — picks features, sets up Ollama + Telegram + cron)
pip install -e .
research-pipeline-install install

# 2. Manual dry run (fetch + score, no Telegram send)
research-pipeline run --dry-run

# 3. Real run
research-pipeline run

# 4. Health check
research-pipeline doctor
```

## What it does

```
[arXiv API] → fetch(q-fin.* + cs.LG + stat.ML, last 26h)
      ↓
[SQLite]   → dedup
      ↓
[Ollama]   → Stage A: abstract score 0–10
      ↓ threshold ≥ 7
[PDF]      → download + extract
      ↓
[Ollama]   → Stage B: deep score + summary
      ↓
[Telegram] → top-K picks with score + summary + link
```

## Configuration

All settings live in `.env`. Copy from `.env.example` and edit. The install
CLI writes a sensible starting `.env` for you.

## Features

Each feature can be enabled/disabled during install:

| Feature | What | Default |
|---|---|---|
| Daily pipeline run | Fetch + score + notify | ✅ on |
| Daily summary | End-of-day stats + top picks | ✅ on |
| Weekly digest | Cluster + summarize the week | ⚪ off |
| AutoBuild | Spawn code/explainer tasks for picks | ⚪ off |
| Telegram bot | Interactive `/ask`, `/last`, … | ⚪ off |
| Backfill CLI | Re-score historical papers | ⚪ off |

## Requirements

- Linux (tested on Debian/Ubuntu)
- Python 3.11+
- 8 GB RAM minimum, 16 GB recommended (Ollama model needs ~4 GB)
- Internet access (arXiv + optional Telegram API)

## Documentation

- [`docs/INSTALL.md`](docs/INSTALL.md) — full install walkthrough, cron wiring, troubleshooting.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — module map, data model, extension points.
- [`docs/PROMPTS.md`](docs/PROMPTS.md) — how the two scoring prompts work, how to customize them.

## CLI

```
research-pipeline              # entry: research_pipeline.cli:main
  run [--dry-run] [--lookback N] [--max N] [--json]
  doctor
  status
  logs [-f]
  backfill stage-a [--days N] [--limit N] [--dry-run]
  backfill stage-b [--days N] [--threshold F] [--limit N] [--dry-run]
  backfill notify  [--days N] [--dry-run]

research-pipeline-install      # entry: research_pipeline.install.wizard:main
  install          # full interactive wizard
  config get|set KEY VAL
  run
  update
  status
  logs [-f]
  diagnose
  uninstall
  doctor
```

## Development

```bash
.venv/bin/pytest -v
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
```

CI runs all three on every PR (`.github/workflows/ci.yml`, Python 3.11 +
3.12 matrix).

## Contributing

Open an issue or a PR. Branch off `main`, follow the existing module
boundaries (`db`, `score`, `notify`, `fetch_arxiv`, `pdf_extract`,
`runtime/runner`, install CLI), keep the sanitization rules from the
spec in mind (no private user paths, no proprietary defaults).

## License

MIT — see [LICENSE](LICENSE).
