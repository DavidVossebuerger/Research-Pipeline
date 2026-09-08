"""Install wizard CLI - the main entry point for research-pipeline-install."""

from __future__ import annotations

import json
import re
import sys
import time
from importlib import reload
from pathlib import Path

import click
import httpx

from research_pipeline import score as score_module
from research_pipeline.config import CFG
from research_pipeline.install import (
    cron,
    ollama,
    telegram,
)
from research_pipeline.install import doctor as doctor_module
from research_pipeline.logging_setup import setup_logging

logger = setup_logging("research_pipeline.install")


def get_env_path() -> Path:
    """Get path to .env file."""
    return Path(".env")


def read_env_file(path: Path) -> dict[str, str]:
    """Read .env file and return key-value pairs."""
    env = {}
    if not path.exists():
        return env

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                # Remove quotes if present
                if value and (value[0] == value[-1] == '"' or value[0] == value[-1] == "'"):
                    value = value[1:-1]
                env[key] = value
    return env


def write_env_file(path: Path, env: dict[str, str]):
    """Write .env file from key-value pairs."""
    # Atomic write: temp file + rename
    temp_path = path.with_suffix(".env.tmp")
    with open(temp_path, "w") as f:
        for key, value in sorted(env.items()):
            if " " in value:
                f.write(f'{key}="{value}"\n')
            else:
                f.write(f"{key}={value}\n")
    temp_path.replace(path)


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Research Pipeline v2 - Install and manage your daily paper pipeline."""


@cli.command()
@click.option("--yes", "-y", is_flag=True, help="Use defaults / skip prompts")
def install(yes: bool):
    """Interactive first-time setup."""
    click.echo("=== Research Pipeline Installation ===\n")

    env_path = get_env_path()
    existing_env = read_env_file(env_path) if env_path.exists() else {}

    # Reload config to get fresh values
    from importlib import reload

    import research_pipeline.config as config_module

    reload(config_module)
    cfg = config_module.CFG

    # Step 1: Check Ollama
    click.echo("[1/8] Checking Ollama...")
    installed, version = ollama.check_ollama_installed()
    if not installed:
        click.echo("\nOllama is not installed.")
        click.echo("Install command:")
        click.echo("  curl -fsSL https://ollama.com/install.sh | sh")
        click.echo("\nAfter installing, run this command again.")
        sys.exit(1)

    click.echo(f"  ✓ Ollama installed: {version}")

    # Step 2: LLM Provider selection
    click.echo("\n[2/8] LLM Provider")

    # Determine default provider from existing env or config
    default_provider = existing_env.get("LLM_PROVIDER", cfg.llm_provider)

    # Map to menu numbers for display
    provider_map = {"1": "ollama", "2": "openai_compat", "3": "anthropic_compat"}

    if yes:
        # In --yes mode, use existing LLM_PROVIDER or default to Ollama
        provider = default_provider
        if provider in provider_map:
            provider = provider_map[provider]
    else:
        click.echo("  1) Ollama (local, recommended for first install)")
        click.echo("  2) Custom API — OpenAI-compatible")
        click.echo("  3) Custom API — Anthropic-compatible")

        # Determine default choice number
        default_choice = "1"
        if default_provider in provider_map:
            default_choice = default_provider
        elif default_provider in provider_map.values():
            for k, v in provider_map.items():
                if v == default_provider:
                    default_choice = k
                    break

        prompt = f"Choice [{default_choice}]"
        provider_choice = click.prompt(prompt, default=default_choice, type=int)

        # Determine provider name
        if provider_choice == 1 or provider_choice == "ollama":
            provider = "ollama"
        elif provider_choice == 2 or provider_choice == "openai_compat":
            provider = "openai_compat"
        elif provider_choice == 3 or provider_choice == "anthropic_compat":
            provider = "anthropic_compat"
        else:
            click.echo("  ✗ Invalid choice. Using Ollama.")
            provider = "ollama"

    # Step 3: Provider-specific configuration
    if provider == "ollama":
        # Ollama: pull model
        model_name = cfg.llm_model
        if yes and "LLM_MODEL" in existing_env:
            model_name = existing_env["LLM_MODEL"]

        model_installed = ollama.check_model_installed(model_name)
        if not model_installed:
            if yes:
                click.echo(f"\n[3/8] Pulling model {model_name}...")
                result = ollama.pull_model(model_name)
                if result.returncode != 0:
                    click.echo(f"  ✗ Failed to pull model: {result.stderr}")
                    sys.exit(1)
                click.echo("  ✓ Model pulled")
            else:
                click.echo(f"\n[3/8] Model {model_name} not installed.")
                if click.confirm(f"  Pull {model_name} now?", default=True):
                    click.echo("  Pulling model (this may take a few minutes)...")
                    result = ollama.pull_model(model_name)
                    if result.returncode != 0:
                        click.echo(f"  ✗ Failed to pull model: {result.stderr}")
                        sys.exit(1)
                    click.echo("  ✓ Model pulled")
        else:
            click.echo(f"  ✓ Model {model_name} already installed")

        base_url = "http://localhost:11434"
        api_key = ""

    elif provider == "openai_compat":
        # OpenAI-compatible: prompt for URL, model, API key
        click.echo("\n[3/8] OpenAI-compatible API")

        base_url = existing_env.get("LLM_BASE_URL", "https://api.openai.com/v1")
        if yes:
            pass  # use existing
        else:
            base_url = click.prompt(
                "  Base URL (e.g. https://api.openai.com/v1)",
                default=base_url,
            )

        model_name = existing_env.get("LLM_MODEL", "gpt-4o-mini")
        if not yes:
            model_name = click.prompt(
                "  Model ID (e.g. gpt-4o-mini)",
                default=model_name,
            )

        api_key = existing_env.get("LLM_API_KEY", "")
        if not yes:
            api_key = click.prompt("  API key", default=api_key, hide_input=True)

        # Validate with test call
        if not yes:
            click.echo("  Validating with test call...")
            try:
                test_result = score_module._chat(
                    [{"role": "user", "content": "Reply with OK"}],
                    model=model_name,
                    base_url=base_url,
                    api_key=api_key,
                    temperature=0.2,
                    max_tokens=10,
                    provider=provider,
                )
                if test_result and test_result.strip():
                    click.echo("  ✓ Test call successful")
                else:
                    click.echo("  ✗ Test call returned empty response")
                    sys.exit(1)
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
                click.echo(f"  ✗ Test call failed: {e}")
                sys.exit(1)

    else:  # anthropic_compat
        # Anthropic-compatible: prompt for URL, model, API key
        click.echo("\n[3/8] Anthropic-compatible API")

        base_url = existing_env.get("LLM_BASE_URL", "https://api.anthropic.com")
        if not yes:
            base_url = click.prompt(
                "  Base URL",
                default=base_url,
            )

        model_name = existing_env.get("LLM_MODEL", "claude-3-5-sonnet-20241022")
        if not yes:
            model_name = click.prompt(
                "  Model ID (e.g. claude-3-5-sonnet-20241022)",
                default=model_name,
            )

        api_key = existing_env.get("LLM_API_KEY", "")
        if not yes:
            api_key = click.prompt("  API key", default=api_key, hide_input=True)

        # Validate with test call
        if not yes:
            click.echo("  Validating with test call...")
            try:
                test_result = score_module._chat(
                    [{"role": "user", "content": "Reply with OK"}],
                    model=model_name,
                    base_url=base_url,
                    api_key=api_key,
                    temperature=0.2,
                    max_tokens=10,
                    provider=provider,
                )
                if test_result and test_result.strip():
                    click.echo("  ✓ Test call successful")
                else:
                    click.echo("  ✗ Test call returned empty response")
                    sys.exit(1)
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
                click.echo(f"  ✗ Test call failed: {e}")
                sys.exit(1)

    # Step 4: Telegram bot setup
    click.echo("\n[4/8] Telegram Bot Setup")

    bot_token = existing_env.get("TELEGRAM_BOT_TOKEN", "")
    if yes and not bot_token:
        click.echo("  Skipping Telegram (no token in existing .env)")
    else:
        while True:
            if bot_token:
                prompt = f"Bot token [{'*' * 8}]: "
            else:
                prompt = "Bot token (get from @BotFather): "

            if yes:
                break

            input_token = click.prompt(prompt, default=bot_token, show_default=False)
            if not input_token:
                click.echo("  Skipping Telegram setup")
                break

            # Validate token
            valid, username, error = telegram.validate_bot_token(input_token)
            if valid:
                click.echo(f"  ✓ Token valid (@{username})")
                bot_token = input_token
                break
            else:
                click.echo(f"  ✗ Invalid token: {error}")

        # Chat ID
        chat_id = existing_env.get("TELEGRAM_CHAT_ID", "")
        if bot_token and not chat_id:
            if yes:
                click.echo("  Skipping chat ID")
            else:
                while True:
                    input_chat = click.prompt(
                        "Chat ID (your Telegram user/chat ID): ", default=chat_id
                    )
                    if not input_chat:
                        click.echo("  Skipping chat ID")
                        break

                    # Validate chat
                    valid, error = telegram.validate_chat_id(bot_token, input_chat)
                    if valid:
                        click.echo("  ✓ Chat validated - test message sent!")
                        chat_id = input_chat
                        break
                    else:
                        click.echo(f"  ✗ Chat validation failed: {error}")

    # Step 5: Feature toggles
    click.echo("\n[5/8] Feature Toggles")

    if yes and "FEATURE_DAILY_SUMMARY_ENABLED" in existing_env:
        daily_enabled = existing_env["FEATURE_DAILY_SUMMARY_ENABLED"].lower() == "true"
    else:
        daily_enabled = click.confirm("  Enable daily summary?", default=True)

    if yes and "FEATURE_WEEKLY_DIGEST_ENABLED" in existing_env:
        weekly_enabled = existing_env["FEATURE_WEEKLY_DIGEST_ENABLED"].lower() == "true"
    else:
        weekly_enabled = click.confirm("  Enable weekly digest?", default=False)

    if yes and "FEATURE_AUTOBUILD_ENABLED" in existing_env:
        autobuild_enabled = existing_env["FEATURE_AUTOBUILD_ENABLED"].lower() == "true"
    else:
        autobuild_enabled = click.confirm("  Enable AutoBuild?", default=False)

    if yes and "FEATURE_TELEGRAM_BOT_ENABLED" in existing_env:
        tg_bot_enabled = existing_env["FEATURE_TELEGRAM_BOT_ENABLED"].lower() == "true"
    else:
        tg_bot_enabled = click.confirm(
            "  Enable Telegram bot (interactive commands)?", default=False
        )

    if yes and "FEATURE_BACKFILL_ENABLED" in existing_env:
        backfill_enabled = existing_env["FEATURE_BACKFILL_ENABLED"].lower() == "true"
    else:
        backfill_enabled = click.confirm("  Enable Backfill CLI?", default=False)

    # Step 6: Schedule
    click.echo("\n[6/8] Schedule")

    if yes and "CRON_DAILY_TIME" in existing_env:
        schedule = existing_env["CRON_DAILY_TIME"]
    else:
        schedule = click.prompt("  Daily run time (HH:MM)", default="07:30")

    # Validate time format
    if not re.match(r"^\d{1,2}:\d{2}$", schedule):
        click.echo("  ✗ Invalid time format. Use HH:MM (e.g., 07:30)")
        sys.exit(1)

    # Step 7: Write .env
    click.echo("\n[7/8] Writing .env file...")

    new_env = {
        "LLM_PROVIDER": provider,
        "LLM_MODEL": model_name,
        "LLM_BASE_URL": base_url,
        "LLM_API_KEY": api_key,
        "TELEGRAM_BOT_TOKEN": bot_token,
        "TELEGRAM_CHAT_ID": chat_id,
        "TELEGRAM_TOPIC_PICKS": existing_env.get("TELEGRAM_TOPIC_PICKS", ""),
        "TELEGRAM_TOPIC_SUMMARY": existing_env.get("TELEGRAM_TOPIC_SUMMARY", ""),
        "CRON_DAILY_TIME": schedule,
        "CRON_AUTOBUILD_POLL": cfg.cron_autobuild_poll,
        "FEATURE_DAILY_SUMMARY_ENABLED": str(daily_enabled).lower(),
        "FEATURE_WEEKLY_DIGEST_ENABLED": str(weekly_enabled).lower(),
        "FEATURE_AUTOBUILD_ENABLED": str(autobuild_enabled).lower(),
        "FEATURE_TELEGRAM_BOT_ENABLED": str(tg_bot_enabled).lower(),
        "FEATURE_BACKFILL_ENABLED": str(backfill_enabled).lower(),
        "ARXIV_CATEGORIES": ",".join(cfg.arxiv_categories),
        "ARXIV_LOOKBACK_HOURS": str(cfg.arxiv_lookback_hours),
        "ARXIV_MAX_RESULTS": str(cfg.arxiv_max_results),
        "ARXIV_FIXTURE_PATH": cfg.arxiv_fixture_path,
        "SCORE_STAGE_A_THRESHOLD": str(cfg.score_stage_a_threshold),
        "SCORE_STAGE_B_TOP_K": str(cfg.score_stage_b_top_k),
        "NOTIFY_TOP_K": str(cfg.notify_top_k),
        "DB_PATH": str(cfg.db_path),
        "PDF_DIR": str(cfg.pdf_dir),
        "LOG_DIR": str(cfg.log_dir),
        "AUTOBUILD_DATA_DIR": str(cfg.autobuild_data_dir),
    }

    if env_path.exists() and not yes:
        click.echo("  .env already exists. Showing diff:")
        existing = read_env_file(env_path)
        for key, value in new_env.items():
            if key in existing:
                if existing[key] != value:
                    click.echo(f"    {key}: {existing[key]} -> {value}")
            else:
                click.echo(f"    {key}: (new) {value}")
        if click.confirm("\n  Overwrite existing .env?", default=False):
            write_env_file(env_path, new_env)
            click.echo("  ✓ .env written")
    else:
        write_env_file(env_path, new_env)
        click.echo("  ✓ .env written")

    # Step 8: Register cron
    click.echo("\n[8/8] Registering cron...")

    success, error = cron.install_cron_entry()
    if success:
        click.echo("  ✓ Cron entry installed")
    else:
        click.echo(f"  ✗ Failed to install cron: {error}")

    click.echo("\n=== Installation Complete ===")
    click.echo("Next steps:")
    click.echo("  - Run 'research-pipeline-install status' to check health")
    click.echo("  - Run 'research-pipeline-install diagnose' for detailed tests")
    click.echo("  - Run 'research-pipeline run' to test the pipeline")


@cli.group()
def config():
    """Manage .env configuration."""


@config.command(name="get")
@click.argument("key")
def config_get(key: str):
    """Read one env var from .env."""
    env_path = get_env_path()
    env = read_env_file(env_path)

    if key in env:
        click.echo(env[key])
    else:
        click.echo(f"Key '{key}' not found in .env", err=True)
        sys.exit(1)


@config.command(name="set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Update one env var in .env."""
    env_path = get_env_path()
    env = read_env_file(env_path)

    # Update or add
    env[key] = value

    # Write back
    write_env_file(env_path, env)
    click.echo(f"✓ {key}={value}")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Don't send notifications")
@click.option("--lookback", "lookback_hours", type=int, help="Look back N hours")
@click.option("--max", "max_papers", type=int, help="Max papers to fetch")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def run(dry_run: bool, lookback_hours: int | None, max_papers: int | None, json_output: bool):
    """Trigger a single pipeline run."""
    # Reload config to pick up any .env changes

    import research_pipeline.config as config_module
    from research_pipeline.runtime import runner

    reload(config_module)

    result = runner.run_pipeline(
        dry_run=dry_run,
        lookback_hours=lookback_hours,
        max_papers=max_papers,
    )

    if json_output:
        click.echo(json.dumps(result))
    else:
        click.echo(
            f"Pipeline run complete: {result['papers_seen']} seen, {result['papers_picked']} picked"
        )
        if result["errors"]:
            click.echo(f"Errors: {result['errors']}")


@cli.command()
def update():
    """Refresh Ollama model + cron entry."""
    # Reload config
    import research_pipeline.config as config_module

    reload(config_module)
    cfg = config_module.CFG

    click.echo("Updating Ollama model...")
    result = ollama.pull_model(cfg.llm_model)
    if result.returncode == 0:
        click.echo("✓ Model updated")
    else:
        click.echo(f"✗ Failed to update model: {result.stderr}")
        sys.exit(1)

    click.echo("\nRe-installing cron entry...")
    success, error = cron.install_cron_entry()
    if success:
        click.echo("✓ Cron entry updated")
    else:
        click.echo(f"✗ Failed to update cron: {error}")
        sys.exit(1)


@cli.command()
def status():
    """Health check - one line per check."""
    import research_pipeline.config as config_module

    reload(config_module)

    # Ollama
    ollama_status = ollama.get_ollama_status()
    if ollama_status.installed:
        click.echo(f"Ollama reachable       ✓ ({ollama_status.base_url})")
    else:
        click.echo("Ollama reachable       ✗")

    # Model
    if ollama_status.model_installed:
        click.echo(f"Model loaded           ✓ ({ollama_status.model_name})")
    else:
        click.echo("Model loaded           ✗")

    # Telegram
    tg_status = telegram.get_telegram_status()
    if tg_status.token_valid:
        username = f"@{tg_status.bot_username}" if tg_status.bot_username else ""
        click.echo(f"Telegram token         ✓ ({username})")
    else:
        click.echo("Telegram token         ✗")

    # Chat
    if tg_status.chat_valid:
        click.echo(f"Telegram chat          ✓ (id={tg_status.chat_id})")
    else:
        click.echo("Telegram chat          ✗")

    # Cron
    cron_status = cron.get_cron_entry()
    if cron_status.installed:
        schedule = cron_status.schedule or config_module.CFG.cron_daily_time
        click.echo(f"Cron registered        ✓ ({schedule} daily)")
    else:
        click.echo("Cron registered        ✗")

    # Last run
    log_dir = config_module.CFG.log_dir
    log_file = log_dir / "pipeline.log"
    if log_file.exists():
        mtime = log_file.stat().st_mtime
        from datetime import UTC, datetime

        last_run = datetime.fromtimestamp(mtime, tz=UTC)
        click.echo(f"Last run               ✓ ({last_run.strftime('%Y-%m-%d %H:%M')})")
    else:
        click.echo("Last run               ⚠ no runs recorded yet")


@cli.command()
@click.option("-f", "--follow", is_flag=True, help="Follow logs")
@click.option("--since", "since_date", help="Filter since date (YYYY-MM-DD)")
def logs(follow: bool, since_date: str | None):
    """Tail logs (default last 100 lines, -f for follow)."""
    import research_pipeline.config as config_module

    reload(config_module)

    log_dir = config_module.CFG.log_dir
    log_files = [log_dir / "pipeline.log"]

    # Also check for other log files
    for name in ["daily_summary.log", "weekly_digest.log"]:
        path = log_dir / name
        if path.exists():
            log_files.append(path)

    if not log_files:
        click.echo("No log files found")
        return

    if follow:
        # Tail -f mode
        import subprocess

        processes = []
        for log_file in log_files:
            if log_file.exists():
                proc = subprocess.Popen(["tail", "-f", str(log_file)])
                processes.append(proc)

        click.echo("Following logs (Ctrl+C to exit)...")
        try:
            # Wait for interrupt
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            click.echo("\nStopping...")
            for proc in processes:
                proc.terminate()
    else:
        # Print last 100 lines
        for log_file in log_files:
            if log_file.exists():
                click.echo(f"\n=== {log_file.name} ===")
                with open(log_file) as f:
                    lines = f.readlines()
                    for line in lines[-100:]:
                        click.echo(line.rstrip())


@cli.command()
def diagnose():
    """Per-component diagnostic test."""
    click.echo("Running diagnostics...\n")

    results = doctor_module.run_diagnose()

    # Ollama
    click.echo("[1/3] Ollama generation")
    ollama_result = results["ollama"]
    if ollama_result["success"]:
        click.echo(
            f"  → POST {CFG.llm_base_url}/api/generate  → 200 ({ollama_result['elapsed']:.1f}s, {ollama_result['tokens']} tokens)"
        )
        click.echo("  ✓ Model responds correctly")
    else:
        click.echo(f"  ✗ {ollama_result.get('error', 'Failed')}")

    # arXiv
    click.echo("\n[2/3] arXiv API")
    arxiv_result = results["arxiv"]
    if arxiv_result["success"]:
        click.echo(
            f"  → GET http://export.arxiv.org/api/query  → {arxiv_result['status_code']} ({arxiv_result['elapsed']:.1f}s)"
        )
        click.echo("  ✓ API reachable")
    else:
        click.echo(f"  ✗ {arxiv_result.get('error', 'Failed')}")

    # Telegram
    click.echo("\n[3/3] Telegram")
    tg_result = results["telegram"]
    if tg_result["success"]:
        click.echo("  → GET https://api.telegram.org/bot.../getMe  → 200")
        click.echo(f"  → Bot: @{tg_result['bot_username']}")
        click.echo("  ✓ Token valid")
    else:
        click.echo(f"  ✗ {tg_result.get('error', 'Failed')}")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Don't actually uninstall")
@click.option("--purge", is_flag=True, help="Also delete .env file")
def uninstall(dry_run: bool, purge: bool):
    """Remove cron entry, optionally purge .env."""
    if not dry_run and not click.confirm("Remove cron entry?", default=False):
        click.echo("Aborted.")
        sys.exit(1)

    # Remove cron
    if not dry_run:
        success, error = cron.remove_cron_entry()
        if success:
            click.echo("✓ Cron entry removed")
        else:
            click.echo(f"✗ Failed to remove cron: {error}")
            sys.exit(1)
    else:
        click.echo("[dry-run] Would remove cron entry")

    # Purge .env
    env_path = get_env_path()
    if purge and env_path.exists():
        if not dry_run:
            env_path.unlink()
            click.echo("✓ .env deleted")
        else:
            click.echo("[dry-run] Would delete .env")
    elif purge:
        click.echo("  (no .env to delete)")

    click.echo("\n✓ Uninstalled. To reinstall: research-pipeline-install install")


@cli.command()
@click.option("-v", "--verbose", is_flag=True, help="Verbose output with fix suggestions")
def doctor(verbose: bool):
    """Full system check with fix suggestions."""
    import research_pipeline.config as config_module

    reload(config_module)

    result = doctor_module.run_doctor(verbose=verbose)

    for check in result.checks:
        status_icon = {"ok": "✓", "warning": "⚠", "failure": "✗"}.get(check["status"], "?")

        if check["status"] == "ok":
            click.echo(f"{status_icon} {check['name']} {check['message']}")
        elif check["status"] == "warning":
            click.echo(f"{status_icon} {check['name']} — {check['message']}")
            if verbose and check["suggestion"]:
                click.echo(f"  → {check['suggestion']}")
        else:  # failure
            click.echo(f"{status_icon} {check['name']} ({check['message']})")
            if check["suggestion"]:
                click.echo(f"  → Fix: {check['suggestion']}")

    click.echo(f"\nExit code: {result.exit_code}")
    sys.exit(result.exit_code)


def main():
    """Entry point for research-pipeline-install."""
    cli()


if __name__ == "__main__":
    main()
