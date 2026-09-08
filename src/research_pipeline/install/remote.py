"""SSH-based remote installation helpers."""

from __future__ import annotations

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

    def _sshpass_args(self, *cmd: str, input: bytes | None = None, check: bool = True) -> list[str]:
        return [
            "sshpass",
            "-p",
            self.password,
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "UserKnownHostsFile=" + str(Path.home() / ".ssh" / "known_hosts_research_pipeline"),
            "-p",
            str(self.port),
            f"{self.user}@{self.host}",
            *cmd,
        ]

    def check_local_requirements(self) -> None:
        """Verify sshpass is installed locally. Raises if not."""
        if not shutil.which("sshpass"):
            raise RemoteInstallError(
                "sshpass is not installed locally. Install with:\n"
                "  Debian/Ubuntu: sudo apt install sshpass\n"
                "  macOS: brew install hudochenkov/sshpass/sshpass\n"
                "  Fedora: sudo dnf install sshpass"
            )

    def check_connection(self) -> tuple[bool, str]:
        """Verify SSH connection works. Returns (ok, ssh_banner)."""
        result = subprocess.run(
            self._sshpass_args("echo", "ok"),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, "ok"

    def check_python(self) -> str | None:
        """Return remote python3.11+ version string, or None if missing."""
        result = subprocess.run(
            self._sshpass_args("command -v python3.11 || command -v python3 || echo none"),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0 or "none" in result.stdout:
            return None
        version_result = subprocess.run(
            self._sshpass_args(result.stdout.strip(), "--version"),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return version_result.stdout.strip() if version_result.returncode == 0 else None

    def stream_command(self, command: str, *, timeout: int = 1800) -> int:
        """Run a command on the remote host, streaming stdout/stderr live to the local terminal.

        Returns the remote exit code. Raises RemoteInstallError on connection failure.
        """
        import sys

        proc = subprocess.Popen(
            self._sshpass_args(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge so the user sees a single chronological stream
            bufsize=1,
            text=True,
        )
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                print(f"  [remote] {line}", end="")
                sys.stdout.flush()
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RemoteInstallError(f"Remote command timed out after {timeout}s")
        except KeyboardInterrupt:
            proc.kill()
            raise RemoteInstallError("Aborted by user (Ctrl+C)")
        return proc.returncode

    def upload_file(self, local_path: Path, remote_path: str) -> None:
        """Upload a file via scp+sshpass."""
        result = subprocess.run(
            [
                "sshpass",
                "-p",
                self.password,
                "scp",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "UserKnownHostsFile=" + str(Path.home() / ".ssh" / "known_hosts_research_pipeline"),
                "-P",
                str(self.port),
                str(local_path),
                f"{self.user}@{self.host}:{remote_path}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise RemoteInstallError(f"SCP upload failed: {result.stderr.strip()}")
