"""Daily summary module for generating and sending daily paper summaries."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .config import Config
from . import db, notify, narrative_review

log = logging.getLogger(__name__)

# Default number of top papers to include
_DEFAULT_TOP_K = 5


def build_daily_summary(date_str: str, cfg: Config) -> dict[str, Any]:
    """Build a daily summary for the given date.

    Args:
        date_str: Date in YYYY-MM-DD format
        cfg: Config object

    Returns:
        Dict with keys: date_str, n_papers, top_papers, stats, narrative
    """
    # Parse date and create UTC range
    # Use date-only comparison - query all papers for this date
    # by matching the date part in the ISO string

    db_path = cfg.db_path
    conn = db.get_connection(db_path)
    try:
        # Query papers with deep_score for this date using date string match
        # Since papers have UTC timestamps from arxiv, we query by date prefix
        date_prefix = date_str  # e.g., "2026-09-08"
        rows = conn.execute(
            """SELECT * FROM papers
               WHERE published_at LIKE ? || '%'
               AND deep_score IS NOT NULL
               ORDER BY CASE WHEN deep_score IS NULL THEN 1 ELSE 0 END, deep_score DESC, published_at DESC""",
            (date_prefix,),
        )
        papers = [dict(row) for row in rows.fetchall()]

        # Filter to only those with deep_score
        scored_papers = [p for p in papers if p.get("deep_score") is not None]

        # Sort by deep_score DESC (already sorted by list_papers_in_range)
        scored_papers.sort(key=lambda p: (p.get("deep_score") or 0, ""), reverse=True)

        # Take top K
        top_papers = scored_papers[:_DEFAULT_TOP_K]

        # Compute aggregate stats
        all_with_abs = [p for p in papers if p.get("abs_score") is not None]
        all_with_deep = scored_papers

        stats = {
            "papers_seen": len(papers),
            "picked": len([p for p in papers if p.get("picked") == 1]),
            "avg_abs_score": (
                sum(p["abs_score"] for p in all_with_abs) / len(all_with_abs)
                if all_with_abs else 0.0
            ),
            "avg_deep_score": (
                sum(p["deep_score"] for p in all_with_deep) / len(all_with_deep)
                if all_with_deep else 0.0
            ),
            "top_categories": _compute_top_categories(scored_papers),
        }

        # Generate narrative
        narrative = narrative_review.generate_narrative(scored_papers, cfg)

        return {
            "date_str": date_str,
            "n_papers": len(scored_papers),
            "top_papers": top_papers,
            "stats": stats,
            "narrative": narrative,
        }
    finally:
        conn.close()


def _compute_top_categories(papers: list[dict]) -> list[str]:
    """Compute top categories from papers."""
    from collections import Counter

    all_cats = []
    for p in papers:
        cats = p.get("categories", "")
        if cats:
            # Categories are comma-separated
            for c in cats.split(","):
                c = c.strip()
                if c:
                    all_cats.append(c.lower())
    if not all_cats:
        return []
    # Return top 5
    counts = Counter(all_cats)
    return [cat for cat, _ in counts.most_common(5)]


def send_daily_summary(date_str: str, cfg: Config) -> bool:
    """Build and send daily summary for the given date.

    Args:
        date_str: Date in YYYY-MM-DD format
        cfg: Config object

    Returns:
        True if sent successfully, False otherwise.
    """
    if not cfg.feature_daily_summary_enabled:
        log.info("Daily summary feature disabled; skipping")
        return False

    summary = build_daily_summary(date_str, cfg)

    # Format as Markdown
    lines = []

    # Header
    lines.append(f"📊 *Daily Summary — {date_str}*")
    lines.append("")

    # Stats
    stats = summary["stats"]
    lines.append("*Stats:*")
    lines.append(f"- Papers gescort: {stats['papers_seen']}")
    lines.append(f"- Deep-gescort: {summary['n_papers']}")
    lines.append(f"- Gepickt: {stats['picked']}")
    if stats['avg_abs_score'] > 0:
        lines.append(f"- Avg abs_score: {stats['avg_abs_score']:.1f}")
    if stats['avg_deep_score'] > 0:
        lines.append(f"- Avg deep_score: {stats['avg_deep_score']:.1f}")
    if stats['top_categories']:
        lines.append(f"- Top cats: {', '.join(stats['top_categories'])}")
    lines.append("")

    # Top papers
    if summary["top_papers"]:
        lines.append("*Top Papers:*")
        for i, p in enumerate(summary["top_papers"], 1):
            title = p.get("title", "Untitled")[:50]
            arxiv_id = p.get("arxiv_id", "")
            score = p.get("deep_score", 0) or 0
            lines.append(f"{i}. {title}")
            lines.append(f"   Score: {score:.1f} | {arxiv_id}")
        lines.append("")

    # Narrative
    if summary["narrative"]:
        lines.append("*Narrative:*")
        lines.append(summary["narrative"])

    text = "\n".join(lines)

    return notify.send_daily_summary(text, date_str, cfg)


def run_daily_summary_job(cfg: Config) -> dict[str, Any]:
    """Run daily summary job for today's date.

    Args:
        cfg: Config object

    Returns:
        Result dict with date_str and success status
    """
    today = datetime.now().strftime("%Y-%m-%d")
    log.info("Running daily summary job for %s", today)

    success = send_daily_summary(today, cfg)

    return {
        "date_str": today,
        "success": success,
    }
