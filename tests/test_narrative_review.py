"""Tests for the narrative_review module."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from research_pipeline import narrative_review
from research_pipeline.config import Config


class MockConfig:
    """Mock config for testing."""
    llm_model = "test-model"
    llm_base_url = "http://localhost:11434"
    llm_api_key = ""


@pytest.fixture
def mock_cfg():
    """Return a mock config object."""
    return MockConfig()


class TestGenerateNarrative:
    def test_returns_mocked_string_on_success(self, mock_cfg):
        """generate_narrative returns the mocked LLM response."""
        papers = [
            {
                "arxiv_id": "2401.12345",
                "title": "Test Paper 1",
                "deep_tags": "machine learning, finance",
                "deep_summary": "This is a test summary for paper 1.",
            },
            {
                "arxiv_id": "2401.12346",
                "title": "Test Paper 2",
                "deep_tags": "reinforcement learning",
                "deep_summary": "This is a test summary for paper 2.",
            },
        ]

        expected_response = "Diese Papers zeigen interessante Trends in der Forschung."

        with patch("research_pipeline.narrative_review.score._chat") as mock_chat:
            mock_chat.return_value = expected_response

            result = narrative_review.generate_narrative(papers, mock_cfg)

            assert result == expected_response
            mock_chat.assert_called_once()

    def test_returns_empty_string_on_error(self, mock_cfg):
        """generate_narrative returns empty string when LLM fails."""
        papers = [
            {
                "arxiv_id": "2401.12345",
                "title": "Test Paper",
                "deep_tags": "ml",
                "deep_summary": "Summary",
            },
        ]

        with patch("research_pipeline.narrative_review.score._chat") as mock_chat:
            mock_chat.side_effect = Exception("API error")

            result = narrative_review.generate_narrative(papers, mock_cfg)

            assert result == ""

    def test_handles_empty_papers_list(self, mock_cfg):
        """generate_narrative returns empty string for empty list."""
        result = narrative_review.generate_narrative([], mock_cfg)
        assert result == ""


class TestGenerateWeeklyNarrative:
    def test_returns_mocked_string_on_success(self, mock_cfg):
        """generate_weekly_narrative returns the mocked LLM response."""
        papers_by_day = {
            "2026-09-01": [
                {
                    "arxiv_id": "2401.12345",
                    "title": "Paper 1",
                },
            ],
            "2026-09-02": [
                {
                    "arxiv_id": "2401.12346",
                    "title": "Paper 2",
                },
            ],
        }

        expected_response = "Eine erfolgreiche Woche mit interessanten Papers."

        with patch("research_pipeline.narrative_review.score._chat") as mock_chat:
            mock_chat.return_value = expected_response

            result = narrative_review.generate_weekly_narrative(papers_by_day, mock_cfg)

            assert result == expected_response

    def test_returns_empty_string_on_error(self, mock_cfg):
        """generate_weekly_narrative returns empty string when LLM fails."""
        papers_by_day = {
            "2026-09-01": [
                {
                    "arxiv_id": "2401.12345",
                    "title": "Paper 1",
                },
            ],
        }

        with patch("research_pipeline.narrative_review.score._chat") as mock_chat:
            mock_chat.side_effect = Exception("API error")

            result = narrative_review.generate_weekly_narrative(papers_by_day, mock_cfg)

            assert result == ""

    def test_handles_empty_papers_by_day(self, mock_cfg):
        """generate_weekly_narrative returns empty string for empty dict."""
        result = narrative_review.generate_weekly_narrative({}, mock_cfg)
        assert result == ""

    def test_handles_empty_day_lists(self, mock_cfg):
        """generate_weekly_narrative handles days with empty paper lists."""
        papers_by_day = {
            "2026-09-01": [],
            "2026-09-02": [
                {"arxiv_id": "2401.12346", "title": "Paper 2"},
            ],
        }

        with patch("research_pipeline.narrative_review.score._chat") as mock_chat:
            mock_chat.return_value = "Narrative"

            result = narrative_review.generate_weekly_narrative(papers_by_day, mock_cfg)

            # Should call the LLM (empty days are filtered)
            assert mock_chat.called
