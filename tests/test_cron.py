"""Tests for cron installation and schedule handling."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from research_pipeline.install import cron


class TestCronScheduleFix:
    """Test that cron daily_time is installed correctly (hour/minute not swapped)."""

    def test_cron_entry_0730_produces_correct_format(self, monkeypatch, tmp_path):
        """Input 07:30 should produce cron line starting with '30 7 * * *'."""
        monkeypatch.setenv("HOME", str(tmp_path))

        # Mock subprocess to simulate empty crontab
        def mock_run(cmd, **kwargs):
            if cmd[0] == "crontab" and cmd[1] == "-l":
                # Return empty crontab
                mock_result = type("MockResult", (), {})()
                mock_result.returncode = 1
                mock_result.stderr = "no crontab for user"
                return mock_result
            if cmd[0] == "crontab" and cmd[1] == "-":
                # Capture the new crontab
                mock_result = type("MockResult", (), {})()
                mock_result.returncode = 0
                mock_result.stderr = ""
                # Store the input for verification
                cron_input = kwargs.get("input", "")
                # Write to a file to inspect
                (tmp_path / "new_crontab.txt").write_text(cron_input)
                return mock_result
            return subprocess.run(cmd, **kwargs, check=False)

        monkeypatch.setattr(subprocess, "run", mock_run)

        # Mock config to use our test paths
        mock_cfg = type("MockCFG", (), {})()
        mock_cfg.cron_daily_time = "07:30"
        mock_cfg.log_dir = tmp_path / "logs"
        mock_cfg.log_dir.mkdir(parents=True, exist_ok=True)

        with patch("research_pipeline.install.cron.CFG", mock_cfg):
            success, error = cron.install_cron_entry()

        assert success, f"Failed to install cron: {error}"

        # Read the crontab that was written
        new_crontab = (tmp_path / "new_crontab.txt").read_text()

        # The cron line should start with "30 7 * * *" (minute hour)
        # NOT "07 30 * * *" (which would be hour minute - wrong!)
        lines = new_crontab.strip().split("\n")
        cron_line = next(l for l in lines if "research_pipeline" in l)

        # Accept either "30 7" or "30 07" format (cron normalizes to 2 digits)
        assert cron_line.startswith(("30 7 * * *", "30 07 * * *")), (
            f"Cron line should start with '30 7 * * *' or '30 07 * * *' for input '07:30', "
            f"but got: {cron_line[:20]}"
        )

    def test_cron_entry_2359_produces_correct_format(self, monkeypatch, tmp_path):
        """Input 23:59 should produce cron line starting with '59 23 * * *'."""
        monkeypatch.setenv("HOME", str(tmp_path))

        def mock_run(cmd, **kwargs):
            if cmd[0] == "crontab" and cmd[1] == "-l":
                mock_result = type("MockResult", (), {})()
                mock_result.returncode = 1
                mock_result.stderr = "no crontab for user"
                return mock_result
            if cmd[0] == "crontab" and cmd[1] == "-":
                mock_result = type("MockResult", (), {})()
                mock_result.returncode = 0
                mock_result.stderr = ""
                cron_input = kwargs.get("input", "")
                (tmp_path / "new_crontab.txt").write_text(cron_input)
                return mock_result
            return subprocess.run(cmd, **kwargs, check=False)

        monkeypatch.setattr(subprocess, "run", mock_run)

        mock_cfg = type("MockCFG", (), {})()
        mock_cfg.cron_daily_time = "23:59"
        mock_cfg.log_dir = tmp_path / "logs"
        mock_cfg.log_dir.mkdir(parents=True, exist_ok=True)

        with patch("research_pipeline.install.cron.CFG", mock_cfg):
            success, error = cron.install_cron_entry()

        assert success, f"Failed to install cron: {error}"

        new_crontab = (tmp_path / "new_crontab.txt").read_text()
        lines = new_crontab.strip().split("\n")
        cron_line = next(l for l in lines if "research_pipeline" in l)

        assert cron_line.startswith("59 23 * * *"), (
            f"Cron line should start with '59 23 * * *' for input '23:59', "
            f"but got: {cron_line[:20]}"
        )

    def test_cron_entry_invalid_time_returns_error(self, monkeypatch, tmp_path):
        """Invalid time format should return error."""
        mock_cfg = type("MockCFG", (), {})()
        mock_cfg.cron_daily_time = "25:00"  # Invalid hour
        mock_cfg.log_dir = tmp_path / "logs"
        mock_cfg.log_dir.mkdir(parents=True, exist_ok=True)

        with patch("research_pipeline.install.cron.CFG", mock_cfg):
            success, error = cron.install_cron_entry()

        assert not success
        assert error is not None
        assert "Invalid schedule time" in error

    def test_cron_entry_invalid_format_returns_error(self, monkeypatch):
        """Invalid format should return error."""
        mock_cfg = type("MockCFG", (), {})()
        mock_cfg.cron_daily_time = "not-a-time"

        with patch("research_pipeline.install.cron.CFG", mock_cfg):
            success, error = cron.install_cron_entry()

        assert not success
        assert error is not None
