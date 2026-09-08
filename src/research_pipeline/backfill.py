"""Backfill CLI for re-scoring historical papers.

Provides three subcommands:
- stage-a: Re-score abstracts for papers from the last N days
- stage-b: Re-score deep (PDF) for borderline papers
- notify: Send picks for the last N days (idempotent via db.mark_picked)
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

import click

from .config import load_config
from .db import (
    get_connection,
    init_schema,
    migrate_add_deep_score_updated_at,
    set_abstract_score,
    update_deep_score,
    list_papers_for_stage_a,
    list_papers_for_stage_b,
    list_unnotified_papers,
    mark_picked,
)
from . import score
from . import notify
from . import fetch_arxiv

log = logging.getLogger(__name__)

MAX_WORKERS = 4


@click.group()
def cli():
    """Backfill historical papers (re-fetch, re-score, re-notify)."""
    pass


@cli.command("stage-a")
@click.option("--days", default=7, type=int, help="Look back N days")
@click.option("--limit", default=50, type=int, help="Max papers to process")
@click.option("--dry-run", is_flag=True, help="Skip scoring, just show what would be processed")
def stage_a(days: int, limit: int, dry_run: bool):
    """Re-score abstracts for papers from the last N days."""
    cfg = load_config()
    conn = get_connection(cfg.db_path)
    init_schema(conn)
    migrate_add_deep_score_updated_at(conn)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    papers = list_papers_for_stage_a(conn, cutoff, limit)

    if not papers:
        click.echo("No papers found to re-score.")
        return

    click.echo(f"Found {len(papers)} papers to re-score (stage-a, days={days}, limit={limit})")

    if dry_run:
        for p in papers:
            click.echo(f"  [DRY-RUN] Would score: {p['arxiv_id']} - {p['title'][:50]}")
        click.echo(f"[DRY-RUN] Skipped {len(papers)} papers.")
        return

    scored = 0
    failed = 0

    def score_one(paper: dict) -> tuple[str, bool, dict | None]:
        arxiv_id = paper["arxiv_id"]
        try:
            result = score.score_abstract(paper, cfg=cfg)
            return (arxiv_id, True, result)
        except Exception as e:
            log.warning("Failed to score %s: %s", arxiv_id, e)
            return (arxiv_id, False, None)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(score_one, p): p for p in papers}
        for future in as_completed(futures):
            arxiv_id, success, result = future.result()
            if success and result:
                set_abstract_score(conn, arxiv_id, result["score"], result["reason"], result["tags"])
                scored += 1
            else:
                failed += 1
            click.echo(f"  Scored {arxiv_id}: score={result.get('score', 'N/A') if result else 'FAILED'}")

    conn.commit()
    conn.close()

    click.echo(f"\nStage-a complete: {scored} scored, {failed} failed")


@cli.command("stage-b")
@click.option("--days", default=7, type=int, help="Look back N days")
@click.option("--threshold", default=6.0, type=float, help="Minimum abstract score to deep-score")
@click.option("--limit", default=20, type=int, help="Max papers to process")
@click.option("--dry-run", is_flag=True, help="Skip PDF download and scoring")
def stage_b(days: int, threshold: float, limit: int, dry_run: bool):
    """Re-score deep (PDF) for borderline papers."""
    cfg = load_config()
    conn = get_connection(cfg.db_path)
    init_schema(conn)
    migrate_add_deep_score_updated_at(conn)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    papers = list_papers_for_stage_b(conn, cutoff, threshold, limit)

    if not papers:
        click.echo("No papers found for deep scoring (stage-b).")
        return

    click.echo(f"Found {len(papers)} papers to deep-score (days={days}, threshold={threshold}, limit={limit})")

    if dry_run:
        for p in papers:
            click.echo(f"  [DRY-RUN] Would deep-score: {p['arxiv_id']} - {p['title'][:50]}")
        click.echo(f"[DRY-RUN] Skipped {len(papers)} papers.")
        return

    scored = 0
    failed = 0
    skipped_no_pdf = 0

    def deep_score_one(paper: dict) -> tuple[str, bool, bool, dict | None]:
        arxiv_id = paper["arxiv_id"]
        pdf_url = paper.get("pdf_url", "")

        # Download PDF if needed
        pdf_path = fetch_arxiv.download_pdf(arxiv_id, pdf_url, cfg)
        if not pdf_path:
            log.warning("No PDF for %s, skipping deep-score", arxiv_id)
            return (arxiv_id, False, True, None)

        try:
            from . import pdf_extract
            pdf_text = pdf_extract.extract_text(pdf_path)
            if not pdf_text:
                return (arxiv_id, False, False, None)
            result = score.score_deep(paper, pdf_text, cfg=cfg)
            return (arxiv_id, True, False, result)
        except Exception as e:
            log.warning("Failed to deep-score %s: %s", arxiv_id, e)
            return (arxiv_id, False, False, None)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(deep_score_one, p): p for p in papers}
        for future in as_completed(futures):
            arxiv_id, success, no_pdf, result = future.result()
            if no_pdf:
                skipped_no_pdf += 1
                click.echo(f"  Skipped {arxiv_id}: no PDF")
            elif success and result:
                update_deep_score(conn, arxiv_id, result)
                scored += 1
                click.echo(f"  Deep-scored {arxiv_id}: score={result.get('overall_score', 'N/A')}")
            else:
                failed += 1
                click.echo(f"  Failed {arxiv_id}")

    conn.commit()
    conn.close()

    click.echo(f"\nStage-b complete: {scored} scored, {failed} failed, {skipped_no_pdf} skipped (no PDF)")


@cli.command("notify")
@click.option("--days", default=3, type=int, help="Look back N days")
@click.option("--dry-run", is_flag=True, help="Skip sending Telegram messages")
def notify_cmd(days: int, dry_run: bool):
    """Send picks for the last N days (idempotent via db.mark_picked)."""
    cfg = load_config()
    conn = get_connection(cfg.db_path)
    init_schema(conn)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    papers = list_unnotified_papers(conn, cutoff, limit=cfg.notify_top_k)

    if not papers:
        click.echo("No papers to notify about.")
        return

    click.echo(f"Found {len(papers)} papers to notify (days={days})")

    # Format for notify.send_top_picks
    picks = []
    for p in papers:
        pick = {
            "arxiv_id": p["arxiv_id"],
            "title": p["title"],
            "deep_score": p.get("deep_score"),
            "abs_score": p.get("abs_score"),
            "categories": p.get("categories", ""),
            "deep_summary": p.get("deep_summary"),
            "abs_reason": p.get("abs_reason"),
        }
        picks.append(pick)

    if dry_run:
        for p in picks:
            click.echo(f"  [DRY-RUN] Would notify: {p['arxiv_id']} - {p['title'][:50]}")
        click.echo(f"[DRY-RUN] Skipped sending {len(picks)} notifications.")
        return

    # Send notifications
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    success = notify.send_top_picks(picks, date_str, cfg)

    if success:
        # Mark as picked
        for p in papers:
            mark_picked(conn, p["arxiv_id"])
        click.echo(f"\nNotified {len(picks)} papers successfully.")
    else:
        click.echo("\nNotification sending failed (check Telegram config).")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    cli()
