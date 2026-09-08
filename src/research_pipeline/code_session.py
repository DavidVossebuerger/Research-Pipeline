"""Thin subprocess wrapper for running isolated code sessions."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


class CodeSession:
    """Wrapper around subprocess.Popen for running isolated sessions.

    Provides a minimal API for spawning, polling, waiting, and terminating
    a subprocess, with log capture.
    """

    def __init__(
        self,
        arxiv_id: str,
        work_dir: Path,
        command: list[str],
        *,
        timeout_sec: int = 1500,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize a code session.

        Args:
            arxiv_id: The arXiv paper ID this session is for.
            work_dir: Working directory for the subprocess.
            command: Command to execute as list of strings.
            timeout_sec: Maximum time the session can run (default 25 min).
            env: Environment variables. If None, inherits os.environ.
        """
        self.arxiv_id = arxiv_id
        self.work_dir = Path(work_dir)
        self.command = command
        self.timeout_sec = timeout_sec
        self._env = env if env is not None else dict(os.environ)
        self._proc: subprocess.Popen[Any] | None = None
        self._log_file = self.work_dir / "session.log"

    @property
    def log_file(self) -> Path:
        """Path to the session log file."""
        return self._log_file

    def start(self) -> int:
        """Spawn the subprocess.

        Returns:
            PID of the spawned process.

        Raises:
            RuntimeError: If the session has already been started.
        """
        if self._proc is not None:
            raise RuntimeError("Session already started")

        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Open log file for stdout/stderr capture - must stay open for subprocess
        log_fp = open(self._log_file, "w")  # noqa: SIM115
        self._proc = subprocess.Popen(
            self.command,
            cwd=str(self.work_dir),
            env=self._env,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        return self._proc.pid

    def poll(self) -> tuple[int | None, bool]:
        """Check if the process has terminated.

        Returns:
            Tuple of (return_code, is_done). return_code is None if still running.
        """
        if self._proc is None:
            return None, False
        return_code = self._proc.poll()
        is_done = return_code is not None
        return return_code, is_done

    def wait(self, timeout: float | None = None) -> int:
        """Wait for the process to complete.

        Args:
            timeout: Maximum time to wait in seconds. If None, uses the default timeout_sec.

        Returns:
            Return code of the process.

        Raises:
            subprocess.TimeoutExpired: If the process exceeds the timeout.
        """
        if self._proc is None:
            raise RuntimeError("Session not started")

        effective_timeout = timeout if timeout is not None else self.timeout_sec
        try:
            return self._proc.wait(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            self.terminate()
            raise

    def terminate(self) -> None:
        """Send SIGTERM to the process, then SIGKILL after 5s if still alive."""
        if self._proc is None:
            return

        # Send SIGTERM
        try:
            self._proc.terminate()
        except ProcessLookupError:
            return  # Process already gone

        # Wait up to 5 seconds for graceful termination
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Force kill
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except ProcessLookupError:
                pass

    def read_log_tail(self, n: int = 100) -> str:
        """Read the last N lines from the session log.

        Args:
            n: Number of lines to read from the end.

        Returns:
            The last N lines of the log file, or empty string if log doesn't exist.
        """
        if not self._log_file.exists():
            return ""

        try:
            lines = self._log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[-n:])
        except OSError:
            return ""
