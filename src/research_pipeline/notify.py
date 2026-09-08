"""Telegram-only notification module for research pipeline.

This module provides Telegram notification functions for sending:
- Top picks (formatted messages with paper details)
- Daily summaries
- Raw messages (back-compat for install CLI)

Fail-open: if Telegram is not configured, logs a warning and returns False.
The caller should never need to wrap in try/except.
"""
from __future__ import annotations

import logging

import httpx

from .config import Config

log = logging.getLogger(__name__)


def _build_telegram_url(bot_token: str) -> str:
    """Build the Telegram API URL for sending messages."""
    return f"https://api.telegram.org/bot{bot_token}/sendMessage"


def _send_telegram_message(
    url: str,
    payload: dict,
    timeout: float = 30.0,
) -> bool:
    """Send a message via Telegram API with Markdown parsing fallback.

    Returns True on success, False on failure.
    """
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
        if r.status_code == 200:
            return True
        # Retry as plain text if markdown parse fails
        if r.status_code == 400 and "can't parse" in r.text.lower():
            log.warning("Markdown parse failed; retrying as plain text (%s)", r.text[:120])
            plain_payload = {k: v for k, v in payload.items() if k != "parse_mode"}
            r2 = httpx.post(url, json=plain_payload, timeout=timeout)
            return r2.status_code == 200
        # Log error for other failures
        log.error("Telegram send failed: %s %s", r.status_code, r.text[:200])
        return False
    except httpx.TimeoutException:
        log.error("Telegram request timed out")
        return False
    except Exception as e:
        log.error("Telegram send exception: %s", e)
        return False


def send_top_picks(picks: list[dict], date_str: str, cfg: Config) -> bool:
    """Send top picks as a formatted Telegram message.

    Args:
        picks: List of pick dictionaries with title, score, tags, summary, arxiv_id
        date_str: Date string for the picks
        cfg: Configuration object

    Returns:
        True if sent successfully, False otherwise.
    """
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        log.warning("Telegram not configured; skipping top picks")
        return False

    url = _build_telegram_url(cfg.telegram_bot_token)

    # Build message text
    lines = [f"*Top Picks for {date_str}*", ""]
    for i, p in enumerate(picks, 1):
        title = p.get("title", "Untitled")
        score = p.get("deep_score") or p.get("abs_score") or 0.0
        tags = p.get("categories", "")
        summary = p.get("deep_summary") or p.get("abs_reason") or ""
        arxiv_id = p.get("arxiv_id", "")
        link = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""

        lines.append(f"*{i}. {title}*")
        lines.append(f"Score: {score:.1f}")
        if tags:
            lines.append(f"Tags: `{tags}`")
        if summary:
            # Truncate summary to one line
            summary_line = summary.split("\n")[0][:200]
            lines.append(f"{summary_line}")
        if link:
            lines.append(f"[arXiv]({link})")
        lines.append("")

    text = "\n".join(lines)

    # Build payload
    payload = {
        "chat_id": cfg.telegram_chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    # Add topic thread if configured
    if cfg.telegram_topic_picks:
        payload["message_thread_id"] = cfg.telegram_topic_picks

    return _send_telegram_message(url, payload)


def send_daily_summary(text: str, date_str: str, cfg: Config) -> bool:
    """Send a daily summary as a Telegram message.

    Args:
        text: Summary text to send
        date_str: Date string for the summary
        cfg: Configuration object

    Returns:
        True if sent successfully, False otherwise.
    """
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        log.warning("Telegram not configured; skipping daily summary")
        return False

    url = _build_telegram_url(cfg.telegram_bot_token)

    # Prepend date header
    full_text = f"*Daily Summary - {date_str}*\n\n{text}"

    payload = {
        "chat_id": cfg.telegram_chat_id,
        "text": full_text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    # Add topic thread if configured
    if cfg.telegram_topic_summary:
        payload["message_thread_id"] = cfg.telegram_topic_summary

    return _send_telegram_message(url, payload)


def send_raw(message: str, cfg: Config, topic: str | None = None) -> bool:
    """Send a raw message to Telegram (back-compat helper for install CLI).

    Args:
        message: Raw message text
        cfg: Configuration object
        topic: Optional topic/thread ID (picks or summary)

    Returns:
        True if sent successfully, False otherwise.
    """
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        log.warning("Telegram not configured; skipping raw message")
        return False

    url = _build_telegram_url(cfg.telegram_bot_token)

    payload = {
        "chat_id": cfg.telegram_chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    # Add topic thread if specified
    if topic:
        payload["message_thread_id"] = topic
    elif cfg.telegram_topic_picks:
        # Default to picks topic for back-compat
        payload["message_thread_id"] = cfg.telegram_topic_picks

    return _send_telegram_message(url, payload)
