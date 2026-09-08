"""Doctor and diagnosis functions for install CLI."""

from __future__ import annotations

from research_pipeline.config import CFG
from research_pipeline.install import cron, ollama, telegram


class DoctorResult:
    """Result from running doctor checks."""

    def __init__(self):
        self.checks: list[dict] = []
        self.warnings: int = 0
        self.failures: int = 0

    def add_check(self, name: str, status: str, message: str = "", suggestion: str = ""):
        """Add a check result."""
        is_warning = status == "warning"
        is_failure = status == "failure"

        if is_warning:
            self.warnings += 1
        if is_failure:
            self.failures += 1

        self.checks.append(
            {
                "name": name,
                "status": status,
                "message": message,
                "suggestion": suggestion,
            }
        )

    @property
    def exit_code(self) -> int:
        """Get exit code based on results."""
        if self.failures > 0:
            return 2
        if self.warnings > 0:
            return 1
        return 0


def run_doctor(verbose: bool = False) -> DoctorResult:
    """
    Run full system doctor check.

    Args:
        verbose: Include detailed suggestions

    Returns:
        DoctorResult with all check results
    """
    result = DoctorResult()

    # 1. Check Ollama installation
    ollama_status = ollama.get_ollama_status()
    if ollama_status.installed:
        result.add_check("Ollama reachable", "ok", f"({ollama_status.base_url})")
    else:
        result.add_check(
            "Ollama reachable",
            "failure",
            "Ollama is not running or not installed",
            "Run 'ollama serve' to start the server, or install from https://ollama.com",
        )

    # 2. Check model
    if ollama_status.model_installed:
        result.add_check("Model loaded", "ok", f"({ollama_status.model_name})")
    elif ollama_status.installed:
        result.add_check(
            "Model loaded",
            "failure",
            f"Model {ollama_status.model_name} not installed",
            f"Run 'ollama pull {ollama_status.model_name}'",
        )
    else:
        result.add_check("Model loaded", "warning", "Cannot check - Ollama not running")

    # 3. Check Telegram token
    tg_status = telegram.get_telegram_status()
    if tg_status.token_valid:
        username = f"@{tg_status.bot_username}" if tg_status.bot_username else ""
        result.add_check("Telegram token", "ok", f"({username})")
    else:
        result.add_check(
            "Telegram token",
            "failure",
            tg_status.error or "Token invalid",
            "Run 'research-pipeline-install config set TELEGRAM_BOT_TOKEN <token>'",
        )

    # 4. Check Telegram chat
    if tg_status.chat_valid:
        result.add_check("Telegram chat", "ok", f"(id={tg_status.chat_id})")
    elif tg_status.token_valid:
        result.add_check(
            "Telegram chat",
            "failure",
            tg_status.error or "Chat ID invalid",
            "Run 'research-pipeline-install config set TELEGRAM_CHAT_ID <chat-id>'",
        )
    else:
        result.add_check("Telegram chat", "warning", "Skipped - no token")

    # 5. Check cron
    cron_status = cron.get_cron_entry()
    if cron_status.installed:
        schedule = cron_status.schedule or CFG.cron_daily_time
        result.add_check("Cron registered", "ok", f"({schedule} daily)")
    else:
        result.add_check(
            "Cron registered",
            "warning",
            "No cron entry found",
            "Run 'research-pipeline-install install' to set up scheduling",
        )

    # 6. Check log directory exists and last run
    log_dir = CFG.log_dir
    if log_dir.exists():
        log_file = log_dir / "pipeline.log"
        if log_file.exists():
            try:
                # Get last run time from log file
                mtime = log_file.stat().st_mtime
                from datetime import UTC, datetime

                last_run = datetime.fromtimestamp(mtime, tz=UTC)
                result.add_check(
                    "Last run",
                    "ok",
                    f"{last_run.strftime('%Y-%m-%d %H:%M')}",
                )
            except OSError:
                result.add_check("Last run", "warning", "Cannot read last run time")
        else:
            result.add_check("Last run", "warning", "No runs recorded yet")
    else:
        result.add_check(
            "Last run",
            "warning",
            "Log directory not created yet",
            "Run 'research-pipeline run' to create logs",
        )

    return result


def run_diagnose() -> dict:
    """
    Run per-component diagnostic tests.

    Returns:
        dict with diagnosis results for each component
    """
    results = {
        "ollama": None,
        "arxiv": None,
        "telegram": None,
    }

    # 1. Ollama generation test
    success, elapsed, tokens = ollama.test_generation()
    results["ollama"] = {
        "success": success,
        "elapsed": elapsed,
        "tokens": tokens,
        "error": None if success else "Generation failed",
    }

    # 2. arXiv API test
    try:
        import time
        import urllib.error
        import urllib.request

        categories = ",".join(CFG.arxiv_categories[:2])  # Test with first 2
        url = f"http://export.arxiv.org/api/query?search_query=cat:{categories}&max_results=1"

        start = time.time()
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed = time.time() - start
            results["arxiv"] = {
                "success": resp.status == 200,
                "status_code": resp.status,
                "elapsed": elapsed,
                "error": None if resp.status == 200 else f"HTTP {resp.status}",
            }
    except OSError as e:
        results["arxiv"] = {
            "success": False,
            "status_code": None,
            "elapsed": 0.0,
            "error": str(e),
        }

    # 3. Telegram test
    tg_result = telegram.test_diagnose()
    results["telegram"] = tg_result

    return results
