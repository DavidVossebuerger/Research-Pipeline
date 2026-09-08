"""Arxiv fetcher using the public API."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import arxiv  # type: ignore[import-untyped]
import httpx

from research_pipeline.config import Config, load_config

log = logging.getLogger(__name__)

# Default PDF rate limit in seconds
DEFAULT_PDF_RATE_LIMIT = 3.0


def _to_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _result_to_paper(r: arxiv.Result) -> dict[str, Any]:
    return {
        "arxiv_id": r.entry_id.rsplit("/", 1)[-1],
        "title": r.title.strip().replace("\n", " "),
        "authors": [a.name for a in r.authors],
        "abstract": r.summary.strip().replace("\n", " "),
        "categories": list(r.categories or []),
        "pdf_url": r.pdf_url or "",
        "published_at": _to_iso(r.published),
    }


def fetch_recent(
    lookback_hours: int | None = None, cfg: Config | None = None
) -> list[dict[str, Any]]:
    """Fetch papers submitted in the last `lookback_hours`, filtered by configured categories.

    Set ARXIV_FIXTURE_PATH in .env to load a local JSON fixture instead of calling arXiv.
    Used for offline testing when arXiv is rate-limiting or unreachable.

    Args:
        lookback_hours: Override the default lookback window in hours.
        cfg: Optional Config object. If not provided, loads default config.

    Returns:
        List of paper dictionaries with keys: arxiv_id, title, authors, abstract,
        categories, pdf_url, published_at.
    """
    if cfg is None:
        cfg = load_config()

    fixture = os.environ.get("ARXIV_FIXTURE_PATH")
    if fixture:
        return _load_fixture(Path(fixture), lookback_hours or cfg.arxiv_lookback_hours)

    lookback = lookback_hours or cfg.arxiv_lookback_hours
    cutoff = datetime.now(UTC) - timedelta(hours=lookback)
    cutoff_str = cutoff.strftime("%Y%m%d%H%M")

    # Get rate limit from env var, default to 3.0 seconds
    rate_limit = float(os.environ.get("ARXIV_PDF_RATE_LIMIT_SEC", DEFAULT_PDF_RATE_LIMIT))

    client = arxiv.Client(
        page_size=50,
        delay_seconds=rate_limit,
        num_retries=3,
    )
    search = arxiv.Search(
        query=f"cat:({' OR '.join(cfg.arxiv_categories)}) AND submittedDate:[{cutoff_str} TO 209912312359]",
        max_results=cfg.arxiv_max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers: list[dict[str, Any]] = []
    for r in client.results(search):
        papers.append(_result_to_paper(r))

    log.info("Arxiv fetch returned %d papers since %s", len(papers), cutoff.isoformat())
    return papers


def _load_fixture(path: Path, lookback_hours: int) -> list[dict[str, Any]]:
    """Load a local JSON fixture, filter by lookback. Fixture is list of dicts."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    cutoff = datetime.now(UTC) - timedelta(hours=lookback_hours)
    out: list[dict[str, Any]] = []
    for p in raw:
        pub_str = p.get("published_at") or ""
        try:
            pub = datetime.fromisoformat(pub_str)
        except ValueError:
            out.append(p)
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=UTC)
        if pub >= cutoff:
            out.append(p)
    log.info(
        "Fixture %s: %d papers, %d within %dh window", path.name, len(raw), len(out), lookback_hours
    )
    return out


def download_pdf(arxiv_id: str, pdf_url: str, cfg: Config) -> Path | None:
    """Download a PDF by arxiv id using httpx. Returns local path or None on failure.

    Args:
        arxiv_id: The arXiv ID (e.g., "2401.12345").
        pdf_url: The PDF URL (currently unused, but kept for API compatibility).
        cfg: Config object with pdf_dir and other settings.

    Returns:
        Path to downloaded PDF, or None on failure.
    """
    dest_dir = cfg.pdf_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{arxiv_id}.pdf"

    # Skip if already exists (idempotent)
    if target.exists() and target.stat().st_size > 1000:
        log.debug("PDF already cached: %s", target)
        return target

    url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    try:
        with httpx.Client(
            timeout=60.0,
            follow_redirects=True,
            headers={"User-Agent": "research-pipeline/0.1 (arxiv-scoring)"},
        ) as client:
            r = client.get(url)
            if r.status_code == 404:
                log.warning("PDF not found (withdrawn or never existed): %s", arxiv_id)
                return None
            if r.status_code == 410:
                log.warning("PDF removed by arxiv: %s", arxiv_id)
                return None
            if r.status_code == 403:
                log.warning("PDF forbidden (access denied): %s", arxiv_id)
                return None
            r.raise_for_status()
            target.write_bytes(r.content)
        log.info("Downloaded PDF: %s (%d KB)", target.name, target.stat().st_size // 1024)
        return target
    except httpx.HTTPStatusError as e:
        log.error("Failed to download %s: HTTP %s", arxiv_id, e.response.status_code)
        return None
    except Exception as e:  # noqa: BLE001
        log.error("Failed to download %s: %s", arxiv_id, e)
        return None
    finally:
        # Rate limit to avoid overwhelming arXiv
        rate_limit = float(os.environ.get("ARXIV_PDF_RATE_LIMIT_SEC", DEFAULT_PDF_RATE_LIMIT))
        time.sleep(rate_limit)
