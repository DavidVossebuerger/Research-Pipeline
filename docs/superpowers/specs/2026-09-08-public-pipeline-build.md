# Research-Pipeline v2 — Sanitized Public Build

## Goal

Make `/root/pipeline-private/`'s research pipeline available as a public,
sanitized, installable GitHub repository at
`https://github.com/DavidVossebuerger/Research-Pipeline` that any user can
clone, customize via `.env`, install with one CLI command, and run on their
own infrastructure.

## Authoritative Reference

The detailed implementation plan lives at
`/root/.claude/plans/schreibe-keinen-superpowers-plan-eager-taco.md`
(written 2026-09-06). This spec is the short, repo-local summary.

## Current State (2026-09-08)

- `pipeline-public/` is a Git repo, remote `origin` = GitHub, default branch `main`.
- Branch protection on `main` enforced via PR workflow (PRs #13 + #14 already merged).
- **Done (merged to `main`):**
  - PR #13 — Issue #1: sanitize `config.py`, `.env.example`, `pyproject.toml` scaffold.
  - PR #14 — Issue #2: install CLI (`research-pipeline-install`) with 9 subcommands (`install`, `config`, `run`, `update`, `status`, `logs`, `diagnose`, `uninstall`, `doctor`).
- **In flight (`feat/3-wave1-foundation`, uncommitted):**
  - `src/research_pipeline/db.py` (SQLite state)
  - `src/research_pipeline/score.py` (Stage A + B scoring, Ollama default)
  - `src/research_pipeline/prompts/` (abstract + deep scoring prompts)
- **Not yet started:** `fetch_arxiv.py`, `pdf_extract.py`, `notify.py`,
  `daily_summary.py`, `weekly_digest.py`, `narrative_review.py`,
  `autobuild.py`, `code_session.py`, `backfill.py`, fixture data,
  feature tests, CI workflow.

## Sanitization Rules (hard constraints, applies to every new file)

The public repo MUST NOT contain any of the following:

- `MiniMax`, `MiniMax-M2.5`, `MiniMax-M3`, `minimax_model`, `MINIMAX_*`,
  `LLM_PROVIDER=minimax`, `https://api.minimax.io/v1`.
- `158.220.101.247`, `wake_bridge`, `WAKE_BRIDGE_*`, `assistent_notifier`,
  `snapshot_exporter`.
- `/opt/assistent/`, `/home/davidv/`, `/srv/tema-v3/d1_data`,
  `/opt/research-pipeline/`.
- `6508378454` (chat_id), `8740982859:` (bot token prefix).
- Any reference to "DavidV", "David Vossebuerger", "MiniMax", "Assistent-App".
- Session logs (`session-*.md`), `.env`, `.env.bak-*`, `secrets/`.

All user-specific values move into `.env`. Every default in code or
`.env.example` must be safe for a fresh GitHub visitor.

## Public Defaults (v2)

- `LLM_PROVIDER=ollama` (was: `openrouter`)
- `LLM_MODEL=phi3.5:3.8b` (was: MiniMax model)
- `NOTIFY_TARGET=telegram` (single channel — no wake-bridge routing)
- `DB_PATH=data/state.db`, `PDF_DIR=pdfs`, `LOG_DIR=logs`
- `AUTOBUILD_DATA_DIR=data/autobuild` (was: `/srv/tema-v3/d1_data`)
- No `WAKE_BRIDGE_*`, no `DATA_EXPORT_DIR`

## Target Architecture

```
research-pipeline/                    # https://github.com/DavidVossebuerger/Research-Pipeline
├── pyproject.toml
├── README.md                         # install-first narrative
├── LICENSE                           # MIT
├── .env.example                      # generic, no user-specific values
├── .gitignore                        # excludes .env, secrets, sessions, caches
├── .github/
│   ├── ISSUE_TEMPLATE/feature.md, bug.md
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/ci.yml              # ruff + pytest on PR
├── src/research_pipeline/
│   ├── __init__.py
│   ├── cli.py                        # research-pipeline entry point
│   ├── config.py                     # env-driven, no user defaults
│   ├── db.py                         # SQLite state
│   ├── fetch_arxiv.py                # arXiv API client
│   ├── score.py                      # 2-stage scoring (Ollama default)
│   ├── pdf_extract.py                # pypdf wrapper
│   ├── notify.py                     # Telegram-only
│   ├── daily_summary.py              # feature-gated
│   ├── weekly_digest.py              # feature-gated
│   ├── narrative_review.py           # helper for daily/weekly
│   ├── autobuild.py                  # feature-gated
│   ├── code_session.py               # helper for autobuild
│   ├── backfill.py                   # CLI for re-scoring
│   ├── install/
│   │   ├── __init__.py
│   │   ├── ollama.py                 # install + model pull
│   │   ├── telegram.py               # token validation via getMe
│   │   ├── cron.py                   # crontab generation + install
│   │   ├── wizard.py                 # interactive feature selection
│   │   └── doctor.py                 # diagnostics
│   ├── prompts/
│   │   ├── abstract_score.txt        # copied from private (no user refs)
│   │   └── deep_score.txt            # copied from private (no user refs)
│   ├── runtime/                      # shared runtime helpers
│   └── logging_setup.py
├── tests/
│   ├── conftest.py
│   ├── test_config.py                # ✅ already present
│   ├── test_install.py               # ✅ already present
│   ├── test_db.py
│   ├── test_fetch_arxiv.py           # uses fixture arxiv response
│   ├── test_score.py                 # mock LLM
│   ├── test_notify.py                # mock Telegram
│   ├── test_daily_summary.py
│   ├── test_weekly_digest.py
│   ├── test_autobuild.py
│   ├── test_backfill.py
│   └── fixtures/arxiv_response.json
├── data/fixtures/arxiv_response.json # checked-in test fixture
├── deploy/research-pipeline.cron     # template, token-substituted by install CLI
├── scripts/dev_run.sh                # source .env + run pipeline
├── scripts/smoke.sh                  # post-install health check
└── docs/
    ├── ARCHITECTURE.md
    ├── PROMPTS.md
    └── INSTALL.md
```

## CLI Surface

Two entry points (`pyproject.toml` `[project.scripts]`):

- `research-pipeline` → `research_pipeline.cli:main`
  - subcommands: `run [--dry-run] [--lookback N] [--max N]`,
    `doctor`, `status`, `logs [-f]`, `backfill ...`
- `research-pipeline-install` → `research_pipeline.install.wizard:main`
  - subcommands: `install`, `config get|set KEY VAL`, `run`, `update`,
    `status`, `logs [-f]`, `diagnose`, `uninstall`, `doctor`

## Development Strategy

Subagent-driven, one PR per issue, isolation via `git worktree`.

For each open issue:
1. Create branch `feat/<issue-nr>-<slug>` from `main`.
2. Dispatch a `general-purpose` subagent with the issue body, sanitization
   rules, and pointers to read-only references in `/root/pipeline-private/`.
3. Subagent implements, writes tests, commits, pushes branch, opens PR
   against `main`.
4. Main thread reviews PR (or requests `superpowers:requesting-code-review`)
   and squash-merges after CI is green.

The first batch (`feat/3-wave1-foundation`) was started without a clean
branch — current uncommitted files (`db.py`, `score.py`, `prompts/`) belong
on a `feat/3-…` branch and need to be committed/pushed as a PR before
parallel work starts to avoid conflicts.

## Implementation Phases (12 issues)

### Phase 0 — Setup ✅
1. Move files to `pipeline-private/`, create `pipeline-public/` git repo.
2. `.gitignore`, `README.md` skeleton, `LICENSE` (MIT), `.github/` templates.
3. Open initial 12 issues.
4. CI workflow scaffold.

### Phase 1 — Sanitization Foundation ✅ (PR #13 merged)
- Issue #1: sanitize `config.py`, `.env.example`, `pyproject.toml`.

### Phase 2 — Install CLI ✅ (PR #14 merged)
- Issue #2: `cli.py` + `install/{ollama,telegram,cron,wizard,doctor}.py`.

### Phase 3 — Core Pipeline (in progress)
- Issue #3: `pipeline.py` orchestrator (CLI `run`).
- Issue #4: `fetch_arxiv.py` + `pdf_extract.py` + fixture.
- Issue #5: `db.py` (already drafted on `feat/3-wave1-foundation`).
- Issue #6: `score.py` (already drafted on `feat/3-wave1-foundation`).
- Issue #7: `notify.py` (Telegram only — NO routing).

### Phase 4 — Feature Modules
- Issue #8: `daily_summary.py`.
- Issue #9: `weekly_digest.py` + `narrative_review.py`.
- Issue #10: `autobuild.py` + `code_session.py` (env-driven data dir).

### Phase 5 — Docs + Polish
- Issue #11: README.md final pass + `docs/INSTALL.md` + `docs/ARCHITECTURE.md`.
- Issue #12: GitHub Actions CI (`ruff` + `pytest`) + secret scan baseline.
- Bonus: `backfill.py` CLI for re-scoring historical papers.

## Verification

Before tagging `v0.1.0`:

```bash
# Fresh-clone install in an empty dir, run as a non-root user
cd /tmp && git clone https://github.com/DavidVossebuerger/Research-Pipeline.git
cd Research-Pipeline && python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"
# Use test bot + chat id; expect full install wizard to complete without errors.
.venv/bin/research-pipeline-install install
.venv/bin/research-pipeline run --dry-run        # scores fixture, no Telegram
.venv/bin/research-pipeline run                  # real Telegram send
.venv/bin/research-pipeline doctor
# Tests + lint + secrets
.venv/bin/pytest -v
.venv/bin/ruff check src/ tests/
detect-secrets scan > .secrets.baseline           # only .env.example placeholders
gh pr checks                                       # all green on main
git tag v0.1.0 && git push --tags                 # create GitHub release
```

Acceptance:

- [ ] All 12 issues closed via merged PR.
- [ ] `pip install -e .` works in fresh venv.
- [ ] `research-pipeline-install install` completes the 8-step wizard.
- [ ] `research-pipeline run --dry-run` scores ≥1 fixture paper end-to-end.
- [ ] `research-pipeline run` sends real Telegram message with top picks.
- [ ] `research-pipeline doctor` reports green for Ollama, Telegram, cron.
- [ ] `pytest` + `ruff` clean.
- [ ] `detect-secrets` reports only `.env.example` placeholders.
- [ ] No sanitization-rule violations in repo (`grep -r ...` checks).
- [ ] `v0.1.0` GitHub release published.
