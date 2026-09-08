"""Tests for the daily_summary module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from research_pipeline import daily_summary, db


class MockConfig:
    """Mock config for testing."""

    db_path = None  # Will be set in fixtures
    feature_daily_summary_enabled = True
    llm_model = "test-model"
    llm_base_url = "http://localhost:11434"
    llm_api_key = ""


@pytest.fixture
def conn(tmp_path):
    """Create an in-memory SQLite database for testing."""
    db_path = tmp_path / "test.db"
    conn = db.get_connection(db_path)
    db.init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def mock_cfg(tmp_path):
    """Return a mock config object."""
    cfg = MockConfig()
    cfg.db_path = tmp_path / "test.db"
    return cfg


def _insert_paper(conn, arxiv_id, title, published_at, abs_score=None, deep_score=None, picked=0):
    """Helper to insert a paper with scores."""
    conn.execute(
        """INSERT INTO papers (arxiv_id, title, published_at, abs_score, deep_score, picked)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (arxiv_id, title, published_at, abs_score, deep_score, picked),
    )


class TestBuildDailySummary:
    def test_returns_expected_structure(self, conn, mock_cfg):
        """build_daily_summary returns expected keys in result."""
        # Insert test papers
        _insert_paper(
            conn,
            "2401.12345",
            "Test Paper 1",
            "2026-09-08T10:00:00",
            abs_score=7.5,
            deep_score=8.5,
            picked=1,
        )
        _insert_paper(
            conn,
            "2401.12346",
            "Test Paper 2",
            "2026-09-08T11:00:00",
            abs_score=6.0,
            deep_score=7.0,
            picked=0,
        )
        _insert_paper(
            conn,
            "2401.12347",
            "Test Paper 3",
            "2026-09-08T12:00:00",
            abs_score=5.0,
            deep_score=None,
            picked=0,
        )

        # Patch the connection to return our test conn
        with patch("research_pipeline.daily_summary.db.get_connection", return_value=conn):
            result = daily_summary.build_daily_summary("2026-09-08", mock_cfg)

            assert "date_str" in result
            assert "n_papers" in result
            assert "top_papers" in result
            assert "stats" in result
            assert "narrative" in result
            assert result["date_str"] == "2026-09-08"
            assert result["n_papers"] == 2  # Only papers with deep_score

    def test_filters_to_deep_scored_only(self, conn, mock_cfg):
        """build_daily_summary only includes papers with deep_score."""
        _insert_paper(
            conn, "2401.12345", "Scored Paper", "2026-09-08T10:00:00", abs_score=7.0, deep_score=8.0
        )
        _insert_paper(
            conn,
            "2401.12346",
            "Unscored Paper",
            "2026-09-08T11:00:00",
            abs_score=6.0,
            deep_score=None,
        )

        with patch("research_pipeline.daily_summary.db.get_connection", return_value=conn):
            result = daily_summary.build_daily_summary("2026-09-08", mock_cfg)

            assert result["n_papers"] == 1

    def test_computes_stats_correctly(self, conn, mock_cfg):
        """build_daily_summary computes aggregate stats."""
        _insert_paper(
            conn,
            "2401.12345",
            "Paper 1",
            "2026-09-08T10:00:00",
            abs_score=7.0,
            deep_score=8.0,
            picked=1,
        )
        _insert_paper(
            conn,
            "2401.12346",
            "Paper 2",
            "2026-09-08T11:00:00",
            abs_score=9.0,
            deep_score=9.0,
            picked=0,
        )

        with patch("research_pipeline.daily_summary.db.get_connection", return_value=conn):
            result = daily_summary.build_daily_summary("2026-09-08", mock_cfg)

            stats = result["stats"]
            assert stats["papers_seen"] == 2
            assert stats["picked"] == 1
            assert stats["avg_abs_score"] == 8.0
            assert stats["avg_deep_score"] == 8.5


class TestSendDailySummary:
    def test_calls_notify_send_daily_summary(self, conn, mock_cfg):
        """send_daily_summary calls notify.send_daily_summary with formatted text."""
        _insert_paper(
            conn, "2401.12345", "Test Paper", "2026-09-08T10:00:00", abs_score=7.0, deep_score=8.0
        )

        with (
            patch("research_pipeline.daily_summary.db.get_connection", return_value=conn),
            patch("research_pipeline.daily_summary.notify") as mock_notify,
            patch("research_pipeline.daily_summary.narrative_review") as mock_narrative,
        ):
            mock_notify.send_daily_summary.return_value = True
            mock_narrative.generate_narrative.return_value = "Test narrative"

            result = daily_summary.send_daily_summary("2026-09-08", mock_cfg)

            assert result is True
            mock_notify.send_daily_summary.assert_called_once()
            # Check that text contains expected content
            call_args = mock_notify.send_daily_summary.call_args
            text = call_args[0][0]
            assert "Daily Summary" in text

    def test_returns_false_when_feature_disabled(self, mock_cfg):
        """send_daily_summary returns False when feature is disabled."""
        mock_cfg.feature_daily_summary_enabled = False

        result = daily_summary.send_daily_summary("2026-09-08", mock_cfg)

        assert result is False

    def test_returns_false_when_notify_fails(self, conn, mock_cfg):
        """send_daily_summary returns False when notify fails."""
        _insert_paper(
            conn, "2401.12345", "Test Paper", "2026-09-08T10:00:00", abs_score=7.0, deep_score=8.0
        )

        with (
            patch("research_pipeline.daily_summary.db.get_connection", return_value=conn),
            patch("research_pipeline.daily_summary.notify") as mock_notify,
            patch("research_pipeline.daily_summary.narrative_review") as mock_narrative,
        ):
            mock_notify.send_daily_summary.return_value = False
            mock_narrative.generate_narrative.return_value = "Narrative"

            result = daily_summary.send_daily_summary("2026-09-08", mock_cfg)

            assert result is False


class TestComputeTopCategories:
    def test_extracts_categories(self):
        """_compute_top_categories extracts categories from papers."""
        papers = [
            {"categories": "cs.LG,stat.ML"},
            {"categories": "cs.LG,q-fin.TR"},
            {"categories": "stat.ML"},
        ]

        result = daily_summary._compute_top_categories(papers)

        assert "cs.lg" in result
        assert "stat.ml" in result

    def test_returns_empty_for_no_categories(self):
        """_compute_top_categories returns empty list when no categories."""
        papers = [
            {"title": "No categories"},
        ]

        result = daily_summary._compute_top_categories(papers)

        assert result == []
