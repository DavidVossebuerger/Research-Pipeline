from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # loads .env if present, no-op otherwise


def _env(key: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.getenv(key, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {key}. Run `research-pipeline-install install` or set it manually.")
    return val or ""


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    return int(raw) if raw else default


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    return float(raw) if raw else default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _env_list(key: str, default: list[str]) -> list[str]:
    raw = os.getenv(key, "")
    return [x.strip() for x in raw.split(",") if x.strip()] if raw else default


@dataclass(frozen=True)
class Config:
    # LLM
    llm_provider: str  # "ollama" | "openrouter"
    llm_model: str
    llm_base_url: str
    llm_api_key: str  # empty for ollama

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_topic_picks: str
    telegram_topic_summary: str

    # Schedule
    cron_daily_time: str
    cron_autobuild_poll: str

    # Features
    feature_daily_summary_enabled: bool
    feature_weekly_digest_enabled: bool
    feature_autobuild_enabled: bool
    feature_telegram_bot_enabled: bool
    feature_backfill_enabled: bool

    # ArXiv
    arxiv_categories: list[str]
    arxiv_lookback_hours: int
    arxiv_max_results: int
    arxiv_fixture_path: str

    # Scoring
    score_stage_a_threshold: float
    score_stage_b_top_k: int
    notify_top_k: int

    # Paths
    db_path: Path
    pdf_dir: Path
    log_dir: Path
    autobuild_data_dir: Path

    def __post_init__(self):
        # Resolve relative paths to absolute, relative to cwd (so crontab finds them)
        for name in ("db_path", "pdf_dir", "log_dir", "autobuild_data_dir"):
            p = getattr(self, name)
            if not p.is_absolute():
                object.__setattr__(self, name, p.resolve())


def load_config() -> Config:
    return Config(
        llm_provider=_env("LLM_PROVIDER", "ollama"),
        llm_model=_env("LLM_MODEL", "phi3.5:3.8b"),
        llm_base_url=_env("LLM_BASE_URL", "http://localhost:11434"),
        llm_api_key=_env("LLM_API_KEY", ""),
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
        telegram_topic_picks=_env("TELEGRAM_TOPIC_PICKS", ""),
        telegram_topic_summary=_env("TELEGRAM_TOPIC_SUMMARY", ""),
        cron_daily_time=_env("CRON_DAILY_TIME", "07:30"),
        cron_autobuild_poll=_env("CRON_AUTOBUILD_POLL", "*/5"),
        feature_daily_summary_enabled=_env_bool("FEATURE_DAILY_SUMMARY_ENABLED", True),
        feature_weekly_digest_enabled=_env_bool("FEATURE_WEEKLY_DIGEST_ENABLED", False),
        feature_autobuild_enabled=_env_bool("FEATURE_AUTOBUILD_ENABLED", False),
        feature_telegram_bot_enabled=_env_bool("FEATURE_TELEGRAM_BOT_ENABLED", False),
        feature_backfill_enabled=_env_bool("FEATURE_BACKFILL_ENABLED", False),
        arxiv_categories=_env_list("ARXIV_CATEGORIES", ["q-fin.GN", "q-fin.TR", "q-fin.PR", "q-fin.RM", "q-fin.ST", "q-fin.MF", "cs.LG", "stat.ML"]),
        arxiv_lookback_hours=_env_int("ARXIV_LOOKBACK_HOURS", 26),
        arxiv_max_results=_env_int("ARXIV_MAX_RESULTS", 200),
        arxiv_fixture_path=_env("ARXIV_FIXTURE_PATH", ""),
        score_stage_a_threshold=_env_float("SCORE_STAGE_A_THRESHOLD", 7.0),
        score_stage_b_top_k=_env_int("SCORE_STAGE_B_TOP_K", 10),
        notify_top_k=_env_int("NOTIFY_TOP_K", 3),
        db_path=Path(_env("DB_PATH", "data/state.db")),
        pdf_dir=Path(_env("PDF_DIR", "pdfs")),
        log_dir=Path(_env("LOG_DIR", "logs")),
        autobuild_data_dir=Path(_env("AUTOBUILD_DATA_DIR", "data/autobuild")),
    )


CFG = load_config()
