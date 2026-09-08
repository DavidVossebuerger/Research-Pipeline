"""Tests for the weekly_digest module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from research_pipeline import db, weekly_digest


class MockConfig:
    """Mock config for testing."""

    db_path = None  # Will be set in fixtures
    feature_weekly_digest_enabled = True
    telegram_topic_summary = "summary-topic"
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


def _insert_paper(conn, arxiv_id, title, published_at, abs_score=None, deep_score=None):
    """Helper to insert a paper with scores."""
    conn.execute(
        """INSERT INTO papers (arxiv_id, title, published_at, abs_score, deep_score)
           VALUES (?, ?, ?, ?, ?)""",
        (arxiv_id, title, published_at, abs_score, deep_score),
    )


class TestIsoWeekToDates:
    def test_parses_iso_week(self):
        """_iso_week_to_dates correctly parses ISO week string."""
        monday_str, sunday_str = weekly_digest._iso_week_to_dates("2026-W36")

        # W36 2026 should start on Monday Sept 7, 2026
        assert monday_str == "2026-09-07"
        assert sunday_str == "2026-09-13"


class TestBuildWeeklyDigest:
    def test_returns_expected_structure(self, conn, mock_cfg):
        """build_weekly_digest returns expected keys in result."""
        # Insert papers across multiple days
        _insert_paper(conn, "2401.12345", "Paper 1", "2026-09-07T10:00:00", deep_score=8.0)
        _insert_paper(conn, "2401.12346", "Paper 2", "2026-09-07T11:00:00", deep_score=7.0)
        _insert_paper(conn, "2401.12347", "Paper 3", "2026-09-08T10:00:00", deep_score=9.0)

        with patch("research_pipeline.weekly_digest.db.get_connection", return_value=conn):
            result = weekly_digest.build_weekly_digest("2026-W36", mock_cfg)

            assert "week_str" in result
            assert "days" in result
            assert "top_tags" in result
            assert "narrative" in result
            assert result["week_str"] == "2026-W36"

    def test_groups_by_day(self, conn, mock_cfg):
        """build_weekly_digest groups papers by day."""
        _insert_paper(conn, "2401.12345", "Monday Paper", "2026-09-07T10:00:00", deep_score=8.0)
        _insert_paper(conn, "2401.12346", "Tuesday Paper", "2026-09-08T10:00:00", deep_score=9.0)

        with patch("research_pipeline.weekly_digest.db.get_connection", return_value=conn):
            result = weekly_digest.build_weekly_digest("2026-W36", mock_cfg)

            assert "2026-09-07" in result["days"]
            assert "2026-09-08" in result["days"]
            assert len(result["days"]["2026-09-07"]) == 1
            assert len(result["days"]["2026-09-08"]) == 1

    def test_filters_to_deep_scored_only(self, conn, mock_cfg):
        """build_weekly_digest only includes papers with deep_score."""
        _insert_paper(conn, "2401.12345", "Scored", "2026-09-07T10:00:00", deep_score=8.0)
        _insert_paper(conn, "2401.12346", "Unscored", "2026-09-07T11:00:00", deep_score=None)

        with patch("research_pipeline.weekly_digest.db.get_connection", return_value=conn):
            result = weekly_digest.build_weekly_digest("2026-W36", mock_cfg)

            # Only scored paper should be included
            assert len(result["days"]["2026-09-07"]) == 1


class TestSendWeeklyDigest:
    def test_calls_notify_send_raw(self, conn, mock_cfg):
        """send_weekly_digest calls notify.send_raw with formatted text."""
        _insert_paper(conn, "2401.12345", "Test Paper", "2026-09-07T10:00:00", deep_score=8.0)

        with (
            patch("research_pipeline.weekly_digest.db.get_connection", return_value=conn),
            patch("research_pipeline.weekly_digest.notify") as mock_notify,
            patch("research_pipeline.weekly_digest.narrative_review") as mock_narrative,
        ):
            mock_notify.send_raw.return_value = True
            mock_narrative.generate_weekly_narrative.return_value = "Weekly narrative"

            result = weekly_digest.send_weekly_digest("2026-W36", mock_cfg)

            assert result is True
            mock_notify.send_raw.assert_called_once()
            # Check that text contains expected content
            call_args = mock_notify.send_raw.call_args
            text = call_args[0][0]
            assert "Weekly Digest" in text

    def test_returns_false_when_feature_disabled(self, mock_cfg):
        """send_weekly_digest returns False when feature is disabled."""
        mock_cfg.feature_weekly_digest_enabled = False

        result = weekly_digest.send_weekly_digest("2026-W36", mock_cfg)

        assert result is False

    def test_uses_telegram_topic(self, conn, mock_cfg):
        """send_weekly_digest passes telegram_topic_summary to notify."""
        _insert_paper(conn, "2401.12345", "Test Paper", "2026-09-07T10:00:00", deep_score=8.0)

        with (
            patch("research_pipeline.weekly_digest.db.get_connection", return_value=conn),
            patch("research_pipeline.weekly_digest.notify") as mock_notify,
            patch("research_pipeline.weekly_digest.narrative_review") as mock_narrative,
        ):
            mock_notify.send_raw.return_value = True
            mock_narrative.generate_weekly_narrative.return_value = "Narrative"

            weekly_digest.send_weekly_digest("2026-W36", mock_cfg)

            call_args = mock_notify.send_raw.call_args
            topic = call_args[1]["topic"]
            assert topic == "summary-topic"


class TestComputeTopTags:
    def test_extracts_tags_from_deep_tags(self):
        """_compute_top_tags extracts from deep_tags."""
        papers = [
            {"deep_tags": "ml,finance"},
            {"deep_tags": "ml,trading"},
        ]

        result = weekly_digest._compute_top_tags(papers)

        assert "ml" in result

    def test_falls_back_to_categories(self):
        """_compute_top_tags falls back to categories if no deep_tags."""
        papers = [
            {"categories": "cs.LG,stat.ML"},
            {"categories": "cs.LG,q-fin.TR"},
        ]

        result = weekly_digest._compute_top_tags(papers)

        assert "cs.lg" in result
