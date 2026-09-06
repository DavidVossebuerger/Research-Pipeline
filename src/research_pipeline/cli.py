"""Thin CLI entry point for research-pipeline command."""
from __future__ import annotations

import json

import click

from research_pipeline.config import load_config
from research_pipeline.logging_setup import setup_logging
from research_pipeline.runtime import runner


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Research Pipeline - Run and manage the paper scoring pipeline."""


@cli.command()
@click.option("--dry-run", is_flag=True, help="Don't send notifications")
@click.option("--lookback", "lookback_hours", type=int, help="Look back N hours")
@click.option("--max", "max_papers", type=int, help="Max papers to fetch")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def run(dry_run: bool, lookback_hours: int | None, max_papers: int | None, json_output: bool):
    """Trigger a single pipeline run."""
    # Ensure config is loaded
    cfg = load_config()
    logger = setup_logging("research_pipeline")

    result = runner.run_pipeline(
        dry_run=dry_run,
        lookback_hours=lookback_hours,
        max_papers=max_papers,
    )

    if json_output:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Pipeline run complete: {result['papers_seen']} seen, {result['papers_picked']} picked")
        if result["errors"]:
            click.echo(f"Errors: {result['errors']}")


def main():
    """Entry point for research-pipeline command."""
    cli()


if __name__ == "__main__":
    main()
