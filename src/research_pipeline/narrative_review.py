"""Narrative review module for generating LLM-based narrative summaries of papers."""

from __future__ import annotations

import logging
from typing import Any

from .config import Config
from . import score

log = logging.getLogger(__name__)

# Maximum characters for truncated summary in prompts
_SUMMARY_TRUNCATE_CHARS = 200


def _truncate_summary(summary: str | None) -> str:
    """Truncate summary to approximately _SUMMARY_TRUNCATE_CHARS."""
    if not summary:
        return ""
    # Truncate and clean up
    truncated = summary[:_SUMMARY_TRUNCATE_CHARS]
    # Try to end at a sentence boundary
    for punct in (". ", "! ", "? "):
        last_punct = truncated.rfind(punct)
        if last_punct > len(truncated) // 2:
            truncated = truncated[: last_punct + 1]
    return truncated


def _format_paper_for_prompt(paper: dict[str, Any]) -> str:
    """Format a paper dict for inclusion in a narrative prompt."""
    title = paper.get("title", "Untitled")
    arxiv_id = paper.get("arxiv_id", "")
    tags = paper.get("deep_tags") or paper.get("abs_tags") or paper.get("categories", "")
    summary = _truncate_summary(paper.get("deep_summary") or paper.get("abs_reason"))

    # Clean up tags - could be comma-separated or JSON list
    if isinstance(tags, str):
        tags_str = tags
    elif isinstance(tags, list):
        tags_str = ", ".join(str(t) for t in tags)
    else:
        tags_str = ""

    parts = [f"- **{title}**"]
    if arxiv_id:
        parts.append(f"  - ID: {arxiv_id}")
    if tags_str:
        parts.append(f"  - Tags: {tags_str}")
    if summary:
        parts.append(f"  - Summary: {summary}")

    return "\n".join(parts)


def generate_narrative(papers: list[dict], cfg: Config, *, max_papers: int = 10) -> str:
    """Generate a German narrative connecting the day's papers.

    Args:
        papers: List of paper dicts with title, deep_tags, deep_summary, etc.
        cfg: Config object
        max_papers: Maximum number of papers to include (default 10)

    Returns:
        Raw LLM text in German, or empty string on error.
    """
    if not papers:
        log.warning("generate_narrative called with empty papers list")
        return ""

    # Limit papers
    selected = papers[:max_papers]

    # Build paper list for prompt
    paper_list = "\n\n".join(_format_paper_for_prompt(p) for p in selected)

    system_prompt = """Du bist ein wissenschaftlicher Assistent, der Tageszusammenfassungen
von Forschungsarbeiten erstellt. Schreibe einen kurzen, zusammenhängenden
deutschsprachigen Narrative (4-8 Sätze), der die wichtigsten Papers des Tages
verbindet. Achte auf:
- Gemeinsame Themen oder Methoden
- Besonders bemerkenswerte Ergebnisse
- Den Kontext für Quant-Finance-Forschung

Antworte direkt mit dem Narrative, ohne Listen oder Formatierung."""

    user_prompt = f"""Hier sind die wichtigsten Papers vom Tag:

{paper_list}

Schreibe einen deutschen Narrative (4-8 Sätze), der diese Papers verbindet:"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = score._chat(
            messages,
            model=cfg.llm_model,
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
            temperature=0.3,
            max_tokens=800,
        )
        # Strip any think blocks if present
        raw = score._strip_think(raw) if hasattr(score, "_strip_think") else raw
        return raw.strip()
    except Exception as e:
        log.warning("generate_narrative failed: %s", e)
        return ""


def generate_weekly_narrative(papers_by_day: dict[str, list[dict]], cfg: Config) -> str:
    """Generate a German narrative for a week's worth of papers.

    Args:
        papers_by_day: Dict mapping date_str (YYYY-MM-DD) to list of paper dicts
        cfg: Config object

    Returns:
        Raw LLM text in German, or empty string on error.
    """
    if not papers_by_day:
        log.warning("generate_weekly_narrative called with empty papers_by_day")
        return ""

    # Build paper list grouped by day
    day_sections = []
    for date_str in sorted(papers_by_day.keys()):
        day_papers = papers_by_day[date_str][:5]  # Top 5 per day for prompt
        if not day_papers:
            continue
        paper_list = "\n".join(
            f"- {p.get('title', 'Untitled')}" for p in day_papers
        )
        day_sections.append(f"### {date_str}\n{paper_list}")

    if not day_sections:
        return ""

    papers_list_md = "\n\n".join(day_sections)

    system_prompt = """Du bist ein wissenschaftlicher Assistent, der Wochenzusammenfassungen
von Forschungsarbeiten erstellt. Schreibe einen zusammenhängenden
deutschsprachigen Narrative (8-12 Sätze), der die wichtigsten Papers der Woche
zusammenfasst. Achte auf:
- Die wichtigsten Themen und Trends der Woche
- Besonders herausragende Papers
- Methodische Ansätze und deren Bedeutung
- Den Forschungskontext in Quant-Finance

Antworte direkt mit dem Narrative, ohne Listen oder Formatierung."""

    user_prompt = f"""Hier sind die wichtigsten Papers nach Tag geordnet:

{papers_list_md}

Schreibe einen deutschen Narrative (8-12 Sätze), der die Woche zusammenfasst:"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = score._chat(
            messages,
            model=cfg.llm_model,
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
            temperature=0.3,
            max_tokens=1200,
        )
        # Strip any think blocks if present
        raw = score._strip_think(raw) if hasattr(score, "_strip_think") else raw
        return raw.strip()
    except Exception as e:
        log.warning("generate_weekly_narrative failed: %s", e)
        return ""
