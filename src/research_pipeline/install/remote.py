"""SSH-based remote installation helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class RemoteInstallError(RuntimeError):
    """Raised when a remote operation fails."""


@dataclass
class SSHConnection:
    host: str
    user: str
    password: str
    port: int = 22

    def _sshpass_env_args(self, *cmd: str, connect_timeout: int = 30) -> tuple[dict, list[str]]:
        """Build sshpass + ssh invocation. Passes the password via the SSHPASS env
        variable instead of `-p` so it doesn't show up in `ps auxe`.
        """
        env = {**os.environ, "SSHPASS": self.password}
        args = [
            "sshpass",
            "-e",  # read password from SSHPASS env var
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "UserKnownHostsFile=" + str(Path.home() / ".ssh" / "known_hosts_research_pipeline"),
            "-o",
            f"ConnectTimeout={connect_timeout}",
            "-p",
            str(self.port),
            f"{self.user}@{self.host}",
            *cmd,
        ]
        return env, args

    def _scp_env_args(
        self, local_path: Path, remote_path: str, *, connect_timeout: int = 30
    ) -> tuple[dict, list[str]]:
        env = {**os.environ, "SSHPASS": self.password}
        args = [
            "sshpass",
            "-e",
            "scp",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "UserKnownHostsFile=" + str(Path.home() / ".ssh" / "known_hosts_research_pipeline"),
            "-o",
            f"ConnectTimeout={connect_timeout}",
            "-P",
            str(self.port),
            str(local_path),
            f"{self.user}@{self.host}:{remote_path}",
        ]
        return env, args

    def check_local_requirements(self) -> None:
        """Verify sshpass is installed locally. Raises if not."""
        if not shutil.which("sshpass"):
            raise RemoteInstallError(
                "sshpass is not installed locally. Install with:\n"
                "  Debian/Ubuntu: sudo apt install sshpass\n"
                "  macOS: brew install hudochenkov/sshpass/sshpass\n"
                "  Fedora: sudo dnf install sshpass"
            )

    def _run_silent(
        self, args: list[str], env: dict, *, timeout: int
    ) -> subprocess.CompletedProcess:
        """Run a command and convert common subprocess failures into RemoteInstallError."""
        try:
            return subprocess.run(
                args,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise RemoteInstallError(
                f"SSH command timed out after {timeout}s. Possible causes:\n"
                f"  - Hostname '{self.host}' doesn't resolve (check DNS, try FQDN or IP)\n"
                f"  - SSH port {self.port} blocked by firewall\n"
                f"  - Remote host unreachable\n"
                f"  - SSH server slow to authenticate\n"
                f"Try: ssh -v {self.user}@{self.host}  (to see what ssh itself reports)"
            ) from None
        except FileNotFoundError as e:
            raise RemoteInstallError(f"Required command not found: {e}") from None
        except OSError as e:
            raise RemoteInstallError(f"OS error while running ssh: {e}") from None

    def check_connection(self) -> tuple[bool, str]:
        """Verify SSH connection works. Returns (ok, message)."""
        env, args = self._sshpass_env_args("echo", "ok")
        try:
            result = self._run_silent(args, env, timeout=30)
        except RemoteInstallError as e:
            return False, str(e)

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "Permission denied" in stderr:
                msg = "Authentication failed (Permission denied). Check username and password."
            elif "Could not resolve hostname" in stderr or "Name or service not known" in stderr:
                msg = f"Hostname '{self.host}' doesn't resolve. Try the FQDN or IP address."
            elif "Connection refused" in stderr:
                msg = f"SSH port {self.port} refused on {self.host}. Is sshd running?"
            elif "Connection timed out" in stderr or "timed out" in stderr.lower():
                msg = f"Connection timed out. Check network/firewall for {self.host}:{self.port}."
            else:
                msg = stderr or f"ssh returned exit code {result.returncode}"
            return False, msg

        return True, "ok"

    def check_python(self) -> str | None:
        """Return remote python3.11+ version string, or None if missing."""
        env, args = self._sshpass_env_args(
            "command -v python3.11 || command -v python3 || echo none"
        )
        try:
            result = self._run_silent(args, env, timeout=30)
        except RemoteInstallError as e:
            raise RemoteInstallError(f"Python check failed: {e}") from e

        if result.returncode != 0 or "none" in result.stdout:
            return None
        python_path = result.stdout.strip()
        env, args = self._sshpass_env_args(python_path, "--version")
        try:
            version_result = self._run_silent(args, env, timeout=30)
        except RemoteInstallError as e:
            raise RemoteInstallError(f"Python version check failed: {e}") from e
        return version_result.stdout.strip() if version_result.returncode == 0 else None

    def stream_command(self, command: str, *, timeout: int = 1800) -> int:
        """Run a command on the remote host, streaming stdout/stderr live.

        Returns the remote exit code. Raises RemoteInstallError on connection failure.
        """
        import sys

        env, args = self._sshpass_env_args(command, connect_timeout=30)
        try:
            proc = subprocess.Popen(
                args,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
            )
        except FileNotFoundError as e:
            raise RemoteInstallError(f"sshpass not found: {e}") from None
        except OSError as e:
            raise RemoteInstallError(f"Failed to start ssh: {e}") from None

        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                print(f"  [remote] {line}", end="")
                sys.stdout.flush()
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RemoteInstallError(f"Remote command timed out after {timeout}s") from None
        except KeyboardInterrupt:
            proc.kill()
            raise RemoteInstallError("Aborted by user (Ctrl+C)") from None
        return proc.returncode

    def upload_file(self, local_path: Path, remote_path: str) -> None:
        """Upload a file via scp+sshpass."""
        env, args = self._scp_env_args(local_path, remote_path)
        try:
            result = self._run_silent(args, env, timeout=60)
        except RemoteInstallError as e:
            raise RemoteInstallError(f"SCP upload failed: {e}") from e
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RemoteInstallError(
                f"SCP upload failed: {stderr or f'exit code {result.returncode}'}"
            )
