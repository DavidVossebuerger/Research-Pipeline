"""AutoBuild: classify papers and launch code sessions for building.

This module provides the core AutoBuild functionality:
- classify_paper_strategy(): determines if a paper is suitable for strategy backtest or research article
- prepare_goal(): writes goal.md with instructions for the session
- launch_autobuild(): spawns a CodeSession for a paper
- poll_autobuild_sessions(): checks status of all running sessions
- run_autobuild_for_picks(): entry point for launching autobuilds from the pipeline
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .config import Config, load_config
from .db import get_connection, record_ai_event
from .code_session import CodeSession

log = logging.getLogger(__name__)

# Strategy-related tags that indicate a paper is suitable for backtesting
_STRATEGY_TAGS = {
    "strategy",
    "trading",
    "backtest",
    "execution",
    "portfolio",
    "alpha",
    "factor",
    "signal",
}


def classify_paper_strategy(paper: dict, cfg: Config) -> str:
    """Classify whether a paper should be processed as 'strategy' or 'research'.

    This is a simple heuristic based on deep_tags. Papers with tags related to
    trading strategies, backtests, or execution are classified as 'strategy'.
    All others are classified as 'research' (suitable for article generation).

    Args:
        paper: Paper dict with 'deep_tags' field (comma-separated string or list).
        cfg: Config object (unused, kept for API consistency).

    Returns:
        "strategy" if the paper has trading-related tags, otherwise "research".
    """
    deep_tags = paper.get("deep_tags", "")

    # Handle both string and list formats
    if isinstance(deep_tags, str):
        tags_set = {tag.strip().lower() for tag in deep_tags.split(",") if tag.strip()}
    elif isinstance(deep_tags, list):
        tags_set = {str(tag).strip().lower() for tag in deep_tags}
    else:
        tags_set = set()

    # Check for any strategy-related tags
    if tags_set & _STRATEGY_TAGS:
        return "strategy"

    return "research"


def prepare_goal(arxiv_id: str, paper: dict, mode: str, cfg: Config) -> Path:
    """Write a goal.md file with instructions for the autobuild session.

    Args:
        arxiv_id: The arXiv ID of the paper.
        paper: Paper dict with 'title', 'abstract', 'deep_summary', etc.
        mode: Either "strategy" or "research".
        cfg: Config with autobuild_data_dir path.

    Returns:
        Path to the created goal.md file.
    """
    work_dir = cfg.autobuild_data_dir / arxiv_id
    work_dir.mkdir(parents=True, exist_ok=True)
    goal_file = work_dir / "goal.md"

    if mode == "strategy":
        goal_content = f"""# Goal: Build a Python Backtest

## Paper
- **Title**: {paper.get('title', 'N/A')}
- **arXiv ID**: {arxiv_id}

## Task
Build a Python backtest using yfinance and CSV data. Save:
- `backtest.py` - the main backtest script
- `plots/equity_curve.png` - equity curve visualization

## Instructions
1. Use `python -m pip install yfinance` to install dependencies
2. Download historical data for the assets mentioned in the paper
3. Implement the trading strategy described
4. Run the backtest and generate visualizations
5. Save all output files to the working directory
"""
    else:  # research
        goal_content = f"""# Goal: Write a German Markdown Article

## Paper
- **Title**: {paper.get('title', 'N/A')}
- **arXiv ID**: {arxiv_id}

## Task
Write a German Markdown article at `article.md` summarizing the paper.

## Instructions
1. Summarize the paper's abstract and key findings
2. Write in German language
3. Structure the article with:
   - Introduction
   - Methodology
   - Results
   - Conclusion
4. Save as `article.md` in the working directory
"""

    goal_file.write_text(goal_content, encoding="utf-8")
    log.info("Wrote goal.md for %s (mode=%s)", arxiv_id, mode)

    return goal_file


def launch_autobuild(arxiv_id: str, paper: dict, cfg: Config) -> CodeSession | None:
    """Launch an autobuild session for a paper.

    Args:
        arxiv_id: The arXiv ID of the paper.
        paper: Paper dict with 'title', 'abstract', 'deep_summary', etc.
        cfg: Config object with feature_autobuild_enabled and autobuild_data_dir.

    Returns:
        CodeSession if launched, None if autobuild is disabled.
    """
    if not cfg.feature_autobuild_enabled:
        log.info("AutoBuild disabled, skipping %s", arxiv_id)
        return None

    work_dir = cfg.autobuild_data_dir / arxiv_id
    work_dir.mkdir(parents=True, exist_ok=True)

    # Determine mode (strategy or research)
    mode = classify_paper_strategy(paper, cfg)
    log.info("Classified %s as %s", arxiv_id, mode)

    # Write context.md with paper information
    context_content = f"""# Paper Context

**arXiv ID**: {arxiv_id}
**Title**: {paper.get('title', 'N/A')}
**Abstract**: {paper.get('abstract', 'N/A')}
**Deep Summary**: {paper.get('deep_summary', 'N/A')}
"""
    (work_dir / "context.md").write_text(context_content, encoding="utf-8")

    # Write goal.md
    prepare_goal(arxiv_id, paper, mode, cfg)

    # Placeholder command - users plug in their own code-execution backend
    # This is a stub that exercises the wiring without invoking any external engine
    command = [
        "python",
        "-c",
        "print('autobuild stub: integrate your own code-execution back-end here')",
    ]

    # Create and start the session
    session = CodeSession(
        arxiv_id=arxiv_id,
        work_dir=work_dir,
        command=command,
        timeout_sec=1500,  # 25 minutes
    )

    pid = session.start()
    log.info("Launched autobuild session for %s (PID=%d, mode=%s)", arxiv_id, pid, mode)

    # Record the launch event in the database
    try:
        conn = get_connection(cfg.db_path)
        try:
            record_ai_event(
                conn,
                source="autobuild",
                event_type="launch",
                arxiv_id=arxiv_id,
                title=paper.get("title"),
                metadata={"mode": mode, "pid": pid},
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        log.warning("Failed to record ai_event for %s: %s", arxiv_id, e)

    return session


def poll_autobuild_sessions(cfg: Config) -> list[dict[str, Any]]:
    """Poll all autobuild sessions and return their status.

    Args:
        cfg: Config with autobuild_data_dir path.

    Returns:
        List of dicts with keys: arxiv_id, status, last_lines, return_code
    """
    results: list[dict[str, Any]] = []

    autobuild_root = cfg.autobuild_data_dir
    if not autobuild_root.exists():
        return results

    # Find all subdirectories (one per arxiv_id)
    for entry in autobuild_root.iterdir():
        if not entry.is_dir():
            continue

        arxiv_id = entry.name
        log_file = entry / "session.log"

        # Default status
        status = "running"
        return_code: int | None = None

        if log_file.exists():
            # Check if the session has completed by looking at the log
            log_text = log_file.read_text(encoding="utf-8", errors="replace")

            # Simple heuristic: if the log contains "stub" output, it's done
            # In real implementation, the subprocess would write markers
            if "stub" in log_text.lower() or "autobuild stub" in log_text.lower():
                status = "done"
                return_code = 0

            # Get last 100 lines
            lines = log_text.splitlines()
            last_lines = "\n".join(lines[-100:]) if lines else ""
        else:
            last_lines = ""

        results.append({
            "arxiv_id": arxiv_id,
            "status": status,
            "last_lines": last_lines,
            "return_code": return_code,
        })

    return results


def run_autobuild_for_picks(picks: list[dict], cfg: Config) -> int:
    """Launch autobuild sessions for a list of paper picks.

    This is the top-level entry point that the pipeline runner would call.

    Args:
        picks: List of paper dicts with arxiv_id, title, abstract, etc.
        cfg: Config object.

    Returns:
        Number of sessions launched.
    """
    if not cfg.feature_autobuild_enabled:
        log.info("AutoBuild disabled, skipping all picks")
        return 0

    launched = 0
    for paper in picks:
        arxiv_id = paper.get("arxiv_id", "")
        if not arxiv_id:
            log.warning("Skipping pick without arxiv_id")
            continue

        session = launch_autobuild(arxiv_id, paper, cfg)
        if session is not None:
            launched += 1

    log.info("AutoBuild launched %d sessions for %d picks", launched, len(picks))
    return launched
