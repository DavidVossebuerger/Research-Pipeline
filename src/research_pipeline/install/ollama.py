"""Ollama helper functions for install CLI."""

from __future__ import annotations

import subprocess
import urllib.error
import urllib.request
from typing import NamedTuple

from research_pipeline.config import CFG


class OllamaStatus(NamedTuple):
    """Status result from Ollama check."""

    installed: bool
    version: str | None
    model_installed: bool
    model_name: str
    base_url: str


def check_ollama_installed() -> tuple[bool, str | None]:
    """Check if Ollama CLI is installed."""
    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            # Parse version from output like "ollama version 0.1.0"
            version = result.stdout.strip()
            return True, version
        return False, None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, None


def check_ollama_running() -> bool:
    """Check if Ollama server is running."""
    try:
        req = urllib.request.Request(f"{CFG.llm_base_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


def check_model_installed(model_name: str | None = None) -> bool:
    """Check if the configured model is installed."""
    model = model_name or CFG.llm_model
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            # Model is listed if present in output
            return model in result.stdout
        return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def pull_model(model_name: str | None = None) -> subprocess.CompletedProcess:
    """Pull the Ollama model."""
    model = model_name or CFG.llm_model
    return subprocess.run(
        ["ollama", "pull", model],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def get_ollama_status() -> OllamaStatus:
    """Get comprehensive Ollama status."""
    installed, version = check_ollama_installed()
    running = check_ollama_running()
    model_installed = check_model_installed() if running else False

    return OllamaStatus(
        installed=installed and running,
        version=version,
        model_installed=model_installed,
        model_name=CFG.llm_model,
        base_url=CFG.llm_base_url,
    )


def test_generation() -> tuple[bool, float, int]:
    """
    Test Ollama generation with a simple prompt.

    Returns:
        tuple of (success, elapsed_seconds, tokens_generated)
    """
    import json
    import time

    prompt = "What is 1+1? Answer in one word."

    try:
        req = urllib.request.Request(
            f"{CFG.llm_base_url}/api/generate",
            data=json.dumps(
                {
                    "model": CFG.llm_model,
                    "prompt": prompt,
                    "stream": False,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        start = time.time()
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - start
            tokens = data.get("eval_count", 0)
            return True, elapsed, tokens
    except OSError:
        return False, 0.0, 0
