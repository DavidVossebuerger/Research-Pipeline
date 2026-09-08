"""Tests for config.py — env loading and parsing."""

from __future__ import annotations

# Import the module to test (will reload with monkeypatched env)
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

import research_pipeline.config as config_module


class TestEnvParsers:
    """Test the helper functions for env parsing."""

    def test_env_bool_true_values(self):
        """Test that true-like strings parse to True."""
        for val in ("1", "true", "yes", "on", "TRUE", "YES", "ON"):
            with patch.dict("os.environ", {"TEST": val}):
                result = config_module._env_bool("TEST", False)
                assert result is True, f"Expected True for '{val}'"

    def test_env_bool_false_values(self):
        """Test that false-like strings parse to False."""
        for val in ("0", "false", "no", "off", "FALSE", "NO", "OFF"):
            with patch.dict("os.environ", {"TEST": val}):
                result = config_module._env_bool("TEST", True)
                assert result is False, f"Expected False for '{val}'"

    def test_env_bool_default(self):
        """Test that missing env returns default."""
        with patch.dict("os.environ", {}, clear=True):
            result = config_module._env_bool("MISSING", True)
            assert result is True
            result = config_module._env_bool("MISSING", False)
            assert result is False

    def test_env_bool_empty_string(self):
        """Test that empty string returns default."""
        with patch.dict("os.environ", {"TEST": ""}):
            result = config_module._env_bool("TEST", True)
            assert result is True

    def test_env_int_valid(self):
        """Test integer parsing."""
        with patch.dict("os.environ", {"TEST": "42"}):
            assert config_module._env_int("TEST", 0) == 42

    def test_env_int_missing(self):
        """Test integer returns default when missing."""
        with patch.dict("os.environ", {}, clear=True):
            assert config_module._env_int("MISSING", 99) == 99

    def test_env_float_valid(self):
        """Test float parsing."""
        with patch.dict("os.environ", {"TEST": "3.14"}):
            assert config_module._env_float("TEST", 0.0) == 3.14

    def test_env_float_missing(self):
        """Test float returns default when missing."""
        with patch.dict("os.environ", {}, clear=True):
            assert config_module._env_float("MISSING", 1.5) == 1.5

    def test_env_list_parsing(self):
        """Test comma-separated list parsing."""
        with patch.dict("os.environ", {"TEST": "a, b, c"}):
            result = config_module._env_list("TEST", [])
            assert result == ["a", "b", "c"]

    def test_env_list_empty_entries_dropped(self):
        """Test that empty entries are dropped."""
        with patch.dict("os.environ", {"TEST": "a, , b, ,"}):
            result = config_module._env_list("TEST", [])
            assert result == ["a", "b"]

    def test_env_list_missing(self):
        """Test list returns default when missing."""
        with patch.dict("os.environ", {}, clear=True):
            default = ["x", "y"]
            result = config_module._env_list("MISSING", default)
            assert result == default

    def test_env_list_empty_string(self):
        """Test empty string returns default."""
        with patch.dict("os.environ", {"TEST": ""}):
            default = ["x", "y"]
            result = config_module._env_list("TEST", default)
            assert result == default


class TestConfigDefaults:
    """Test that defaults are applied when no .env is present."""

    def test_defaults_no_env(self, monkeypatch):
        """Test that CFG has expected defaults when no env vars are set."""
        # Clear all env vars that config reads
        env_vars = [
            "LLM_PROVIDER",
            "LLM_MODEL",
            "LLM_BASE_URL",
            "LLM_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "TELEGRAM_TOPIC_PICKS",
            "TELEGRAM_TOPIC_SUMMARY",
            "CRON_DAILY_TIME",
            "CRON_AUTOBUILD_POLL",
            "FEATURE_DAILY_SUMMARY_ENABLED",
            "FEATURE_WEEKLY_DIGEST_ENABLED",
            "FEATURE_AUTOBUILD_ENABLED",
            "FEATURE_TELEGRAM_BOT_ENABLED",
            "FEATURE_BACKFILL_ENABLED",
            "ARXIV_CATEGORIES",
            "ARXIV_LOOKBACK_HOURS",
            "ARXIV_MAX_RESULTS",
            "ARXIV_FIXTURE_PATH",
            "SCORE_STAGE_A_THRESHOLD",
            "SCORE_STAGE_B_TOP_K",
            "NOTIFY_TOP_K",
            "DB_PATH",
            "PDF_DIR",
            "LOG_DIR",
            "AUTOBUILD_DATA_DIR",
        ]
        for var in env_vars:
            monkeypatch.delenv(var, raising=False)

        # Reload the module to pick up the cleared env
        importlib.reload(config_module)
        cfg = config_module.CFG

        assert cfg.llm_provider == "ollama"
        assert cfg.llm_model == "phi3.5:3.8b"
        assert cfg.llm_base_url == "http://localhost:11434"
        assert cfg.llm_api_key == ""
        assert cfg.cron_daily_time == "07:30"
        assert cfg.cron_autobuild_poll == "*/5"
        assert cfg.feature_daily_summary_enabled is True
        assert cfg.feature_weekly_digest_enabled is False
        assert cfg.feature_autobuild_enabled is False
        assert cfg.feature_telegram_bot_enabled is False
        assert cfg.feature_backfill_enabled is False
        assert cfg.arxiv_lookback_hours == 26
        assert cfg.arxiv_max_results == 200
        assert cfg.arxiv_fixture_path == ""
        assert cfg.score_stage_a_threshold == 7.0
        assert cfg.score_stage_b_top_k == 10
        assert cfg.notify_top_k == 3

    def test_env_override_works(self, monkeypatch):
        """Test that env vars override defaults."""
        monkeypatch.setenv("LLM_MODEL", "qwen2.5:7b")
        monkeypatch.setenv("LLM_PROVIDER", "openrouter")
        monkeypatch.setenv("ARXIV_MAX_RESULTS", "500")
        monkeypatch.setenv("SCORE_STAGE_A_THRESHOLD", "8.5")

        importlib.reload(config_module)
        cfg = config_module.CFG

        assert cfg.llm_model == "qwen2.5:7b"
        assert cfg.llm_provider == "openrouter"
        assert cfg.arxiv_max_results == 500
        assert cfg.score_stage_a_threshold == 8.5


class TestPathResolution:
    """Test that relative paths are resolved to absolute."""

    def test_relative_path_resolved(self, monkeypatch, tmp_path):
        """Test that relative paths become absolute."""
        # Set relative paths
        monkeypatch.setenv("DB_PATH", "data/state.db")
        monkeypatch.setenv("PDF_DIR", "pdfs")
        monkeypatch.setenv("LOG_DIR", "logs")
        monkeypatch.setenv("AUTOBUILD_DATA_DIR", "data/autobuild")

        importlib.reload(config_module)
        cfg = config_module.CFG

        # All paths should be absolute and resolve to cwd
        cwd = Path.cwd()
        assert cfg.db_path.is_absolute()
        assert cfg.db_path == cwd / "data" / "state.db"
        assert cfg.pdf_dir.is_absolute()
        assert cfg.pdf_dir == cwd / "pdfs"
        assert cfg.log_dir.is_absolute()
        assert cfg.log_dir == cwd / "logs"
        assert cfg.autobuild_data_dir.is_absolute()
        assert cfg.autobuild_data_dir == cwd / "data" / "autobuild"

    def test_absolute_path_unchanged(self, monkeypatch):
        """Test that absolute paths stay absolute."""
        monkeypatch.setenv("DB_PATH", "/absolute/path/to/db")
        monkeypatch.setenv("PDF_DIR", "/absolute/pdf")
        monkeypatch.setenv("LOG_DIR", "/absolute/log")
        monkeypatch.setenv("AUTOBUILD_DATA_DIR", "/absolute/autobuild")

        importlib.reload(config_module)
        cfg = config_module.CFG

        assert cfg.db_path == Path("/absolute/path/to/db")
        assert cfg.pdf_dir == Path("/absolute/pdf")
        assert cfg.log_dir == Path("/absolute/log")
        assert cfg.autobuild_data_dir == Path("/absolute/autobuild")


class TestRequiredVars:
    """Test handling of required environment variables."""

    def test_required_var_missing_raises(self, monkeypatch):
        """Test that missing required var raises RuntimeError."""
        # Make a var required by using required=True
        # Since our current config doesn't use required=True for any var,
        # we test the _env function directly
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                config_module._env("MISSING_REQUIRED", required=True)
            assert "MISSING_REQUIRED" in str(exc_info.value)
