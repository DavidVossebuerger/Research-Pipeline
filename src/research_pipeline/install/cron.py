"""Cron helper functions for install CLI."""

from __future__ import annotations

import re
import subprocess
from typing import NamedTuple

from research_pipeline.config import CFG


class CronStatus(NamedTuple):
    """Status result from cron check."""

    installed: bool
    schedule: str | None
    command: str | None
    error: str | None


def get_cron_entry() -> CronStatus:
    """
    Check if cron entry exists for research-pipeline.

    Returns:
        CronStatus with installation details
    """
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode != 0:
            # No crontab or empty crontab
            if "no crontab" in result.stderr.lower():
                return CronStatus(
                    installed=False,
                    schedule=None,
                    command=None,
                    error=None,
                )
            return CronStatus(
                installed=False,
                schedule=None,
                command=None,
                error=result.stderr,
            )

        # Search for research-pipeline entry
        for line in result.stdout.splitlines():
            if "research_pipeline" in line and "research-pipeline" not in line.lower():
                # Parse cron entry
                match = re.match(r"^(\S+)\s+(\S+)\s+.*research[_-]pipeline", line)
                if match:
                    minute, hour = match.groups()
                    schedule = f"{minute} {hour} * * *"
                else:
                    schedule = None
                return CronStatus(
                    installed=True,
                    schedule=schedule,
                    command=line.strip(),
                    error=None,
                )

        return CronStatus(
            installed=False,
            schedule=None,
            command=None,
            error=None,
        )

    except FileNotFoundError:
        return CronStatus(
            installed=False,
            schedule=None,
            command=None,
            error="crontab command not found",
        )
    except OSError as e:
        return CronStatus(
            installed=False,
            schedule=None,
            command=None,
            error=str(e),
        )


def install_cron_entry(python_path: str | None = None) -> tuple[bool, str | None]:
    """
    Install cron entry for daily pipeline run.

    Args:
        python_path: Path to python interpreter. If None, uses sys.executable

    Returns:
        tuple of (success, error_message)
    """
    # Parse schedule
    time_parts = CFG.cron_daily_time.split(":")
    if len(time_parts) != 2:
        return False, f"Invalid schedule time: {CFG.cron_daily_time}"

    minute, hour = time_parts

    # Build command
    python = python_path or "python3"
    install_dir = CFG.log_dir.parent.resolve()  # Project root
    log_file = CFG.log_dir / "pipeline.log"

    cron_line = f"{minute} {hour} * * * cd {install_dir} && {python} -m research_pipeline.cli run >> {log_file} 2>&1"

    try:
        # Get current crontab
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        current_lines = []
        if result.returncode == 0:
            # Filter out existing research-pipeline entries
            for line in result.stdout.splitlines():
                if "research_pipeline" not in line:
                    current_lines.append(line)

        # Add new entry
        current_lines.append(cron_line)

        # Write new crontab
        new_crontab = "\n".join(current_lines) + "\n"
        proc = subprocess.run(
            ["crontab", "-"],
            input=new_crontab,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if proc.returncode == 0:
            return True, None
        return False, proc.stderr

    except OSError as e:
        return False, str(e)


def remove_cron_entry() -> tuple[bool, str | None]:
    """
    Remove cron entry for research-pipeline.

    Returns:
        tuple of (success, error_message)
    """
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode != 0:
            # No crontab exists, nothing to remove
            return True, None

        # Filter out research-pipeline entries
        new_lines = []
        for line in result.stdout.splitlines():
            if "research_pipeline" not in line:
                new_lines.append(line)

        # Write back
        new_crontab = "\n".join(new_lines) + "\n"
        proc = subprocess.run(
            ["crontab", "-"],
            input=new_crontab,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if proc.returncode == 0:
            return True, None
        return False, proc.stderr

    except OSError as e:
        return False, str(e)
