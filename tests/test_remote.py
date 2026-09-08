"""Tests for SSH remote installation helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research_pipeline.install.remote import RemoteInstallError, SSHConnection


class TestCheckLocalRequirements:
    """Test sshpass availability check."""

    def test_sshpass_available(self, monkeypatch):
        """Should pass if sshpass is found."""
        monkeypatch.setattr(
            "shutil.which", lambda x: "/usr/bin/sshpass" if x == "sshpass" else None
        )

        ssh = SSHConnection(host="example.com", user="test", password="pass")
        # Should not raise
        ssh.check_local_requirements()

    def test_sshpass_not_available(self, monkeypatch):
        """Should raise RemoteInstallError if sshpass not found."""
        monkeypatch.setattr("shutil.which", lambda x: None)

        ssh = SSHConnection(host="example.com", user="test", password="pass")
        with pytest.raises(RemoteInstallError) as exc_info:
            ssh.check_local_requirements()

        assert "sshpass is not installed" in str(exc_info.value)


class TestCheckConnection:
    """Test SSH connection validation."""

    def test_connection_success(self, monkeypatch):
        """Should return True on successful connection."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_result)

        ssh = SSHConnection(host="example.com", user="test", password="pass")
        ok, msg = ssh.check_connection()

        assert ok is True
        assert msg == "ok"

    def test_connection_failure(self, monkeypatch):
        """Should return False on auth failure."""
        mock_result = MagicMock()
        mock_result.returncode = 255
        mock_result.stderr = "Permission denied"

        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_result)

        ssh = SSHConnection(host="example.com", user="test", password="pass")
        ok, msg = ssh.check_connection()

        assert ok is False
        assert "Permission denied" in msg


class TestCheckPython:
    """Test remote Python version check."""

    def test_python_found(self, monkeypatch):
        """Should return version string if Python found."""
        # First call finds python3.11
        mock_result1 = MagicMock()
        mock_result1.returncode = 0
        mock_result1.stdout = "python3.11\n"

        # Second call gets version
        mock_result2 = MagicMock()
        mock_result2.returncode = 0
        mock_result2.stdout = "Python 3.11.0"

        results = [mock_result1, mock_result2]

        def mock_run(*args, **kwargs):
            return results.pop(0)

        monkeypatch.setattr(subprocess, "run", mock_run)

        ssh = SSHConnection(host="example.com", user="test", password="pass")
        version = ssh.check_python()

        assert version == "Python 3.11.0"

    def test_python_not_found(self, monkeypatch):
        """Should return None if no Python found."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "none\n"

        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_result)

        ssh = SSHConnection(host="example.com", user="test", password="pass")
        version = ssh.check_python()

        assert version is None


class TestStreamCommand:
    """Test remote command streaming."""

    def test_command_success(self, monkeypatch):
        """Should return exit code 0 on success."""
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["line 1\n", "line 2\n"])
        mock_proc.returncode = 0

        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: mock_proc)

        ssh = SSHConnection(host="example.com", user="test", password="pass")
        rc = ssh.stream_command("echo test")

        assert rc == 0

    def test_command_failure(self, monkeypatch):
        """Should return non-zero exit code on failure."""
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["error\n"])
        mock_proc.returncode = 1

        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: mock_proc)

        ssh = SSHConnection(host="example.com", user="test", password="pass")
        rc = ssh.stream_command("false")

        assert rc == 1

    def test_command_timeout(self, monkeypatch):
        """Should raise RemoteInstallError on timeout."""
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait = MagicMock(side_effect=subprocess.TimeoutExpired("cmd", 1))

        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: mock_proc)

        ssh = SSHConnection(host="example.com", user="test", password="pass")
        with pytest.raises(RemoteInstallError) as exc_info:
            ssh.stream_command("sleep 100", timeout=1)

        assert "timed out" in str(exc_info.value)

    def test_command_keyboard_interrupt(self, monkeypatch):
        """Should raise RemoteInstallError on Ctrl+C."""
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait = MagicMock(side_effect=KeyboardInterrupt())

        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: mock_proc)

        ssh = SSHConnection(host="example.com", user="test", password="pass")
        with pytest.raises(RemoteInstallError) as exc_info:
            ssh.stream_command("sleep 100")

        assert "Aborted by user" in str(exc_info.value)


class TestUploadFile:
    """Test file upload via scp."""

    def test_upload_success(self, monkeypatch):
        """Should succeed if scp returns 0."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_result)

        ssh = SSHConnection(host="example.com", user="test", password="pass")
        # Should not raise
        ssh.upload_file(Path("/local/file.sh"), "~/remote.sh")

    def test_upload_failure(self, monkeypatch):
        """Should raise RemoteInstallError if scp fails."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Connection refused"

        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_result)

        ssh = SSHConnection(host="example.com", user="test", password="pass")
        with pytest.raises(RemoteInstallError) as exc_info:
            ssh.upload_file(Path("/local/file.sh"), "~/remote.sh")

        assert "SCP upload failed" in str(exc_info.value)
