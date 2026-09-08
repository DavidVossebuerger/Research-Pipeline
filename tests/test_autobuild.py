"""Tests for autobuild.py module."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from research_pipeline import autobuild
from research_pipeline.config import Config


def make_test_config(tmp_path):
    """Create a test config with autobuild enabled."""
    return Config(
        llm_provider="ollama",
        llm_model="phi3.5:3.8b",
        llm_base_url="http://localhost:11434",
        llm_api_key="",
        telegram_bot_token="",
        telegram_chat_id="",
        telegram_topic_picks="",
        telegram_topic_summary="",
        cron_daily_time="07:30",
        cron_autobuild_poll="*/5",
        feature_daily_summary_enabled=True,
        feature_weekly_digest_enabled=False,
        feature_autobuild_enabled=True,
        feature_telegram_bot_enabled=False,
        feature_backfill_enabled=False,
        arxiv_categories=["q-fin.TR"],
        arxiv_lookback_hours=26,
        arxiv_max_results=200,
        arxiv_fixture_path="",
        score_stage_a_threshold=7.0,
        score_stage_b_top_k=10,
        notify_top_k=3,
        db_path=tmp_path / "test.db",
        pdf_dir=tmp_path / "pdfs",
        log_dir=tmp_path / "logs",
        autobuild_data_dir=tmp_path / "autobuild",
    )


class TestClassifyPaperStrategy:
    """Tests for classify_paper_strategy()."""

    def test_returns_strategy_for_backtest_tag(self):
        """Test that papers with 'backtest' tag are classified as strategy."""
        paper = {"deep_tags": "backtest,trading,strategy"}
        cfg = MagicMock()
        result = autobuild.classify_paper_strategy(paper, cfg)
        assert result == "strategy"

    def test_returns_strategy_for_trading_tag(self):
        """Test that papers with 'trading' tag are classified as strategy."""
        paper = {"deep_tags": "trading,execution"}
        cfg = MagicMock()
        result = autobuild.classify_paper_strategy(paper, cfg)
        assert result == "strategy"

    def test_returns_strategy_for_alpha_tag(self):
        """Test that papers with 'alpha' tag are classified as strategy."""
        paper = {"deep_tags": "alpha,factor"}
        cfg = MagicMock()
        result = autobuild.classify_paper_strategy(paper, cfg)
        assert result == "strategy"

    def test_returns_research_for_non_strategy_tags(self):
        """Test that papers without strategy tags are classified as research."""
        paper = {"deep_tags": "machine learning,classification"}
        cfg = MagicMock()
        result = autobuild.classify_paper_strategy(paper, cfg)
        assert result == "research"

    def test_returns_research_for_empty_tags(self):
        """Test that papers with empty tags are classified as research."""
        paper = {"deep_tags": ""}
        cfg = MagicMock()
        result = autobuild.classify_paper_strategy(paper, cfg)
        assert result == "research"

    def test_returns_research_for_missing_tags(self):
        """Test that papers without deep_tags field are classified as research."""
        paper = {"title": "Test Paper"}
        cfg = MagicMock()
        result = autobuild.classify_paper_strategy(paper, cfg)
        assert result == "research"

    def test_handles_list_format_tags(self):
        """Test that tags in list format are handled correctly."""
        paper = {"deep_tags": ["backtest", "trading"]}
        cfg = MagicMock()
        result = autobuild.classify_paper_strategy(paper, cfg)
        assert result == "strategy"


class TestPrepareGoal:
    """Tests for prepare_goal()."""

    def test_writes_strategy_goal(self, tmp_path):
        """Test that prepare_goal writes correct goal.md for strategy mode."""
        cfg = make_test_config(tmp_path)
        paper = {
            "title": "Test Paper Title",
            "abstract": "Test abstract",
            "deep_summary": "Test summary",
        }
        goal_file = autobuild.prepare_goal("1234.56789", paper, "strategy", cfg)

        assert goal_file.exists()
        content = goal_file.read_text()
        assert "backtest" in content.lower()
        assert "backtest.py" in content

    def test_writes_research_goal(self, tmp_path):
        """Test that prepare_goal writes correct goal.md for research mode."""
        cfg = make_test_config(tmp_path)
        paper = {
            "title": "Test Paper Title",
            "abstract": "Test abstract",
            "deep_summary": "Test summary",
        }
        goal_file = autobuild.prepare_goal("1234.56789", paper, "research", cfg)

        assert goal_file.exists()
        content = goal_file.read_text()
        assert "German" in content
        assert "article.md" in content

    def test_creates_work_directory(self, tmp_path):
        """Test that prepare_goal creates the work directory."""
        cfg = make_test_config(tmp_path)
        paper = {"title": "Test"}
        goal_file = autobuild.prepare_goal("1234.56789", paper, "research", cfg)

        assert goal_file.parent.exists()
        assert goal_file.parent.is_dir()


class TestLaunchAutobuild:
    """Tests for launch_autobuild()."""

    def test_returns_none_when_disabled(self, tmp_path):
        """Test that launch_autobuild returns None when feature is disabled."""
        # Create a config with feature_autobuild_enabled=False directly
        cfg = Config(
            llm_provider="ollama",
            llm_model="phi3.5:3.8b",
            llm_base_url="http://localhost:11434",
            llm_api_key="",
            telegram_bot_token="",
            telegram_chat_id="",
            telegram_topic_picks="",
            telegram_topic_summary="",
            cron_daily_time="07:30",
            cron_autobuild_poll="*/5",
            feature_daily_summary_enabled=True,
            feature_weekly_digest_enabled=False,
            feature_autobuild_enabled=False,  # Disabled!
            feature_telegram_bot_enabled=False,
            feature_backfill_enabled=False,
            arxiv_categories=["q-fin.TR"],
            arxiv_lookback_hours=26,
            arxiv_max_results=200,
            arxiv_fixture_path="",
            score_stage_a_threshold=7.0,
            score_stage_b_top_k=10,
            notify_top_k=3,
            db_path=tmp_path / "test.db",
            pdf_dir=tmp_path / "pdfs",
            log_dir=tmp_path / "logs",
            autobuild_data_dir=tmp_path / "autobuild",
        )

        paper = {"arxiv_id": "1234.56789", "title": "Test"}
        result = autobuild.launch_autobuild("1234.56789", paper, cfg)

        assert result is None

    @patch("research_pipeline.autobuild.get_connection")
    def test_writes_context_and_goal_when_enabled(self, mock_get_conn, tmp_path):
        """Test that context.md and goal.md are written when autobuild is enabled."""
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        cfg = make_test_config(tmp_path)
        paper = {
            "arxiv_id": "1234.56789",
            "title": "Test Paper",
            "abstract": "Test abstract",
            "deep_summary": "Test summary",
        }
        result = autobuild.launch_autobuild("1234.56789", paper, cfg)

        # Should return a CodeSession
        assert result is not None

        # Check context.md was written
        context_file = cfg.autobuild_data_dir / "1234.56789" / "context.md"
        assert context_file.exists()
        content = context_file.read_text()
        assert "Test Paper" in content

        # Check goal.md was written
        goal_file = cfg.autobuild_data_dir / "1234.56789" / "goal.md"
        assert goal_file.exists()

    @patch("research_pipeline.autobuild.get_connection")
    def test_records_ai_event(self, mock_get_conn, tmp_path):
        """Test that launch_autobuild records an AI event."""
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        cfg = make_test_config(tmp_path)
        paper = {
            "arxiv_id": "1234.56789",
            "title": "Test Paper",
            "abstract": "Test abstract",
            "deep_summary": "Test summary",
        }
        result = autobuild.launch_autobuild("1234.56789", paper, cfg)

        # Verify record_ai_event was called
        mock_conn.execute.assert_called()
        mock_conn.commit.assert_called()


class TestPollAutobuildSessions:
    """Tests for poll_autobuild_sessions()."""

    def test_returns_empty_list_when_no_dirs(self, tmp_path):
        """Test that poll returns empty list when no sessions exist."""
        cfg = make_test_config(tmp_path)
        result = autobuild.poll_autobuild_sessions(cfg)
        assert result == []

    def test_reports_session_status(self, tmp_path):
        """Test that poll reports session status correctly."""
        cfg = make_test_config(tmp_path)

        # Create a mock session directory with a log file
        session_dir = cfg.autobuild_data_dir / "1234.56789"
        session_dir.mkdir(parents=True)
        log_file = session_dir / "session.log"
        log_file.write_text("autobuild stub: test output")

        result = autobuild.poll_autobuild_sessions(cfg)

        assert len(result) == 1
        assert result[0]["arxiv_id"] == "1234.56789"
        assert "last_lines" in result[0]


class TestRunAutobuildForPicks:
    """Tests for run_autobuild_for_picks()."""

    def test_returns_zero_when_disabled(self, tmp_path):
        """Test that run_autobuild_for_picks returns 0 when feature is disabled."""
        # Create a config with feature_autobuild_enabled=False directly
        cfg = Config(
            llm_provider="ollama",
            llm_model="phi3.5:3.8b",
            llm_base_url="http://localhost:11434",
            llm_api_key="",
            telegram_bot_token="",
            telegram_chat_id="",
            telegram_topic_picks="",
            telegram_topic_summary="",
            cron_daily_time="07:30",
            cron_autobuild_poll="*/5",
            feature_daily_summary_enabled=True,
            feature_weekly_digest_enabled=False,
            feature_autobuild_enabled=False,  # Disabled!
            feature_telegram_bot_enabled=False,
            feature_backfill_enabled=False,
            arxiv_categories=["q-fin.TR"],
            arxiv_lookback_hours=26,
            arxiv_max_results=200,
            arxiv_fixture_path="",
            score_stage_a_threshold=7.0,
            score_stage_b_top_k=10,
            notify_top_k=3,
            db_path=tmp_path / "test.db",
            pdf_dir=tmp_path / "pdfs",
            log_dir=tmp_path / "logs",
            autobuild_data_dir=tmp_path / "autobuild",
        )

        picks = [{"arxiv_id": "1234.56789", "title": "Test"}]
        result = autobuild.run_autobuild_for_picks(picks, cfg)

        assert result == 0

    @patch("research_pipeline.autobuild.get_connection")
    def test_launches_session_for_each_pick(self, mock_get_conn, tmp_path):
        """Test that run_autobuild_for_picks launches a session for each pick."""
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn

        cfg = make_test_config(tmp_path)
        picks = [
            {"arxiv_id": "1234.56789", "title": "Test 1", "abstract": "", "deep_summary": ""},
            {"arxiv_id": "2345.67890", "title": "Test 2", "abstract": "", "deep_summary": ""},
        ]
        result = autobuild.run_autobuild_for_picks(picks, cfg)

        assert result == 2

    def test_skips_picks_without_arxiv_id(self, tmp_path):
        """Test that picks without arxiv_id are skipped."""
        cfg = make_test_config(tmp_path)
        picks = [
            {"title": "Test without ID"},  # No arxiv_id
        ]
        result = autobuild.run_autobuild_for_picks(picks, cfg)

        assert result == 0
