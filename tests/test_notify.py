"""Tests for notify.py — Telegram-only notifications."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Mock httpx before importing the module under test
import research_pipeline.notify as notify_module


class TestSendTopPicks:
    """Tests for send_top_picks function."""

    def test_builds_correct_url_and_payload(self, monkeypatch):
        """Test that send_top_picks builds correct URL and payload."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"

        with patch.object(notify_module.httpx, "post", return_value=mock_response) as mock_post:
            # Create a minimal config
            cfg = MagicMock()
            cfg.telegram_bot_token = "12345:ABCDE"
            cfg.telegram_chat_id = "999"
            cfg.telegram_topic_picks = ""
            cfg.telegram_topic_summary = ""

            picks = [
                {
                    "title": "Test Paper",
                    "deep_score": 8.5,
                    "categories": "cs.LG",
                    "deep_summary": "This is a test summary.",
                    "arxiv_id": "2401.12345",
                }
            ]

            result = notify_module.send_top_picks(picks, "2024-01-15", cfg)

            assert result is True
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            url = call_args[0][0]
            payload = call_args[1]["json"]

            assert url == "https://api.telegram.org/bot12345:ABCDE/sendMessage"
            assert payload["chat_id"] == "999"
            assert payload["parse_mode"] == "Markdown"
            assert payload["disable_web_page_preview"] is True
            assert "Test Paper" in payload["text"]

    def test_includes_message_thread_id_when_topic_set(self, monkeypatch):
        """Test that message_thread_id is included when topic is set."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"

        with patch.object(notify_module.httpx, "post", return_value=mock_response) as mock_post:
            cfg = MagicMock()
            cfg.telegram_bot_token = "12345:ABCDE"
            cfg.telegram_chat_id = "999"
            cfg.telegram_topic_picks = "42"
            cfg.telegram_topic_summary = ""

            picks = [{"title": "Test", "deep_score": 8.5, "arxiv_id": "2401.12345"}]

            result = notify_module.send_top_picks(picks, "2024-01-15", cfg)

            assert result is True
            payload = mock_post.call_args[1]["json"]
            assert payload["message_thread_id"] == "42"

    def test_returns_false_and_logs_warning_when_token_missing(self, monkeypatch):
        """Test that missing bot token returns False and logs warning."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(notify_module.httpx, "post", return_value=mock_response) as mock_post:
            cfg = MagicMock()
            cfg.telegram_bot_token = ""
            cfg.telegram_chat_id = "999"
            cfg.telegram_topic_picks = ""
            cfg.telegram_topic_summary = ""

            picks = [{"title": "Test", "deep_score": 8.5}]

            result = notify_module.send_top_picks(picks, "2024-01-15", cfg)

            assert result is False
            mock_post.assert_not_called()

    def test_returns_false_when_chat_id_missing(self, monkeypatch):
        """Test that missing chat_id returns False."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(notify_module.httpx, "post", return_value=mock_response) as mock_post:
            cfg = MagicMock()
            cfg.telegram_bot_token = "12345:ABCDE"
            cfg.telegram_chat_id = ""
            cfg.telegram_topic_picks = ""
            cfg.telegram_topic_summary = ""

            picks = [{"title": "Test", "deep_score": 8.5}]

            result = notify_module.send_top_picks(picks, "2024-01-15", cfg)

            assert result is False
            mock_post.assert_not_called()

    def test_retries_plain_text_on_markdown_parse_error(self, monkeypatch):
        """Test retry as plain text when 400 with parse error."""
        mock_response_400 = MagicMock()
        mock_response_400.status_code = 400
        mock_response_400.text = "can't parse Markdown"

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.text = "ok"

        with patch.object(
            notify_module.httpx, "post", side_effect=[mock_response_400, mock_response_200]
        ) as mock_post:
            cfg = MagicMock()
            cfg.telegram_bot_token = "12345:ABCDE"
            cfg.telegram_chat_id = "999"
            cfg.telegram_topic_picks = ""
            cfg.telegram_topic_summary = ""

            picks = [{"title": "Test", "deep_score": 8.5, "arxiv_id": "2401.12345"}]

            result = notify_module.send_top_picks(picks, "2024-01-15", cfg)

            assert result is True
            assert mock_post.call_count == 2
            # Second call should not have parse_mode
            second_payload = mock_post.call_args[1]["json"]
            assert "parse_mode" not in second_payload

    def test_returns_false_on_500_with_error_logged(self, monkeypatch):
        """Test that 500 returns False and logs error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(notify_module.httpx, "post", return_value=mock_response) as mock_post:
            cfg = MagicMock()
            cfg.telegram_bot_token = "12345:ABCDE"
            cfg.telegram_chat_id = "999"
            cfg.telegram_topic_picks = ""
            cfg.telegram_topic_summary = ""

            picks = [{"title": "Test", "deep_score": 8.5}]

            result = notify_module.send_top_picks(picks, "2024-01-15", cfg)

            assert result is False
            mock_post.assert_called_once()


class TestSendDailySummary:
    """Tests for send_daily_summary function."""

    def test_builds_correct_url_and_payload(self, monkeypatch):
        """Test that send_daily_summary builds correct payload."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"

        with patch.object(notify_module.httpx, "post", return_value=mock_response) as mock_post:
            cfg = MagicMock()
            cfg.telegram_bot_token = "12345:ABCDE"
            cfg.telegram_chat_id = "999"
            cfg.telegram_topic_picks = ""
            cfg.telegram_topic_summary = ""

            text = "This is a daily summary."

            result = notify_module.send_daily_summary(text, "2024-01-15", cfg)

            assert result is True
            payload = mock_post.call_args[1]["json"]

            assert payload["chat_id"] == "999"
            assert payload["parse_mode"] == "Markdown"
            assert payload["disable_web_page_preview"] is True
            assert "2024-01-15" in payload["text"]
            assert "daily summary" in payload["text"]

    def test_includes_message_thread_id_when_summary_topic_set(self, monkeypatch):
        """Test that summary topic is used when set."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"

        with patch.object(notify_module.httpx, "post", return_value=mock_response) as mock_post:
            cfg = MagicMock()
            cfg.telegram_bot_token = "12345:ABCDE"
            cfg.telegram_chat_id = "999"
            cfg.telegram_topic_picks = ""
            cfg.telegram_topic_summary = "55"

            result = notify_module.send_daily_summary("summary text", "2024-01-15", cfg)

            assert result is True
            payload = mock_post.call_args[1]["json"]
            assert payload["message_thread_id"] == "55"

    def test_returns_false_when_token_missing(self, monkeypatch):
        """Test that missing token returns False."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(notify_module.httpx, "post", return_value=mock_response) as mock_post:
            cfg = MagicMock()
            cfg.telegram_bot_token = ""
            cfg.telegram_chat_id = "999"
            cfg.telegram_topic_picks = ""
            cfg.telegram_topic_summary = ""

            result = notify_module.send_daily_summary("text", "2024-01-15", cfg)

            assert result is False
            mock_post.assert_not_called()

    def test_returns_false_when_chat_id_missing(self, monkeypatch):
        """Test that missing chat_id returns False."""
        cfg = MagicMock()
        cfg.telegram_bot_token = "12345:ABCDE"
        cfg.telegram_chat_id = ""
        cfg.telegram_topic_picks = ""
        cfg.telegram_topic_summary = ""

        result = notify_module.send_daily_summary("text", "2024-01-15", cfg)

        assert result is False

    def test_retries_plain_text_on_parse_error(self, monkeypatch):
        """Test retry on markdown parse error."""
        mock_response_400 = MagicMock()
        mock_response_400.status_code = 400
        mock_response_400.text = "can't parse"

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200

        with patch.object(
            notify_module.httpx, "post", side_effect=[mock_response_400, mock_response_200]
        ):
            cfg = MagicMock()
            cfg.telegram_bot_token = "12345:ABCDE"
            cfg.telegram_chat_id = "999"
            cfg.telegram_topic_picks = ""
            cfg.telegram_topic_summary = ""

            result = notify_module.send_daily_summary("text", "2024-01-15", cfg)

            assert result is True

    def test_returns_false_on_500(self, monkeypatch):
        """Test that 500 returns False."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "error"

        with patch.object(notify_module.httpx, "post", return_value=mock_response):
            cfg = MagicMock()
            cfg.telegram_bot_token = "12345:ABCDE"
            cfg.telegram_chat_id = "999"
            cfg.telegram_topic_picks = ""
            cfg.telegram_topic_summary = ""

            result = notify_module.send_daily_summary("text", "2024-01-15", cfg)

            assert result is False


class TestSendRaw:
    """Tests for send_raw function (back-compat helper)."""

    def test_is_thin_wrapper(self, monkeypatch):
        """Test that send_raw is a thin wrapper around _send_telegram_message."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"

        with patch.object(notify_module.httpx, "post", return_value=mock_response) as mock_post:
            cfg = MagicMock()
            cfg.telegram_bot_token = "12345:ABCDE"
            cfg.telegram_chat_id = "999"
            cfg.telegram_topic_picks = "10"
            cfg.telegram_topic_summary = "20"

            result = notify_module.send_raw("Hello world", cfg)

            assert result is True
            payload = mock_post.call_args[1]["json"]
            assert payload["text"] == "Hello world"
            # Default to picks topic
            assert payload["message_thread_id"] == "10"

    def test_uses_explicit_topic_when_provided(self, monkeypatch):
        """Test that explicit topic parameter overrides defaults."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"

        with patch.object(notify_module.httpx, "post", return_value=mock_response) as mock_post:
            cfg = MagicMock()
            cfg.telegram_bot_token = "12345:ABCDE"
            cfg.telegram_chat_id = "999"
            cfg.telegram_topic_picks = "10"
            cfg.telegram_topic_summary = "20"

            result = notify_module.send_raw("Hello", cfg, topic="30")

            assert result is True
            payload = mock_post.call_args[1]["json"]
            assert payload["message_thread_id"] == "30"

    def test_returns_false_when_not_configured(self, monkeypatch):
        """Test that send_raw returns False when not configured."""
        cfg = MagicMock()
        cfg.telegram_bot_token = ""
        cfg.telegram_chat_id = "999"
        cfg.telegram_topic_picks = ""
        cfg.telegram_topic_summary = ""

        result = notify_module.send_raw("Hello", cfg)

        assert result is False
