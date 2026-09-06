"""Pipeline runner stub — full implementation in upcoming PRs."""
from __future__ import annotations

from research_pipeline.logging_setup import setup_logging

logger = setup_logging("research_pipeline")


def run_pipeline(
    *,
    dry_run: bool = False,
    lookback_hours: int | None = None,
    max_papers: int | None = None,
) -> dict:
    """
    Run the full research pipeline.

    This is a stub — full implementation lands in PRs #3-#7.

    Args:
        dry_run: If True, don't actually send notifications
        lookback_hours: Override default lookback window
        max_papers: Override default max papers to fetch

    Returns:
        dict with keys: papers_seen, papers_picked, errors
    """
    logger.info("Pipeline stub — full implementation lands in upcoming PRs")

    if dry_run:
        logger.info("Running in dry-run mode")

    if lookback_hours:
        logger.info(f"Lookback window: {lookback_hours} hours")

    if max_papers:
        logger.info(f"Max papers: {max_papers}")

    # Stub return
    return {"papers_seen": 0, "papers_picked": 0, "errors": []}
