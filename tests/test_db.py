"""Tests for the database module."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest
import sqlite3

from research_pipeline.db import (
    get_connection,
    init_schema,
    upsert_paper,
    get_paper,
    list_unscored_papers,
    list_top_deep_scored,
    mark_picked,
    start_run,
    finish_run,
    record_ai_event,
)


@pytest.fixture
def conn(tmp_path):
    """Create an in-memory SQLite database for testing."""
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    init_schema(conn)
    yield conn
    conn.close()


class TestSchemaInit:
    def test_schema_init_idempotent(self, conn):
        """Schema init should be idempotent - running twice should not fail."""
        # Run init_schema again - should not raise
        init_schema(conn)
        # Verify tables exist
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "papers" in table_names
        assert "runs" in table_names
        assert "ai_events" in table_names


class TestPaperOperations:
    def test_upsert_and_get_roundtrip(self, conn):
        """upsert_paper then get_paper should return the same data."""
        paper = {
            "arxiv_id": "2401.12345",
            "title": "Test Paper",
            "authors": ["Alice Smith", "Bob Jones"],
            "abstract": "This is a test abstract.",
            "categories": ["cs.LG", "stat.ML"],
            "pdf_url": "https://arxiv.org/pdf/2401.12345.pdf",
            "published_at": "2024-01-15T10:00:00Z",
        }
        upsert_paper(conn, paper)

        result = get_paper(conn, "2401.12345")
        assert result is not None
        assert result["arxiv_id"] == "2401.12345"
        assert result["title"] == "Test Paper"
        # Authors stored as JSON string
        assert json.loads(result["authors"]) == ["Alice Smith", "Bob Jones"]
        assert result["abstract"] == "This is a test abstract."
        assert result["categories"] == "cs.LG,stat.ML"
        assert result["pdf_status"] is None
        assert result["picked"] == 0

    def test_upsert_updates_existing(self, conn):
        """upsert_paper should update an existing paper."""
        paper = {
            "arxiv_id": "2401.12345",
            "title": "Original Title",
            "authors": ["Author"],
            "abstract": "Original",
            "categories": ["cs.LG"],
            "pdf_url": "",
            "published_at": "2024-01-01",
        }
        upsert_paper(conn, paper)

        # Update with new title
        paper["title"] = "Updated Title"
        upsert_paper(conn, paper)

        result = get_paper(conn, "2401.12345")
        assert result["title"] == "Updated Title"


class TestListUnscoredPapers:
    def test_filters_deep_score_null(self, conn):
        """Should only return papers where deep_score is NULL."""
        # Insert paper with no deep_score
        paper = {
            "arxiv_id": "2401.00001",
            "title": "Paper 1",
            "authors": [],
            "abstract": "",
            "categories": [],
            "pdf_url": "",
            "published_at": "2024-01-01",
        }
        upsert_paper(conn, paper)

        # Insert paper with deep_score set
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, deep_score)
               VALUES (?, ?, ?)""",
            ("2401.00002", "Paper 2", 8.5),
        )

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = list_unscored_papers(conn, since, limit=10)

        assert len(results) == 1
        assert results[0]["arxiv_id"] == "2401.00001"

    def test_orders_by_abs_score(self, conn):
        """Should order by abs_score DESC."""
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, abs_score, deep_score)
               VALUES (?, ?, ?, NULL)""",
            ("2401.00001", "Low Score", 3.0),
        )
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, abs_score, deep_score)
               VALUES (?, ?, ?, NULL)""",
            ("2401.00002", "High Score", 8.0),
        )

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = list_unscored_papers(conn, since, limit=10)

        assert len(results) == 2
        assert results[0]["arxiv_id"] == "2401.00002"
        assert results[1]["arxiv_id"] == "2401.00001"


class TestListTopDeepScored:
    def test_filters_picked_zero(self, conn):
        """Should only return papers where picked = 0."""
        # Insert picked paper
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, deep_score, picked)
               VALUES (?, ?, ?, 1)""",
            ("2401.00001", "Picked Paper", 9.0),
        )
        # Insert unpicked paper
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, deep_score, picked)
               VALUES (?, ?, ?, 0)""",
            ("2401.00002", "Unpicked Paper", 8.0),
        )

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = list_top_deep_scored(conn, top_k=10, since=since)

        assert len(results) == 1
        assert results[0]["arxiv_id"] == "2401.00002"

    def test_orders_by_deep_score_desc(self, conn):
        """Should order by deep_score DESC."""
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, deep_score, picked)
               VALUES (?, ?, ?, 0)""",
            ("2401.00001", "Low Deep", 5.0),
        )
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, deep_score, picked)
               VALUES (?, ?, ?, 0)""",
            ("2401.00002", "High Deep", 9.0),
        )

        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        results = list_top_deep_scored(conn, top_k=10, since=since)

        assert len(results) == 2
        assert results[0]["arxiv_id"] == "2401.00002"
        assert results[1]["arxiv_id"] == "2401.00001"


class TestMarkPicked:
    def test_sets_picked_and_notified_at(self, conn):
        """mark_picked should set picked=1 and notified_at timestamp."""
        paper = {
            "arxiv_id": "2401.12345",
            "title": "Test",
            "authors": [],
            "abstract": "",
            "categories": [],
            "pdf_url": "",
            "published_at": "2024-01-01",
        }
        upsert_paper(conn, paper)

        mark_picked(conn, "2401.12345")

        result = get_paper(conn, "2401.12345")
        assert result["picked"] == 1
        assert result["notified_at"] is not None


class TestRunOperations:
    def test_start_run_returns_id(self, conn):
        """start_run should return a run id."""
        run_id = start_run(conn)
        assert run_id == 1

    def test_finish_run_updates_row(self, conn):
        """finish_run should update the run with stats."""
        run_id = start_run(conn)
        finish_run(conn, run_id, papers_seen=100, papers_picked=5, error=None)

        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row["papers_seen"] == 100
        assert row["papers_picked"] == 5
        assert row["error"] is None
        assert row["finished_at"] is not None

    def test_finish_run_with_error(self, conn):
        """finish_run should store error message."""
        run_id = start_run(conn)
        finish_run(conn, run_id, papers_seen=10, papers_picked=0, error="Network error")

        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row["error"] == "Network error"


class TestAiEvents:
    def test_record_ai_event_persists_metadata(self, conn):
        """record_ai_event should store metadata as JSON."""
        record_ai_event(
            conn,
            source="test",
            event_type="scoring",
            arxiv_id="2401.12345",
            title="Test Paper",
            summary="Scored 8.5",
            metadata={"model": "phi3.5", "latency_ms": 1500},
        )

        row = conn.execute("SELECT * FROM ai_events").fetchone()
        assert row["source"] == "test"
        assert row["event_type"] == "scoring"
        assert row["arxiv_id"] == "2401.12345"
        assert row["title"] == "Test Paper"
        assert row["summary"] == "Scored 8.5"
        metadata = json.loads(row["metadata"])
        assert metadata["model"] == "phi3.5"
        assert metadata["latency_ms"] == 1500
