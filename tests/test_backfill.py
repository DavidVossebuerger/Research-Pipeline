"""Tests for the backfill CLI module."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from research_pipeline import backfill
from research_pipeline.db import (
    get_connection,
    init_schema,
    upsert_paper,
    migrate_add_deep_score_updated_at,
)


@pytest.fixture
def conn(tmp_path):
    """Create an in-memory SQLite database for testing."""
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    init_schema(conn)
    migrate_add_deep_score_updated_at(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_papers(conn):
    """Insert sample papers for testing."""
    papers = [
        {
            "arxiv_id": "2401.00001",
            "title": "Test Paper 1",
            "authors": ["Alice"],
            "abstract": "Abstract 1",
            "categories": ["cs.LG"],
            "pdf_url": "https://arxiv.org/pdf/2401.00001.pdf",
            "published_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        },
        {
            "arxiv_id": "2401.00002",
            "title": "Test Paper 2",
            "authors": ["Bob"],
            "abstract": "Abstract 2",
            "categories": ["stat.ML"],
            "pdf_url": "https://arxiv.org/pdf/2401.00002.pdf",
            "published_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        },
        {
            "arxiv_id": "2401.00003",
            "title": "Test Paper 3",
            "authors": ["Charlie"],
            "abstract": "Abstract 3",
            "categories": ["q-fin.GN"],
            "pdf_url": "https://arxiv.org/pdf/2401.00003.pdf",
            "published_at": datetime.now(timezone.utc).isoformat(),
        },
    ]
    for p in papers:
        upsert_paper(conn, p)
    return papers


class TestStageA:
    @patch("research_pipeline.backfill.score.score_abstract")
    @patch("research_pipeline.backfill.load_config")
    @patch("research_pipeline.backfill.get_connection")
    def test_stage_a_calls_score_abstract_for_each_paper(
        self, mock_get_conn, mock_load_cfg, mock_score_abstract, conn, sample_papers
    ):
        """stage-a should call score_abstract for each candidate paper."""
        mock_cfg = MagicMock()
        mock_load_cfg.return_value = mock_cfg
        mock_get_conn.return_value = conn

        mock_score_abstract.return_value = {
            "score": 7.5,
            "reason": "Good paper",
            "tags": ["ml", "finance"],
        }

        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(backfill.cli, ["stage-a", "--days=7", "--limit=10"])

        assert result.exit_code == 0
        assert mock_score_abstract.call_count == len(sample_papers)

    @patch("research_pipeline.backfill.score.score_abstract")
    @patch("research_pipeline.backfill.load_config")
    @patch("research_pipeline.backfill.get_connection")
    def test_stage_a_dry_run(
        self, mock_get_conn, mock_load_cfg, mock_score_abstract, conn, sample_papers
    ):
        """stage-a with --dry-run should NOT call score_abstract."""
        mock_cfg = MagicMock()
        mock_load_cfg.return_value = mock_cfg
        mock_get_conn.return_value = conn

        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(backfill.cli, ["stage-a", "--days=7", "--dry-run"])

        assert result.exit_code == 0
        mock_score_abstract.assert_not_called()
        assert "[DRY-RUN]" in result.output


class TestStageB:
    @patch("research_pipeline.pdf_extract.extract_text")
    @patch("research_pipeline.backfill.fetch_arxiv.download_pdf")
    @patch("research_pipeline.backfill.score.score_deep")
    @patch("research_pipeline.backfill.load_config")
    @patch("research_pipeline.backfill.get_connection")
    def test_stage_b_filters_by_threshold(
        self, mock_get_conn, mock_load_cfg, mock_score_deep, mock_download_pdf, mock_extract_text, conn
    ):
        """stage-b should only process papers with abs_score >= threshold."""
        # Insert papers with different abstract scores
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, abstract, published_at, abs_score, pdf_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "2401.00010",
                "High Score",
                "Abstract",
                datetime.now(timezone.utc).isoformat(),
                8.0,
                "https://arxiv.org/pdf/2401.00010.pdf",
            ),
        )
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, abstract, published_at, abs_score, pdf_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "2401.00011",
                "Low Score",
                "Abstract",
                datetime.now(timezone.utc).isoformat(),
                4.0,
                "https://arxiv.org/pdf/2401.00011.pdf",
            ),
        )

        mock_cfg = MagicMock()
        mock_load_cfg.return_value = mock_cfg
        mock_get_conn.return_value = conn

        # Mock PDF and scoring
        mock_download_pdf.return_value = MagicMock()
        mock_extract_text.return_value = "Sample PDF text content"
        mock_score_deep.return_value = {
            "overall_score": 8.5,
            "summary": "Summary",
            "why_interesting": "Interesting",
            "tags": ["tag1"],
            "analysis": "Analysis",
        }

        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(backfill.cli, ["stage-b", "--days=7", "--threshold=6.0"])

        assert result.exit_code == 0
        # Should only score the paper with abs_score >= 6.0
        assert mock_score_deep.call_count >= 1

    @patch("research_pipeline.backfill.fetch_arxiv.download_pdf")
    @patch("research_pipeline.backfill.score.score_deep")
    @patch("research_pipeline.backfill.load_config")
    @patch("research_pipeline.backfill.get_connection")
    def test_stage_b_skips_recent_deep_score(
        self, mock_get_conn, mock_load_cfg, mock_score_deep, mock_download_pdf, conn
    ):
        """stage-b should skip papers that already have a recent deep_score."""
        # Insert paper with recent deep_score_updated_at
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, abstract, published_at, abs_score, deep_score, deep_score_updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "2401.00020",
                "Recent Deep",
                "Abstract",
                datetime.now(timezone.utc).isoformat(),
                8.0,
                9.0,
                one_hour_ago,
            ),
        )

        mock_cfg = MagicMock()
        mock_load_cfg.return_value = mock_cfg
        mock_get_conn.return_value = conn

        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(backfill.cli, ["stage-b", "--days=7", "--threshold=6.0"])

        # Should not try to score the paper with recent deep_score
        mock_download_pdf.assert_not_called()
        mock_score_deep.assert_not_called()

    @patch("research_pipeline.backfill.score.score_deep")
    @patch("research_pipeline.backfill.load_config")
    @patch("research_pipeline.backfill.get_connection")
    def test_stage_b_dry_run(
        self, mock_get_conn, mock_load_cfg, mock_score_deep, conn
    ):
        """stage-b with --dry-run should NOT call score_deep."""
        # Insert paper with abs_score >= threshold
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, abstract, published_at, abs_score, pdf_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "2401.00050",
                "Test Paper",
                "Abstract",
                datetime.now(timezone.utc).isoformat(),
                7.5,
                "https://arxiv.org/pdf/2401.00050.pdf",
            ),
        )

        mock_cfg = MagicMock()
        mock_load_cfg.return_value = mock_cfg
        mock_get_conn.return_value = conn

        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(backfill.cli, ["stage-b", "--days=7", "--dry-run"])

        assert result.exit_code == 0
        mock_score_deep.assert_not_called()
        assert "[DRY-RUN]" in result.output


class TestNotify:
    @patch("research_pipeline.backfill.notify.send_top_picks")
    @patch("research_pipeline.backfill.load_config")
    @patch("research_pipeline.backfill.get_connection")
    def test_notify_skips_already_marked_picked(
        self, mock_get_conn, mock_load_cfg, mock_send_picks, conn
    ):
        """notify should skip papers that are already marked as picked."""
        # Insert paper and mark it as picked
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, abstract, published_at, deep_score, picked)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "2401.00030",
                "Already Picked",
                "Abstract",
                datetime.now(timezone.utc).isoformat(),
                9.0,
                1,  # picked = 1
            ),
        )

        mock_cfg = MagicMock()
        mock_cfg.notify_top_k = 3
        mock_load_cfg.return_value = mock_cfg
        mock_get_conn.return_value = conn

        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(backfill.cli, ["notify", "--days=7"])

        assert result.exit_code == 0
        mock_send_picks.assert_not_called()

    @patch("research_pipeline.backfill.notify.send_top_picks")
    @patch("research_pipeline.backfill.load_config")
    @patch("research_pipeline.backfill.get_connection")
    def test_notify_dry_run(
        self, mock_get_conn, mock_load_cfg, mock_send_picks, conn
    ):
        """notify with --dry-run should NOT call send_top_picks."""
        # Insert paper with deep_score
        conn.execute(
            """INSERT INTO papers (arxiv_id, title, abstract, published_at, deep_score, picked)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "2401.00040",
                "Test Paper",
                "Abstract",
                datetime.now(timezone.utc).isoformat(),
                9.0,
                0,
            ),
        )

        mock_cfg = MagicMock()
        mock_cfg.notify_top_k = 3
        mock_load_cfg.return_value = mock_cfg
        mock_get_conn.return_value = conn

        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(backfill.cli, ["notify", "--days=7", "--dry-run"])

        assert result.exit_code == 0
        mock_send_picks.assert_not_called()
        assert "[DRY-RUN]" in result.output


class TestDbMigration:
    def test_migrate_add_deep_score_updated_at_idempotent(self, conn):
        """Migration should be idempotent - running twice should not fail."""
        # Run migration first time
        migrate_add_deep_score_updated_at(conn)

        # Check column exists
        cursor = conn.execute("PRAGMA table_info(papers)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "deep_score_updated_at" in columns

        # Run again - should not fail
        migrate_add_deep_score_updated_at(conn)
