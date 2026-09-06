"""Telegram helper functions for install CLI."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import NamedTuple

from research_pipeline.config import CFG


class TelegramStatus(NamedTuple):
    """Status result from Telegram check."""
    token_valid: bool
    bot_username: str | None
    chat_valid: bool
    chat_id: str | None
    error: str | None


def validate_bot_token(token: str) -> tuple[bool, str | None, str | None]:
    """
    Validate a Telegram bot token via getMe.

    Returns:
        tuple of (valid, bot_username, error_message)
    """
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/getMe",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok") and data.get("result", {}).get("is_bot"):
                username = data.get("result", {}).get("username", "unknown")
                return True, username, None
            return False, None, "Invalid response from Telegram"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, None, "Unauthorized - invalid token"
        return False, None, f"HTTP {e.code}"
    except Exception as e:
        return False, None, str(e)


def validate_chat_id(token: str, chat_id: str) -> tuple[bool, str | None]:
    """
    Validate a Telegram chat ID by sending a test message.

    Returns:
        tuple of (valid, error_message)
    """
    test_message = "🤖 Research-Pipeline test — if you see this, setup is working"

    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps({
                "chat_id": chat_id,
                "text": test_message,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                return True, None
            return False, data.get("description", "Unknown error")
    except urllib.error.HTTPError as e:
        if e.code == 400:
            return False, "Bad request - check chat ID"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def get_telegram_status() -> TelegramStatus:
    """Get comprehensive Telegram status."""
    token = CFG.telegram_bot_token
    chat_id = CFG.telegram_chat_id

    if not token:
        return TelegramStatus(
            token_valid=False,
            bot_username=None,
            chat_valid=False,
            chat_id=None,
            error="No token configured",
        )

    valid, username, error = validate_bot_token(token)
    if not valid:
        return TelegramStatus(
            token_valid=False,
            bot_username=None,
            chat_valid=False,
            chat_id=chat_id,
            error=error,
        )

    if not chat_id:
        return TelegramStatus(
            token_valid=True,
            bot_username=username,
            chat_valid=False,
            chat_id=None,
            error="No chat ID configured",
        )

    chat_valid, chat_error = validate_chat_id(token, chat_id)
    return TelegramStatus(
        token_valid=True,
        bot_username=username,
        chat_valid=chat_valid,
        chat_id=chat_id,
        error=chat_error,
    )


def test_diagnose() -> dict:
    """
    Run a diagnosis test on Telegram.

    Returns:
        dict with keys: success, status_code, elapsed, bot_username, error
    """
    import json
    import time
    import urllib.error
    import urllib.request

    token = CFG.telegram_bot_token

    if not token:
        return {
            "success": False,
            "status_code": None,
            "elapsed": 0.0,
            "bot_username": None,
            "error": "No token configured",
        }

    try:
        start = time.time()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/getMe",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed = time.time() - start
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                return {
                    "success": True,
                    "status_code": resp.status,
                    "elapsed": elapsed,
                    "bot_username": data.get("result", {}).get("username"),
                    "error": None,
                }
            return {
                "success": False,
                "status_code": resp.status,
                "elapsed": elapsed,
                "bot_username": None,
                "error": data.get("description"),
            }
    except urllib.error.HTTPError as e:
        return {
            "success": False,
            "status_code": e.code,
            "elapsed": 0.0,
            "bot_username": None,
            "error": f"HTTP {e.code}",
        }
    except Exception as e:
        return {
            "success": False,
            "status_code": None,
            "elapsed": 0.0,
            "bot_username": None,
            "error": str(e),
        }
