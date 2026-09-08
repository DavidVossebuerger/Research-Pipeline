"""Two-stage scoring with Ollama, OpenAI-compat, and Anthropic-compat support."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from .config import Config

# Anthropic API version header (hardcoded per spec)
ANTHROPIC_VERSION = "2023-06-01"

log = logging.getLogger(__name__)


# ---------- Prompt loading ----------


def _load_prompt(name: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompts_dir = Path(__file__).parent / "prompts"
    return (prompts_dir / name).read_text(encoding="utf-8")


# ---------- HTTP layer ----------


def _chat_ollama(
    messages: list[dict],
    *,
    model: str,
    base_url: str,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    timeout: int = 120,
) -> str:
    """Call Ollama API."""
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]


def _chat_openai_compat(
    messages: list[dict],
    *,
    model: str,
    base_url: str,
    api_key: str = "",
    temperature: float = 0.2,
    max_tokens: int = 1024,
    timeout: int = 120,
) -> str:
    """Call OpenAI-compatible API (e.g., OpenRouter, OpenAI direct, Together, Groq)."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _chat_anthropic_compat(
    messages: list[dict],
    *,
    model: str,
    base_url: str,
    api_key: str,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    timeout: int = 120,
) -> str:
    """Call an Anthropic-format /v1/messages endpoint.

    Compatible with Anthropic direct and any provider that follows the Anthropic
    Messages API schema (e.g., Anthropic direct, or any Anthropic-format proxy).
    """
    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        # Response shape: {"content": [{"type": "text", "text": "..."}, ...]}
        content_blocks = data.get("content") or []
        text_parts = [block["text"] for block in content_blocks if block.get("type") == "text"]
        return "".join(text_parts)


def _chat(
    messages: list[dict],
    *,
    model: str,
    base_url: str,
    api_key: str = "",
    temperature: float = 0.2,
    max_tokens: int = 1024,
    timeout: int = 120,
    provider: str = "ollama",
) -> str:
    """Call the configured LLM provider. Returns the assistant message content.

    Args:
        messages: List of message dicts with 'role' and 'content'.
        model: Model identifier.
        base_url: Base URL for the API endpoint.
        api_key: API key for authenticating with the provider.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens to generate.
        timeout: Request timeout in seconds.
        provider: Provider name - "ollama", "openai_compat", or "anthropic_compat".
    """
    if provider == "ollama":
        return _chat_ollama(
            messages,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
    if provider == "openai_compat":
        return _chat_openai_compat(
            messages,
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
    if provider == "anthropic_compat":
        return _chat_anthropic_compat(
            messages,
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}")


# ---------- JSON extraction ----------


_JSON_BLOCK = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)
_SIMPLE_JSON = re.compile(r"^\s*\{.*\}\s*$", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract JSON from LLM response. Tries fenced block first, then raw JSON."""
    # Try fenced ```json ... ``` block
    m = _JSON_BLOCK.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try raw JSON object
    text = text.strip()
    if _SIMPLE_JSON.match(text):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Try incremental parse
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, i)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


# ---------- Scoring functions ----------


def score_abstract(paper: dict, *, cfg: Config) -> dict:
    """Score a paper's abstract for relevance to quant finance.

    Returns {"score": float, "tags": list[str], "reason": str}
    """
    template = _load_prompt("abstract_score.txt")
    prompt = template.format(
        title=paper.get("title", ""),
        abstract=paper.get("abstract", ""),
    )

    messages = [
        {"role": "user", "content": prompt},
    ]

    try:
        raw = _chat(
            messages,
            model=cfg.llm_model,
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
            temperature=0.2,
            max_tokens=400,
            provider=cfg.llm_provider,
        )
    except Exception as e:  # noqa: BLE001
        # Catch all failures to ensure one paper's scoring failure doesn't stop the pipeline
        log.warning("Abstract scoring failed: %s", e)
        return {"score": 0.0, "tags": [], "reason": "api_error"}

    parsed = _extract_json(raw)
    if parsed and "score" in parsed:
        try:
            score = float(parsed["score"])
            score = max(0.0, min(10.0, score))
            tags = parsed.get("tags") or parsed.get("relevance_tags") or []
            reason = parsed.get("reason") or parsed.get("reasoning") or ""
            return {"score": score, "tags": tags, "reason": reason}
        except (TypeError, ValueError):
            pass

    log.warning("Abstract score JSON parse failed, raw: %s", raw[:200])
    return {"score": 0.0, "tags": [], "reason": "parse_error"}


def score_deep(paper: dict, pdf_text: str, *, cfg: Config) -> dict:
    """Perform deep scoring of a paper with full text.

    Returns {
        "overall_score": float,
        "novelty": float,
        "rigor": float,
        "reproducibility": float,
        "practical_value": float,
        "summary": str,
        "why_interesting": str,
        "tags": list[str],
        "analysis": str,
    }
    """
    template = _load_prompt("deep_score.txt")
    pdf_excerpt = pdf_text[:4000]
    prompt = template.format(
        title=paper.get("title", ""),
        abstract=paper.get("abstract", ""),
        pdf_text=pdf_excerpt,
    )

    messages = [
        {"role": "user", "content": prompt},
    ]

    try:
        raw = _chat(
            messages,
            model=cfg.llm_model,
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
            temperature=0.2,
            max_tokens=2500,
            provider=cfg.llm_provider,
        )
    except Exception as e:  # noqa: BLE001
        # Catch all failures to ensure one paper's scoring failure doesn't stop the pipeline
        log.warning("Deep scoring failed: %s", e)
        return _zero_deep_result("api_error")

    parsed = _extract_json(raw)
    if parsed and "overall_score" in parsed:
        try:
            result = {
                "overall_score": float(parsed["overall_score"]),
                "novelty": parsed.get("novelty"),
                "rigor": parsed.get("rigor"),
                "reproducibility": parsed.get("reproducibility"),
                "practical_value": parsed.get("practical_value"),
                "summary": parsed.get("summary", ""),
                "why_interesting": parsed.get("why_interesting", ""),
                "tags": parsed.get("tags", []),
                "analysis": parsed.get("analysis", ""),
            }
            # Clamp score to 0-10
            result["overall_score"] = max(0.0, min(10.0, result["overall_score"]))
            return result
        except (TypeError, ValueError):
            pass

    log.warning("Deep score JSON parse failed, raw: %s", raw[:200])
    return _zero_deep_result("parse_error")


def _zero_deep_result(error_type: str) -> dict:
    """Return a zero-score deep result for error cases."""
    return {
        "overall_score": 0.0,
        "novelty": 0.0,
        "rigor": 0.0,
        "reproducibility": 0.0,
        "practical_value": 0.0,
        "summary": "",
        "why_interesting": "",
        "tags": [],
        "analysis": f"Scoring failed: {error_type}",
    }
