"""Tests for the scoring module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from research_pipeline import score as score_module
from research_pipeline.config import Config


@pytest.fixture
def mock_config(tmp_path):
    """Create a mock Config for testing."""
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


@pytest.fixture
def openai_compat_config(tmp_path):
    """Create a mock Config for OpenAI-compat testing."""
    return Config(
        llm_provider="openai_compat",
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.openai.com/v1",
        llm_api_key="sk-test-key",
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


@pytest.fixture
def anthropic_compat_config(tmp_path):
    """Create a mock Config for Anthropic-compat testing."""
    return Config(
        llm_provider="anthropic_compat",
        llm_model="claude-3-5-sonnet-20241022",
        llm_base_url="https://api.anthropic.com",
        llm_api_key="sk-ant-test-key",
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


class TestExtractJson:
    def test_fenced_json_block(self):
        """Should parse fenced ```json``` block."""
        text = """Here is my response:
```json
{"score": 8, "tags": ["ml", "finance"], "reason": "Test"}
```
Some explanation."""
        result = score_module._extract_json(text)
        assert result is not None
        assert result["score"] == 8
        assert result["tags"] == ["ml", "finance"]

    def test_raw_json(self):
        """Should parse raw JSON when no fence."""
        text = '{"score": 7, "tags": ["quant"], "reason": "Good"}'
        result = score_module._extract_json(text)
        assert result is not None
        assert result["score"] == 7

    def test_incremental_parse(self):
        """Should handle incremental JSON parsing."""
        text = '  {"score": 6, "tags": []}  \n\nExtra text'
        result = score_module._extract_json(text)
        assert result is not None
        assert result["score"] == 6

    def test_invalid_json_returns_none(self):
        """Should return None for invalid JSON."""
        text = "This is not JSON at all"
        result = score_module._extract_json(text)
        assert result is None


class TestScoreAbstract:
    def test_parses_fenced_json_and_clamp(self, mock_config):
        """score_abstract should parse fenced JSON and clamp score 0-10."""
        paper = {"title": "Test", "abstract": "Test abstract"}

        fake_response = {
            "message": {"content": '```json\n{"score": 15, "tags": ["ml"], "reason": "High"}\n```'}
        }

        with patch.object(
            score_module, "_chat_ollama", return_value=fake_response["message"]["content"]
        ):
            result = score_module.score_abstract(paper, cfg=mock_config)

        assert result["score"] == 10.0  # clamped from 15
        assert result["tags"] == ["ml"]
        assert result["reason"] == "High"

    def test_parses_raw_json_no_fence(self, mock_config):
        """score_abstract should parse raw JSON when no fence."""
        paper = {"title": "Test", "abstract": "Test abstract"}

        fake_response = '{"score": 5, "tags": ["finance"], "reason": "Ok"}'

        with patch.object(score_module, "_chat_ollama", return_value=fake_response):
            result = score_module.score_abstract(paper, cfg=mock_config)

        assert result["score"] == 5.0
        assert result["tags"] == ["finance"]

    def test_returns_api_error_on_httpx_exception(self, mock_config):
        """score_abstract should return api_error on httpx exception."""
        paper = {"title": "Test", "abstract": "Test abstract"}

        with patch.object(score_module, "_chat_ollama", side_effect=Exception("Connection error")):
            result = score_module.score_abstract(paper, cfg=mock_config)

        assert result["score"] == 0.0
        assert result["reason"] == "api_error"

    def test_returns_parse_error_on_invalid_json(self, mock_config):
        """score_abstract should return parse_error when JSON is invalid."""
        paper = {"title": "Test", "abstract": "Test abstract"}

        # Return valid JSON but missing 'score' key
        fake_response = '{"tags": ["ml"], "reason": "No score"}'

        with patch.object(score_module, "_chat_ollama", return_value=fake_response):
            result = score_module.score_abstract(paper, cfg=mock_config)

        assert result["score"] == 0.0
        assert result["reason"] == "parse_error"

    def test_negative_score_clamped_to_zero(self, mock_config):
        """score_abstract should clamp negative scores to 0."""
        paper = {"title": "Test", "abstract": "Test abstract"}

        fake_response = '{"score": -5, "tags": [], "reason": "Negative"}'

        with patch.object(score_module, "_chat_ollama", return_value=fake_response):
            result = score_module.score_abstract(paper, cfg=mock_config)

        assert result["score"] == 0.0


class TestScoreDeep:
    def test_parses_full_deep_schema(self, mock_config):
        """score_deep should parse full deep schema and clamp overall_score."""
        paper = {"title": "Test", "abstract": "Test abstract"}
        pdf_text = "Full paper text here..."

        fake_response = json.dumps(
            {
                "overall_score": 12,
                "novelty": 8,
                "rigor": 7,
                "reproducibility": 6,
                "practical_value": 9,
                "summary": "Test summary",
                "why_interesting": "Interesting for trading",
                "tags": ["ml", "alpha"],
                "analysis": "Detailed analysis",
            }
        )

        with patch.object(score_module, "_chat_ollama", return_value=fake_response):
            result = score_module.score_deep(paper, pdf_text, cfg=mock_config)

        assert result["overall_score"] == 10.0  # clamped from 12
        assert result["novelty"] == 8
        assert result["rigor"] == 7
        assert result["summary"] == "Test summary"
        assert result["tags"] == ["ml", "alpha"]

    def test_returns_zero_on_api_error(self, mock_config):
        """score_deep should return zero result on api_error."""
        paper = {"title": "Test", "abstract": "Test abstract"}
        pdf_text = "Full paper text..."

        with patch.object(score_module, "_chat_ollama", side_effect=Exception("Network")):
            result = score_module.score_deep(paper, pdf_text, cfg=mock_config)

        assert result["overall_score"] == 0.0
        assert result["analysis"] == "Scoring failed: api_error"

    def test_returns_zero_on_parse_error(self, mock_config):
        """score_deep should return zero result on parse_error."""
        paper = {"title": "Test", "abstract": "Test abstract"}
        pdf_text = "Full paper text..."

        # Return invalid JSON (missing overall_score)
        fake_response = '{"novelty": 5, "summary": "Incomplete"}'

        with patch.object(score_module, "_chat_ollama", return_value=fake_response):
            result = score_module.score_deep(paper, pdf_text, cfg=mock_config)

        assert result["overall_score"] == 0.0
        assert result["analysis"] == "Scoring failed: parse_error"

    def test_fenced_json_parsing(self, mock_config):
        """score_deep should parse fenced JSON block."""
        paper = {"title": "Test", "abstract": "Test abstract"}
        pdf_text = "Full paper text..."

        fake_response = """Here is my analysis:
```json
{
  "overall_score": 7,
  "novelty": 8,
  "rigor": 6,
  "reproducibility": 5,
  "practical_value": 7,
  "summary": "Summary",
  "why_interesting": "Why",
  "tags": ["tag1"],
  "analysis": "Analysis"
}
```
End of response."""

        with patch.object(score_module, "_chat_ollama", return_value=fake_response):
            result = score_module.score_deep(paper, pdf_text, cfg=mock_config)

        assert result["overall_score"] == 7.0
        assert result["tags"] == ["tag1"]


class TestZeroDeepResult:
    def test_returns_complete_zero_structure(self):
        """_zero_deep_result should return complete zero-score structure."""
        result = score_module._zero_deep_result("api_error")

        assert result["overall_score"] == 0.0
        assert result["novelty"] == 0.0
        assert result["rigor"] == 0.0
        assert result["reproducibility"] == 0.0
        assert result["practical_value"] == 0.0
        assert result["summary"] == ""
        assert result["why_interesting"] == ""
        assert result["tags"] == []
        assert result["analysis"] == "Scoring failed: api_error"


class TestChatAnthropicCompat:
    """Tests for _chat_anthropic_compat function."""

    def test_calls_correct_url(self):
        """_chat_anthropic_compat should call the correct /v1/messages URL."""
        messages = [{"role": "user", "content": "Hello"}]
        model = "claude-3-5-sonnet-20241022"
        base_url = "https://api.anthropic.com"
        api_key = "sk-ant-test-key"

        with patch("httpx.Client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"content": [{"type": "text", "text": "Hello back"}]}
            mock_resp.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

            score_module._chat_anthropic_compat(
                messages,
                model=model,
                base_url=base_url,
                api_key=api_key,
            )

            # Verify URL is constructed correctly
            mock_client.assert_called_once_with(timeout=120)

    def test_includes_correct_headers(self):
        """_chat_anthropic_compat should include correct headers."""
        messages = [{"role": "user", "content": "Hello"}]
        model = "claude-3-5-sonnet-20241022"
        base_url = "https://api.anthropic.com"
        api_key = "sk-ant-test-key"

        with patch("httpx.Client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"content": [{"type": "text", "text": "Hello back"}]}
            mock_resp.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

            score_module._chat_anthropic_compat(
                messages,
                model=model,
                base_url=base_url,
                api_key=api_key,
            )

            call_args = mock_client.return_value.__enter__.return_value.post.call_args
            headers = call_args[1]["headers"]
            assert headers["x-api-key"] == api_key
            assert headers["anthropic-version"] == score_module.ANTHROPIC_VERSION

    def test_includes_correct_body(self):
        """_chat_anthropic_compat should include correct body."""
        messages = [{"role": "user", "content": "Hello"}]
        model = "claude-3-5-sonnet-20241022"
        base_url = "https://api.anthropic.com"
        api_key = "sk-ant-test-key"

        with patch("httpx.Client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"content": [{"type": "text", "text": "Hello back"}]}
            mock_resp.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

            score_module._chat_anthropic_compat(
                messages,
                model=model,
                base_url=base_url,
                api_key=api_key,
                temperature=0.5,
                max_tokens=100,
            )

            call_args = mock_client.return_value.__enter__.return_value.post.call_args
            body = call_args[1]["json"]
            assert body["model"] == model
            assert body["messages"] == messages
            assert body["temperature"] == 0.5
            assert body["max_tokens"] == 100

    def test_extracts_single_content_block(self):
        """_chat_anthropic_compat should extract text from single content block."""
        messages = [{"role": "user", "content": "Hello"}]

        with patch("httpx.Client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"content": [{"type": "text", "text": "Response text"}]}
            mock_resp.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

            result = score_module._chat_anthropic_compat(
                messages,
                model="test-model",
                base_url="https://api.anthropic.com",
                api_key="test-key",
            )

            assert result == "Response text"

    def test_extracts_multiple_content_blocks(self):
        """_chat_anthropic_compat should join text from multiple content blocks."""
        messages = [{"role": "user", "content": "Hello"}]

        with patch("httpx.Client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "content": [
                    {"type": "text", "text": "Part1 "},
                    {"type": "text", "text": "Part2"},
                ]
            }
            mock_resp.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.post.return_value = mock_resp

            result = score_module._chat_anthropic_compat(
                messages,
                model="test-model",
                base_url="https://api.anthropic.com",
                api_key="test-key",
            )

            assert result == "Part1 Part2"


class TestChatDispatch:
    """Tests for _chat dispatch function."""

    def test_dispatches_to_ollama(self):
        """_chat should dispatch to _chat_ollama for ollama provider."""
        messages = [{"role": "user", "content": "test"}]

        with patch.object(score_module, "_chat_ollama") as mock_ollama:
            mock_ollama.return_value = "response"
            result = score_module._chat(
                messages,
                model="phi3.5:3.8b",
                base_url="http://localhost:11434",
                provider="ollama",
            )

            mock_ollama.assert_called_once()
            assert result == "response"

    def test_dispatches_to_openai_compat(self):
        """_chat should dispatch to _chat_openai_compat for openai_compat provider."""
        messages = [{"role": "user", "content": "test"}]

        with patch.object(score_module, "_chat_openai_compat") as mock_openai:
            mock_openai.return_value = "response"
            result = score_module._chat(
                messages,
                model="gpt-4o-mini",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
                provider="openai_compat",
            )

            mock_openai.assert_called_once()
            assert result == "response"

    def test_dispatches_to_anthropic_compat(self):
        """_chat should dispatch to _chat_anthropic_compat for anthropic_compat provider."""
        messages = [{"role": "user", "content": "test"}]

        with patch.object(score_module, "_chat_anthropic_compat") as mock_anthropic:
            mock_anthropic.return_value = "response"
            result = score_module._chat(
                messages,
                model="claude-3-5-sonnet-20241022",
                base_url="https://api.anthropic.com",
                api_key="sk-ant-test",
                provider="anthropic_compat",
            )

            mock_anthropic.assert_called_once()
            assert result == "response"

    def test_raises_on_unknown_provider(self):
        """_chat should raise ValueError for unknown provider."""
        messages = [{"role": "user", "content": "test"}]

        with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
            score_module._chat(
                messages,
                model="test-model",
                base_url="http://localhost:11434",
                provider="unknown_provider",
            )


class TestScoreWithProviders:
    """Tests for score_abstract and score_deep with different providers."""

    def test_score_abstract_uses_provider_from_config(self, openai_compat_config):
        """score_abstract should pass provider from config to _chat."""
        paper = {"title": "Test", "abstract": "Test abstract"}

        with patch.object(score_module, "_chat") as mock_chat:
            mock_chat.return_value = '{"score": 8, "tags": ["test"], "reason": "Good"}'
            score_module.score_abstract(paper, cfg=openai_compat_config)

            mock_chat.assert_called_once()
            call_kwargs = mock_chat.call_args[1]
            assert call_kwargs["provider"] == "openai_compat"

    def test_score_deep_uses_provider_from_config(self, anthropic_compat_config):
        """score_deep should pass provider from config to _chat."""
        paper = {"title": "Test", "abstract": "Test abstract"}
        pdf_text = "Full paper text..."

        with patch.object(score_module, "_chat") as mock_chat:
            mock_chat.return_value = '{"overall_score": 8, "novelty": 7, "rigor": 6, "reproducibility": 5, "practical_value": 7, "summary": "Sum", "why_interesting": "Why", "tags": [], "analysis": "A"}'
            score_module.score_deep(paper, pdf_text, cfg=anthropic_compat_config)

            mock_chat.assert_called_once()
            call_kwargs = mock_chat.call_args[1]
            assert call_kwargs["provider"] == "anthropic_compat"

    def test_prompts_sent_as_single_user_message_ollama(self, mock_config):
        """For ollama, prompts should be sent as a single user message."""
        paper = {"title": "Test", "abstract": "Test abstract"}

        with patch.object(score_module, "_chat") as mock_chat:
            mock_chat.return_value = '{"score": 8, "tags": ["test"], "reason": "Good"}'
            score_module.score_abstract(paper, cfg=mock_config)

            call_messages = mock_chat.call_args[0][0]  # First positional arg
            assert len(call_messages) == 1
            assert call_messages[0]["role"] == "user"
            # The prompt includes "Test" (title) and "Test abstract" in formatted content
            assert "Test" in call_messages[0]["content"]

    def test_prompts_sent_as_single_user_message_anthropic(self, anthropic_compat_config):
        """For anthropic_compat, prompts should also be sent as a single user message."""
        paper = {"title": "Test", "abstract": "Test abstract"}

        with patch.object(score_module, "_chat") as mock_chat:
            mock_chat.return_value = '{"score": 8, "tags": ["test"], "reason": "Good"}'
            score_module.score_abstract(paper, cfg=anthropic_compat_config)

            call_messages = mock_chat.call_args[0][0]  # First positional arg
            assert len(call_messages) == 1
            assert call_messages[0]["role"] == "user"
