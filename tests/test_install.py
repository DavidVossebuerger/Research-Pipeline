"""Tests for install CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

from click.testing import CliRunner

from research_pipeline.install import doctor
from research_pipeline.install.wizard import cli as install_cli
from research_pipeline.install.wizard import read_env_file


class TestConfigGetSet:
    """Test config get/set commands."""

    def test_config_get_existing(self, tmp_path, monkeypatch):
        """Write a temp .env, run config get FOO, assert output."""
        # Create temp .env file
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=qux\n")

        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(install_cli, ["config", "get", "FOO"])

        assert result.exit_code == 0
        assert result.output.strip() == "bar"

    def test_config_get_missing(self, tmp_path, monkeypatch):
        """Exit code 1 if key not found."""
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\n")

        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(install_cli, ["config", "get", "MISSING"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_config_set_new(self, tmp_path, monkeypatch):
        """Write new key to .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\n")

        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(install_cli, ["config", "set", "NEWKEY", "newvalue"])

        assert result.exit_code == 0
        content = env_file.read_text()
        assert "NEWKEY=newvalue" in content
        assert "FOO=bar" in content

    def test_config_set_existing(self, tmp_path, monkeypatch):
        """Replace value, preserve formatting."""
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\nBAZ=qux\n")

        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(install_cli, ["config", "set", "FOO", "updated"])

        assert result.exit_code == 0
        content = env_file.read_text()
        assert "FOO=updated" in content
        assert "BAZ=qux" in content

    def test_read_env_file_empty(self, tmp_path):
        """Test reading empty .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("")

        env = read_env_file(env_file)
        assert env == {}

    def test_read_env_file_with_comments(self, tmp_path):
        """Test reading .env with comments."""
        env_file = tmp_path / ".env"
        env_file.write_text("# Comment\nFOO=bar\n\nBAZ=qux\n")

        env = read_env_file(env_file)
        assert env == {"FOO": "bar", "BAZ": "qux"}

    def test_read_env_file_quoted_values(self, tmp_path):
        """Test reading .env with quoted values."""
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=\"bar baz\"\nBAZ='qux'\n")

        env = read_env_file(env_file)
        assert env == {"FOO": "bar baz", "BAZ": "qux"}


class TestDoctorExitCodes:
    """Test doctor exit codes."""

    def test_doctor_exits_2_on_failure(self, monkeypatch):
        """Mock Telegram getMe to return 401, assert exit 2."""
        # Mock Telegram to return failure
        import research_pipeline.install.telegram as tg_module

        monkeypatch.setattr(
            tg_module,
            "get_telegram_status",
            lambda: MagicMock(
                token_valid=False,
                bot_username=None,
                chat_valid=False,
                chat_id=None,
                error="Unauthorized",
            ),
        )

        # Mock Ollama
        import research_pipeline.install.ollama as ollama_module

        monkeypatch.setattr(
            ollama_module,
            "get_ollama_status",
            lambda: MagicMock(
                installed=True,
                version="0.1.0",
                model_installed=True,
                model_name="phi3.5:3.8b",
                base_url="http://localhost:11434",
            ),
        )

        # Mock Cron
        import research_pipeline.install.cron as cron_module

        monkeypatch.setattr(
            cron_module,
            "get_cron_entry",
            lambda: MagicMock(
                installed=True,
                schedule="30 07 * * *",
                command="some command",
                error=None,
            ),
        )

        # Mock log file
        import research_pipeline.config as config_module

        mock_cfg = MagicMock()
        mock_cfg.log_dir = MagicMock()
        mock_cfg.log_dir.exists.return_value = False
        monkeypatch.setattr(config_module, "CFG", mock_cfg)

        result = doctor.run_doctor()
        assert result.exit_code == 2

    def test_doctor_exits_0_on_success(self, monkeypatch):
        """Mock everything green."""
        # Mock Telegram
        import research_pipeline.install.telegram as tg_module

        monkeypatch.setattr(
            tg_module,
            "get_telegram_status",
            lambda: MagicMock(
                token_valid=True,
                bot_username="test_bot",
                chat_valid=True,
                chat_id="123456",
                error=None,
            ),
        )

        # Mock Ollama
        import research_pipeline.install.ollama as ollama_module

        monkeypatch.setattr(
            ollama_module,
            "get_ollama_status",
            lambda: MagicMock(
                installed=True,
                version="0.1.0",
                model_installed=True,
                model_name="phi3.5:3.8b",
                base_url="http://localhost:11434",
            ),
        )

        # Mock Cron
        import research_pipeline.install.cron as cron_module

        monkeypatch.setattr(
            cron_module,
            "get_cron_entry",
            lambda: MagicMock(
                installed=True,
                schedule="30 07 * * *",
                command="some command",
                error=None,
            ),
        )

        # Mock log dir
        import research_pipeline.config as config_module

        mock_log_dir = MagicMock()
        mock_log_dir.exists.return_value = True
        mock_log_dir.__truediv__ = lambda self, x: MagicMock(exists=MagicMock(return_value=True))
        mock_cfg = MagicMock()
        mock_cfg.log_dir = mock_log_dir
        monkeypatch.setattr(config_module, "CFG", mock_cfg)

        result = doctor.run_doctor()
        assert result.exit_code == 0


class TestUninstall:
    """Test uninstall command."""

    def test_uninstall_dry_run(self, tmp_path, monkeypatch):
        """--dry-run flag doesn't touch cron or .env."""
        # Create .env
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\n")

        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(install_cli, ["uninstall", "--dry-run"])

        assert result.exit_code == 0
        # .env should still exist
        assert env_file.exists()
        assert "dry-run" in result.output.lower()


class TestStatus:
    """Test status command."""

    def test_status_runs(self, tmp_path, monkeypatch):
        """Status command runs without error."""
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(install_cli, ["status"])

        # Should run without crashing (may have failures but shouldn't error)
        assert result.exit_code == 0


class TestDiagnose:
    """Test diagnose command."""

    def test_diagnose_runs(self, tmp_path, monkeypatch):
        """Diagnose command runs without error."""
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(install_cli, ["diagnose"])

        # Should run without crashing
        assert result.exit_code == 0
