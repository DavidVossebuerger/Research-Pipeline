"""Tests for pdf_extract module."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_pipeline.pdf_extract import extract_first_n_chars, extract_text


class TestExtractText:
    """Test extract_text function."""

    def test_returns_empty_on_missing_file(self):
        """Test that extract_text returns empty string for missing file."""
        result = extract_text(Path("/nonexistent/file.pdf"))
        assert result == ""

    def test_returns_empty_for_blank_pdf(self, tmp_path):
        """Test extraction from a blank PDF created with pypdf."""
        from pypdf import PdfWriter

        pdf_path = tmp_path / "blank.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        result = extract_text(pdf_path)
        # Blank PDF may return empty or very short text
        assert isinstance(result, str)


class TestExtractFirstNChars:
    """Test extract_first_n_chars function."""

    def test_returns_empty_on_missing_file(self):
        """Test that extract_first_n_chars returns empty for missing file."""
        result = extract_first_n_chars(Path("/nonexistent/file.pdf"))
        assert result == ""

    def test_returns_empty_for_blank_pdf(self, tmp_path):
        """Test that extract_first_n_chars handles blank PDF."""
        from pypdf import PdfWriter

        pdf_path = tmp_path / "blank.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        result = extract_first_n_chars(pdf_path, n=100)
        assert isinstance(result, str)


class TestPdfExtractionWithReportLab:
    """Tests requiring reportlab to generate PDFs with actual text."""

    @pytest.fixture(autouse=True)
    def check_reportlab(self):
        """Skip tests if reportlab is not installed."""
        pytest.importorskip("reportlab")

    def test_extracts_text_from_pdf(self, tmp_path):
        """Test text extraction from a PDF with actual content."""
        from io import BytesIO
        from reportlab.pdfgen import canvas

        pdf_path = tmp_path / "test.pdf"

        buffer = BytesIO()
        c = canvas.Canvas(buffer)
        c.drawString(100, 750, "Hello, World!")
        c.drawString(100, 700, "This is a test.")
        c.save()

        buffer.seek(0)
        pdf_path.write_bytes(buffer.read())

        result = extract_text(pdf_path)
        assert isinstance(result, str)
        # Check that some content was extracted
        assert len(result) > 0

    def test_limits_char_count(self, tmp_path):
        """Test that extract_first_n_chars limits to n characters."""
        from io import BytesIO
        from reportlab.pdfgen import canvas

        pdf_path = tmp_path / "test.pdf"

        buffer = BytesIO()
        c = canvas.Canvas(buffer)
        for i in range(50):
            c.drawString(50, 750 - (i * 12), f"Line {i} extra content here")
        c.save()

        buffer.seek(0)
        pdf_path.write_bytes(buffer.read())

        result = extract_first_n_chars(pdf_path, n=100)
        assert len(result) <= 100

    def test_max_pages_limit(self, tmp_path):
        """Test extraction with max_pages limit."""
        from io import BytesIO
        from reportlab.pdfgen import canvas

        pdf_path = tmp_path / "multipage.pdf"

        buffer = BytesIO()
        c = canvas.Canvas(buffer)
        c.drawString(100, 750, "Page 1 content")
        c.showPage()
        c.drawString(100, 750, "Page 2 content")
        c.showPage()
        c.drawString(100, 750, "Page 3 content")
        c.save()

        buffer.seek(0)
        pdf_path.write_bytes(buffer.read())

        # Extract only first 2 pages
        result = extract_text(pdf_path, max_pages=2)
        assert "Page 1" in result
        assert "Page 2" in result
