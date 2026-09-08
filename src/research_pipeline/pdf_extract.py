"""PDF text extraction utilities."""

from __future__ import annotations

import logging
from pathlib import Path

from pypdf import PdfReader

log = logging.getLogger(__name__)


def extract_text(pdf_path: Path, max_pages: int | None = None) -> str:
    """Extract text from a PDF file.

    Args:
        pdf_path: Path to the PDF file.
        max_pages: Optional limit on number of pages to read. Reads all if None.

    Returns:
        Extracted text with whitespace stripped, or empty string on error.
    """
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as e:
        log.warning("Failed to read PDF %s: %s", pdf_path, e)
        return ""

    pages_to_read = max_pages if max_pages is not None else len(reader.pages)
    text_parts: list[str] = []

    for i in range(pages_to_read):
        if i >= len(reader.pages):
            break
        try:
            page = reader.pages[i]
            text = page.extract_text()
            if text:
                text_parts.append(text)
        except Exception as e:
            log.warning("Failed to extract text from page %d of %s: %s", i, pdf_path, e)

    # Join and normalize whitespace
    full_text = "\n".join(text_parts)
    # Replace multiple whitespace with single space, but preserve paragraphs
    lines = [line.strip() for line in full_text.split("\n")]
    return " ".join(line for line in lines if line)


def extract_first_n_chars(pdf_path: Path, n: int = 4000) -> str:
    """Extract first n characters from a PDF for quick scoring.

    Args:
        pdf_path: Path to the PDF file.
        n: Number of characters to extract (default 4000).

    Returns:
        First n characters of extracted text, or empty string on error.
    """
    text = extract_text(pdf_path)
    return text[:n] if text else text
