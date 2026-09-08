"""Tests for fetch_arxiv module."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Fixture path
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "arxiv_response.json"


class TestFetchRecent:
    """Test fetch_recent function."""

    def test_loads_fixture_when_env_set(self, monkeypatch):
        """Test that ARXIV_FIXTURE_PATH loads the fixture."""
        monkeypatch.setenv("ARXIV_FIXTURE_PATH", str(FIXTURE_PATH))

        from research_pipeline.fetch_arxiv import fetch_recent

        # Patch config to avoid needing real env vars
        from research_pipeline import config
        monkeypatch.setattr(config, "CFG", config.load_config())

        papers = fetch_recent()
        assert len(papers) >= 1
        # Check paper structure
        p = papers[0]
        assert "arxiv_id" in p
        assert "title" in p
        assert "authors" in p
        assert "abstract" in p
        assert "categories" in p
        assert "pdf_url" in p
        assert "published_at" in p

    def test_filter_by_lookback_hours(self, monkeypatch):
        """Test that lookback_hours filters out old papers."""
        monkeypatch.setenv("ARXIV_FIXTURE_PATH", str(FIXTURE_PATH))

        from research_pipeline import config
        monkeypatch.setattr(config, "CFG", config.load_config())

        from research_pipeline.fetch_arxiv import fetch_recent

        # With 26h lookback (default), should include papers from Sept 8 but not Sept 5
        papers = fetch_recent(lookback_hours=26)
        # The fixture has one paper from Sept 8 (2026-09-08T10:00:00), one from Sept 7, one from Sept 5
        # Within 26h from now (Sept 8), the Sept 8 and Sept 7 papers should be included
        arxiv_ids = [p["arxiv_id"] for p in papers]
        # 2509.01234 (Sept 8 10am) - within 26h
        # 2509.05678 (Sept 7 8pm) - that's ~38h ago, might be filtered
        # 2508.99999 (Sept 5) - definitely older than 26h

        # The Sept 5 paper should be filtered out
        assert "2508.99999" not in arxiv_ids

    def test_fetch_recent_returns_list(self, monkeypatch):
        """Test that fetch_recent returns a list."""
        monkeypatch.setenv("ARXIV_FIXTURE_PATH", str(FIXTURE_PATH))

        from research_pipeline import config
        monkeypatch.setattr(config, "CFG", config.load_config())

        from research_pipeline.fetch_arxiv import fetch_recent

        result = fetch_recent()
        assert isinstance(result, list)


class TestLoadFixture:
    """Test _load_fixture function."""

    def test_loads_all_papers(self):
        """Test loading fixture returns all papers."""
        from research_pipeline.fetch_arxiv import _load_fixture

        # Use a very large lookback to include all
        papers = _load_fixture(FIXTURE_PATH, lookback_hours=1000)
        assert len(papers) == 3

    def test_filters_by_time(self):
        """Test filtering by lookback hours."""
        from research_pipeline.fetch_arxiv import _load_fixture

        # With 20h lookback, only recent papers should be included
        papers = _load_fixture(FIXTURE_PATH, lookback_hours=20)
        # Only papers published after (now - 20h) should be included
        now = datetime.now(timezone.utc)

        for p in papers:
            pub_str = p.get("published_at", "")
            if pub_str:
                pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                # Should be within lookback window
                assert (now - pub).total_seconds() / 3600 <= 20


class TestDownloadPdf:
    """Test download_pdf function."""

    def test_skip_existing_pdf(self, monkeypatch, tmp_path):
        """Test that download skips if PDF already exists."""
        from research_pipeline.config import Config

        # Create a minimal config
        cfg = Config(
            llm_provider="ollama",
            llm_model="phi3.5",
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
            feature_autobuild_enabled=False,
            feature_telegram_bot_enabled=False,
            feature_backfill_enabled=False,
            arxiv_categories=["cs.LG"],
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

        # Create dummy PDF file
        pdf_dir = tmp_path / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        dummy_pdf = pdf_dir / "2509.01234.pdf"
        dummy_pdf.write_text("dummy pdf content")

        from research_pipeline.fetch_arxiv import download_pdf

        result = download_pdf("2509.01234", "https://arxiv.org/pdf/2509.01234.pdf", cfg)
        assert result is not None
        assert result.name == "2509.01234.pdf"
