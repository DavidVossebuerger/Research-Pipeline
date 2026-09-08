"""Weekly digest module for generating and sending weekly paper digests."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from . import db, narrative_review, notify
from .config import Config

log = logging.getLogger(__name__)

# Default limits
_TOP_PER_DAY = 3
_TOP_PER_WEEK = 7


def _iso_week_to_dates(week_str: str) -> tuple[str, str]:
    """Convert ISO week string (YYYY-WXX) to Monday and Sunday date strings.

    Args:
        week_str: ISO week string like "2026-W36"

    Returns:
        Tuple of (monday_str, sunday_str) as YYYY-MM-DD strings
    """
    # Parse YYYY-WXX format
    year, week = week_str.split("-W")
    year = int(year)
    week_num = int(week)

    # Use isocalendar: find the first Thursday of the ISO year, then go back to Monday
    # January 4 is always in ISO week 1
    jan4 = datetime(year, 1, 4)  # noqa: DTZ001
    # Thursday is 3 days after Monday (weekday() returns 0=Monday, 6=Sunday)
    # Find the Thursday of week 1
    thursday_of_week1 = jan4 + timedelta(days=(3 - jan4.weekday()) % 7)
    # Monday of week 1 is 3 days before Thursday of week 1
    monday_of_week1 = thursday_of_week1 - timedelta(days=3)
    # Find Monday of the target week
    monday = monday_of_week1 + timedelta(weeks=week_num - 1)
    sunday = monday + timedelta(days=6)

    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def build_weekly_digest(week_str: str, cfg: Config) -> dict[str, Any]:
    """Build a weekly digest for the given ISO week.

    Args:
        week_str: ISO week string like "2026-W36"
        cfg: Config object

    Returns:
        Dict with keys: week_str, days, top_tags, narrative
    """
    monday_str, sunday_str = _iso_week_to_dates(week_str)

    db_path = cfg.db_path
    conn = db.get_connection(db_path)
    try:
        # Query all papers in the week with deep_score
        # Use date prefix matching for each day in the range
        rows = conn.execute(
            """SELECT * FROM papers
               WHERE published_at >= ? AND published_at < ?
               AND deep_score IS NOT NULL
               ORDER BY CASE WHEN deep_score IS NULL THEN 1 ELSE 0 END, deep_score DESC, published_at DESC""",
            (monday_str, sunday_str + "T23:59:59"),
        )
        papers = [dict(row) for row in rows.fetchall()]

        # All papers from query already have deep_score (filtered in SQL)
        scored_papers = papers

        # Group by day
        days: dict[str, list[dict]] = {}
        for p in papers:
            pub_at = p.get("published_at", "")
            if pub_at:
                try:
                    # Parse date from ISO string
                    pub_date = datetime.fromisoformat(pub_at)
                    date_str = pub_date.strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    date_str = "unknown"
            else:
                date_str = "unknown"

            if date_str not in days:
                days[date_str] = []
            days[date_str].append(p)

        # Sort each day by deep_score DESC
        for date_str, papers_list in days.items():
            papers_list.sort(key=lambda p: (p.get("deep_score") or 0, ""), reverse=True)
            # Take top K per day and update the dictionary
            days[date_str] = papers_list[:_TOP_PER_DAY]

        # Compute top tags across all scored papers
        top_tags = _compute_top_tags(scored_papers)

        # Get top papers for the week
        all_sorted = sorted(
            scored_papers, key=lambda p: (p.get("deep_score") or 0, ""), reverse=True
        )
        top_week_papers = all_sorted[:_TOP_PER_WEEK]

        # Generate weekly narrative
        narrative = narrative_review.generate_weekly_narrative(days, cfg)

        return {
            "week_str": week_str,
            "days": days,
            "top_tags": top_tags,
            "top_week_papers": top_week_papers,
            "narrative": narrative,
        }
    finally:
        conn.close()


def _compute_top_tags(papers: list[dict]) -> list[str]:
    """Compute top tags from papers using tag intersection heuristic."""
    from collections import Counter

    all_tags = []
    for p in papers:
        # Try deep_tags first, then abs_tags, then categories
        tags = p.get("deep_tags") or p.get("abs_tags") or p.get("categories", "")
        if isinstance(tags, str) and tags:
            for t in tags.split(","):
                t = t.strip().lower()
                if t:
                    all_tags.append(t)
        elif isinstance(tags, list):
            for t in tags:
                t = str(t).strip().lower()
                if t:
                    all_tags.append(t)

    if not all_tags:
        return []

    counts = Counter(all_tags)
    return [tag for tag, _ in counts.most_common(5)]


def send_weekly_digest(week_str: str, cfg: Config) -> bool:
    """Build and send weekly digest for the given ISO week.

    Args:
        week_str: ISO week string like "2026-W36"
        cfg: Config object

    Returns:
        True if sent successfully, False otherwise.
    """
    if not cfg.feature_weekly_digest_enabled:
        log.info("Weekly digest feature disabled; skipping")
        return False

    digest = build_weekly_digest(week_str, cfg)

    # Format as Markdown
    lines = []

    # Header
    lines.append(f"📅 *Weekly Digest — {week_str}*")
    lines.append("")

    # Top tags
    if digest["top_tags"]:
        lines.append("*Top Themes:* " + ", ".join(f"`{t}`" for t in digest["top_tags"]))
        lines.append("")

    # Daily sections
    for date_str in sorted(digest["days"].keys()):
        papers = digest["days"][date_str]
        if not papers:
            continue
        lines.append(f"### {date_str}")
        for i, p in enumerate(papers, 1):
            title = p.get("title", "Untitled")[:55]
            arxiv_id = p.get("arxiv_id", "")
            score = p.get("deep_score") or 0
            lines.append(f"{i}. {title}")
            lines.append(f"   Score: {score:.1f} | {arxiv_id}")
        lines.append("")

    # Weekly narrative
    if digest["narrative"]:
        lines.append("*Weekly Narrative:*")
        lines.append(digest["narrative"])

    text = "\n".join(lines)

    # Use telegram_topic_summary if available
    topic = cfg.telegram_topic_summary if cfg.telegram_topic_summary else None

    return notify.send_raw(text, cfg, topic=topic)


def run_weekly_digest_job(cfg: Config) -> dict[str, Any]:
    """Run weekly digest job for the current ISO week.

    Args:
        cfg: Config object

    Returns:
        Result dict with week_str and success status
    """
    today = datetime.now(UTC)
    week_str = today.strftime("%Y-W%V")
    log.info("Running weekly digest job for %s", week_str)

    success = send_weekly_digest(week_str, cfg)

    return {
        "week_str": week_str,
        "success": success,
    }
