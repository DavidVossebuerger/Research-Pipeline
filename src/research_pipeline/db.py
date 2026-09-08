"""SQLite state store for papers, runs, and AI events."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Create a connection to the SQLite database with proper settings."""
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Initialize the database schema. Idempotent - safe to run multiple times."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS papers (
            arxiv_id       TEXT PRIMARY KEY,
            title          TEXT NOT NULL,
            authors        TEXT,
            abstract       TEXT,
            categories    TEXT,
            pdf_url        TEXT,
            published_at  TIMESTAMP,
            abs_score     REAL,
            abs_reason    TEXT,
            abs_tags      TEXT,
            deep_score    REAL,
            deep_summary  TEXT,
            deep_why      TEXT,
            deep_tags     TEXT,
            deep_analysis TEXT,
            picked        INTEGER DEFAULT 0,
            notified_at   TIMESTAMP,
            fetched_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            pdf_status    TEXT,
            pdf_reason    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_papers_abs_score ON papers(abs_score DESC);
        CREATE INDEX IF NOT EXISTS idx_papers_deep_score ON papers(deep_score DESC);
        CREATE INDEX IF NOT EXISTS idx_papers_picked ON papers(picked);

        CREATE TABLE IF NOT EXISTS runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at      TIMESTAMP NOT NULL,
            finished_at     TIMESTAMP,
            papers_seen     INTEGER DEFAULT 0,
            papers_picked   INTEGER DEFAULT 0,
            error           TEXT
        );

        CREATE TABLE IF NOT EXISTS ai_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source      TEXT,
            event_type  TEXT,
            arxiv_id    TEXT,
            title       TEXT,
            summary     TEXT,
            metadata    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ai_events_ts ON ai_events(ts DESC);
        CREATE INDEX IF NOT EXISTS idx_ai_events_source ON ai_events(source);
        CREATE INDEX IF NOT EXISTS idx_ai_events_arxiv ON ai_events(arxiv_id);
    """)


def upsert_paper(conn: sqlite3.Connection, paper: dict[str, Any]) -> None:
    """Insert or update a paper. Uses transaction for atomicity."""
    conn.execute(
        """
        INSERT INTO papers (arxiv_id, title, authors, abstract, categories, pdf_url, published_at, fetched_at)
        VALUES (:arxiv_id, :title, :authors, :abstract, :categories, :pdf_url, :published_at, :fetched_at)
        ON CONFLICT(arxiv_id) DO UPDATE SET
            title=excluded.title,
            authors=excluded.authors,
            abstract=excluded.abstract,
            categories=excluded.categories,
            pdf_url=excluded.pdf_url,
            published_at=excluded.published_at
        """,
        {
            "arxiv_id": paper["arxiv_id"],
            "title": paper["title"],
            "authors": json.dumps(paper.get("authors", [])),
            "abstract": paper.get("abstract", ""),
            "categories": ",".join(paper.get("categories", [])),
            "pdf_url": paper.get("pdf_url", ""),
            "published_at": paper.get("published_at", ""),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def get_paper(conn: sqlite3.Connection, arxiv_id: str) -> dict | None:
    """Get a paper by arxiv_id. Returns dict or None."""
    row = conn.execute(
        "SELECT * FROM papers WHERE arxiv_id = ?",
        (arxiv_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_unscored_papers(
    conn: sqlite3.Connection,
    since: datetime,
    limit: int = 100,
) -> list[dict]:
    """List papers without deep_score since the given datetime, ordered by abs_score desc."""
    rows = conn.execute(
        """SELECT * FROM papers
           WHERE deep_score IS NULL
           AND fetched_at >= ?
           ORDER BY COALESCE(abs_score, 0) DESC
           LIMIT ?""",
        (since.isoformat(), limit),
    )
    return [dict(row) for row in rows]


def list_top_deep_scored(
    conn: sqlite3.Connection,
    top_k: int,
    since: datetime,
) -> list[dict]:
    """List top-k papers with deep_score above threshold since given datetime."""
    rows = conn.execute(
        """SELECT * FROM papers
           WHERE deep_score IS NOT NULL
           AND picked = 0
           AND fetched_at >= ?
           ORDER BY deep_score DESC
           LIMIT ?""",
        (since.isoformat(), top_k),
    )
    return [dict(row) for row in rows]


def mark_picked(conn: sqlite3.Connection, arxiv_id: str) -> None:
    """Mark a paper as picked."""
    conn.execute(
        "UPDATE papers SET picked = 1, notified_at = ? WHERE arxiv_id = ?",
        (datetime.now(timezone.utc).isoformat(), arxiv_id),
    )


def start_run(conn: sqlite3.Connection) -> int:
    """Start a new run. Returns the run id."""
    cursor = conn.execute(
        "INSERT INTO runs (started_at) VALUES (?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    return cursor.lastrowid


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    papers_seen: int,
    papers_picked: int,
    error: str | None = None,
) -> None:
    """Finish a run with statistics."""
    conn.execute(
        """UPDATE runs SET finished_at = ?, papers_seen = ?, papers_picked = ?, error = ?
           WHERE id = ?""",
        (datetime.now(timezone.utc).isoformat(), papers_seen, papers_picked, error, run_id),
    )


def record_ai_event(
    conn: sqlite3.Connection,
    *,
    source: str,
    event_type: str,
    arxiv_id: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Record an AI activity event."""
    conn.execute(
        """INSERT INTO ai_events (ts, source, event_type, arxiv_id, title, summary, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            source,
            event_type,
            arxiv_id,
            title,
            summary,
            json.dumps(metadata) if metadata else None,
        ),
    )
