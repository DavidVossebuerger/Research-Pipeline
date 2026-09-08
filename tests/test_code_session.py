"""Tests for code_session.py module."""

from __future__ import annotations

import time

import pytest

from research_pipeline.code_session import CodeSession


@pytest.fixture
def tmp_work_dir(tmp_path):
    """Create a temporary working directory."""
    return tmp_path / "session_test"


def test_start_returns_pid(tmp_work_dir):
    """Test that start() returns a valid PID."""
    session = CodeSession(
        arxiv_id="test123",
        work_dir=tmp_work_dir,
        command=["python3", "-c", "print('hello'); import time; time.sleep(0.1)"],
    )
    pid = session.start()
    assert pid > 0


def test_poll_shows_not_done_immediately(tmp_work_dir):
    """Test that poll() shows is_done=False immediately after start."""
    session = CodeSession(
        arxiv_id="test123",
        work_dir=tmp_work_dir,
        command=["python3", "-c", "print('hello'); import time; time.sleep(0.5)"],
    )
    session.start()
    _return_code, is_done = session.poll()
    assert is_done is False
    # Clean up
    session.terminate()


def test_poll_shows_done_after_wait(tmp_work_dir):
    """Test that poll() shows is_done=True after process completes."""
    session = CodeSession(
        arxiv_id="test123",
        work_dir=tmp_work_dir,
        command=["python3", "-c", "print('hello'); import time; time.sleep(0.1)"],
    )
    session.start()
    # Wait for completion
    return_code = session.wait(timeout=10)
    assert return_code == 0
    # Now poll should show done
    return_code, is_done = session.poll()
    assert is_done is True
    assert return_code == 0


def test_terminate_kills_long_running_process(tmp_work_dir):
    """Test that terminate() kills a long-running process."""
    # Use a command that sleeps for a long time
    session = CodeSession(
        arxiv_id="test123",
        work_dir=tmp_work_dir,
        command=["python3", "-c", "import time; time.sleep(30)"],
        timeout_sec=1500,
    )
    session.start()
    # Give it a moment to start
    time.sleep(0.1)
    # Poll should show it's running
    _, is_done = session.poll()
    assert is_done is False
    # Terminate it
    session.terminate()
    # Now poll should show it's done (killed)
    _return_code, is_done = session.poll()
    assert is_done is True


def test_read_log_tail_returns_printed_text(tmp_work_dir):
    """Test that read_log_tail() returns the printed text."""
    session = CodeSession(
        arxiv_id="test123",
        work_dir=tmp_work_dir,
        command=["python3", "-c", "print('hello'); import time; time.sleep(0.1)"],
    )
    session.start()
    # Wait for completion
    session.wait(timeout=10)
    # Read log tail
    log_tail = session.read_log_tail(n=100)
    assert "hello" in log_tail


def test_log_file_property(tmp_work_dir):
    """Test that log_file property returns the correct path."""
    session = CodeSession(
        arxiv_id="test123",
        work_dir=tmp_work_dir,
        command=["python3", "-c", "pass"],
    )
    assert session.log_file == tmp_work_dir / "session.log"


def test_arxiv_id_property(tmp_work_dir):
    """Test that arxiv_id property returns the correct value."""
    session = CodeSession(
        arxiv_id="test123",
        work_dir=tmp_work_dir,
        command=["python3", "-c", "pass"],
    )
    assert session.arxiv_id == "test123"


def test_session_with_custom_env(tmp_work_dir):
    """Test that custom environment variables are passed to subprocess."""
    env = {"CUSTOM_VAR": "custom_value"}
    session = CodeSession(
        arxiv_id="test123",
        work_dir=tmp_work_dir,
        command=["python3", "-c", "import os; print(os.environ.get('CUSTOM_VAR', 'not_found'))"],
        env=env,
    )
    session.start()
    session.wait(timeout=10)
    log_tail = session.read_log_tail(n=100)
    assert "custom_value" in log_tail
