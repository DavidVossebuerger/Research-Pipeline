"""Tests for the pipeline runner orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research_pipeline.db import (
    finish_run,
    get_connection,
    get_paper,
    init_schema,
    mark_picked,
    start_run,
    update_abstract_score,
    update_deep_score,
    upsert_paper,
)


@pytest.fixture
def conn(tmp_path):
    """Create an in-memory SQLite database for testing."""
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_papers():
    """Sample papers for testing."""
    return [
        {
            "arxiv_id": "2401.00001",
            "title": "Deep Learning for Finance",
            "authors": ["Alice Smith"],
            "abstract": "We propose a new method...",
            "categories": ["q-fin.TR"],
            "pdf_url": "https://arxiv.org/pdf/2401.00001.pdf",
            "published_at": "2024-01-01T12:00:00Z",
        },
        {
            "arxiv_id": "2401.00002",
            "title": "Quantum Computing Advances",
            "authors": ["Bob Jones"],
            "abstract": "Quantum computing is evolving...",
            "categories": ["quant-ph"],
            "pdf_url": "https://arxiv.org/pdf/2401.00002.pdf",
            "published_at": "2024-01-02T12:00:00Z",
        },
        {
            "arxiv_id": "2401.00003",
            "title": "Machine Learning Survey",
            "authors": ["Charlie Day"],
            "abstract": "A comprehensive survey...",
            "categories": ["cs.LG"],
            "pdf_url": "https://arxiv.org/pdf/2401.00003.pdf",
            "published_at": "2024-01-03T12:00:00Z",
        },
    ]


class TestRunPipeline:
    def test_empty_fetch_returns_zero(self, conn, monkeypatch):
        """Empty fetch should return 0 seen, 0 picked."""
        from research_pipeline.runtime import runner

        # Mock dependencies
        monkeypatch.setattr(runner, "config_module", MagicMock())
        monkeypatch.setattr(runner, "db_module", MagicMock())
        monkeypatch.setattr(runner.fetch_arxiv, "fetch_recent", lambda **k: [])
        monkeypatch.setattr(runner.notify, "send_top_picks", lambda *a, **kw: True)

        # Set up mock config
        mock_cfg = MagicMock()
        mock_cfg.pdf_dir = Path("/tmp/test_pdfs")
        mock_cfg.db_path = Path("/tmp/test.db")
        mock_cfg.score_stage_a_threshold = 7.0
        mock_cfg.score_stage_b_top_k = 10
        mock_cfg.notify_top_k = 3
        monkeypatch.setattr(runner.config_module, "load_config", lambda: mock_cfg)

        # Set up mock db
        mock_conn = MagicMock()
        mock_conn.execute = MagicMock()
        mock_conn.commit = MagicMock()
        mock_conn.close = MagicMock()
        mock_run_id = 1
        monkeypatch.setattr(runner.db_module, "get_connection", lambda x: mock_conn)
        monkeypatch.setattr(runner.db_module, "init_schema", lambda x: None)
        monkeypatch.setattr(runner.db_module, "start_run", lambda x: mock_run_id)
        monkeypatch.setattr(runner.db_module, "finish_run", lambda *a, **kw: None)

        result = runner.run_pipeline(dry_run=True)

        assert result["papers_seen"] == 0
        assert result["papers_picked"] == 0
        assert result["errors"] == []

    def test_fetch_3_papers_above_threshold_picks_top_k(self, conn, monkeypatch, sample_papers):
        """Fetch returns 3 papers, all score above threshold, picks top-K."""
        from research_pipeline.runtime import runner

        mock_cfg = MagicMock()
        mock_cfg.pdf_dir = Path("/tmp/test_pdfs")
        mock_cfg.db_path = Path("/tmp/test.db")
        mock_cfg.score_stage_a_threshold = 5.0
        mock_cfg.score_stage_b_top_k = 10
        mock_cfg.notify_top_k = 2
        mock_cfg.llm_model = "test"
        mock_cfg.llm_base_url = "http://localhost:11434"
        mock_cfg.llm_api_key = ""
        mock_cfg.telegram_bot_token = ""
        mock_cfg.telegram_chat_id = ""
        mock_cfg.telegram_topic_picks = ""

        # Create a real connection for testing
        _db_path = conn.execute("SELECT 1").fetchone()

        def mock_get_connection(path):
            return conn

        def mock_init_schema(c):
            init_schema(c)

        def mock_get_paper(c, arxiv_id):
            return get_paper(c, arxiv_id)

        def mock_update_abstract_score(c, arxiv_id, score, reason, tags):
            update_abstract_score(c, arxiv_id, score, reason, tags)

        def mock_update_deep_score(c, arxiv_id, result):
            update_deep_score(c, arxiv_id, result)

        def mock_mark_picked(c, arxiv_id):
            mark_picked(c, arxiv_id)

        def mock_start_run(c):
            return start_run(c)

        def mock_finish_run(c, run_id, **kw):
            finish_run(c, run_id, **kw)

        # Mock score functions to return high scores
        def mock_score_abstract(paper, *, cfg):
            return {"score": 8.5, "reason": "Relevant to quant finance", "tags": ["trading"]}

        def mock_score_deep(paper, pdf_text, *, cfg):
            return {
                "overall_score": 9.0,
                "novelty": 8.0,
                "rigor": 9.0,
                "reproducibility": 8.5,
                "practical_value": 9.5,
                "summary": "Excellent paper",
                "why_interesting": "Novel approach",
                "tags": ["trading", "deep learning"],
                "analysis": "Good",
            }

        def mock_download_pdf(arxiv_id, pdf_url, cfg):
            # Return a fake Path for testing
            return Path(f"/tmp/fake_{arxiv_id}.pdf")

        def mock_extract_text(path, n=4000):
            return "Sample PDF text for testing purposes"

        # Apply all mocks
        monkeypatch.setattr(runner, "config_module", MagicMock())
        monkeypatch.setattr(runner.config_module, "load_config", lambda: mock_cfg)

        monkeypatch.setattr(runner, "db_module", MagicMock())
        monkeypatch.setattr(runner.db_module, "get_connection", mock_get_connection)
        monkeypatch.setattr(runner.db_module, "init_schema", mock_init_schema)
        monkeypatch.setattr(runner.db_module, "upsert_paper", lambda c, p: upsert_paper(c, p))
        monkeypatch.setattr(runner.db_module, "get_paper", mock_get_paper)
        monkeypatch.setattr(runner.db_module, "update_abstract_score", mock_update_abstract_score)
        monkeypatch.setattr(runner.db_module, "update_deep_score", mock_update_deep_score)
        monkeypatch.setattr(runner.db_module, "mark_picked", mock_mark_picked)
        monkeypatch.setattr(runner.db_module, "start_run", mock_start_run)
        monkeypatch.setattr(runner.db_module, "finish_run", mock_finish_run)

        monkeypatch.setattr(runner.score_module, "score_abstract", mock_score_abstract)
        monkeypatch.setattr(runner.score_module, "score_deep", mock_score_deep)
        monkeypatch.setattr(runner.fetch_arxiv, "fetch_recent", lambda **k: sample_papers)
        monkeypatch.setattr(runner.fetch_arxiv, "download_pdf", mock_download_pdf)
        monkeypatch.setattr(runner.pdf_extract, "extract_first_n_chars", mock_extract_text)

        # Track if notify was called
        notify_called = []
        monkeypatch.setattr(
            runner.notify,
            "send_top_picks",
            lambda picks, date_str, cfg: notify_called.append(picks),
        )

        result = runner.run_pipeline(dry_run=True)

        assert result["papers_seen"] == 3
        assert result["papers_picked"] == 2  # notify_top_k = 2

    def test_llm_errors_populates_errors_list(self, conn, monkeypatch, sample_papers):
        """LLM errors should populate errors list but papers_seen still counts."""
        from research_pipeline.runtime import runner

        mock_cfg = MagicMock()
        mock_cfg.pdf_dir = Path("/tmp/test_pdfs")
        mock_cfg.db_path = Path("/tmp/test.db")
        mock_cfg.score_stage_a_threshold = 5.0
        mock_cfg.score_stage_b_top_k = 10
        mock_cfg.notify_top_k = 2
        mock_cfg.llm_model = "test"
        mock_cfg.llm_base_url = "http://localhost:11434"
        mock_cfg.llm_api_key = ""
        mock_cfg.telegram_bot_token = ""
        mock_cfg.telegram_chat_id = ""
        mock_cfg.telegram_topic_picks = ""

        def mock_get_connection(path):
            return conn

        def mock_init_schema(c):
            init_schema(c)

        def mock_get_paper(c, arxiv_id):
            return get_paper(c, arxiv_id)

        def mock_start_run(c):
            return start_run(c)

        def mock_finish_run(c, run_id, **kw):
            finish_run(c, run_id, **kw)

        # Mock score functions to raise errors
        def mock_score_abstract_error(paper, *, cfg):
            raise RuntimeError("LLM API error")

        def mock_score_deep_error(paper, pdf_text, *, cfg):
            raise RuntimeError("LLM API error")

        monkeypatch.setattr(runner, "config_module", MagicMock())
        monkeypatch.setattr(runner.config_module, "load_config", lambda: mock_cfg)

        monkeypatch.setattr(runner, "db_module", MagicMock())
        monkeypatch.setattr(runner.db_module, "get_connection", mock_get_connection)
        monkeypatch.setattr(runner.db_module, "init_schema", mock_init_schema)
        monkeypatch.setattr(runner.db_module, "upsert_paper", lambda c, p: upsert_paper(c, p))
        monkeypatch.setattr(runner.db_module, "get_paper", mock_get_paper)
        monkeypatch.setattr(runner.db_module, "start_run", mock_start_run)
        monkeypatch.setattr(runner.db_module, "finish_run", mock_finish_run)

        monkeypatch.setattr(runner.score_module, "score_abstract", mock_score_abstract_error)
        monkeypatch.setattr(runner.score_module, "score_deep", mock_score_deep_error)
        monkeypatch.setattr(runner.fetch_arxiv, "fetch_recent", lambda **k: sample_papers[:1])

        result = runner.run_pipeline(dry_run=True)

        # papers_seen should still be 1 even though scoring failed
        assert result["papers_seen"] == 1
        # errors should contain the arxiv_id
        assert "2401.00001" in result["errors"]

    def test_dry_run_skips_notify(self, conn, monkeypatch, sample_papers):
        """dry_run=True should NOT call notify.send_top_picks."""
        from research_pipeline.runtime import runner

        mock_cfg = MagicMock()
        mock_cfg.pdf_dir = Path("/tmp/test_pdfs")
        mock_cfg.db_path = Path("/tmp/test.db")
        mock_cfg.score_stage_a_threshold = 5.0
        mock_cfg.score_stage_b_top_k = 10
        mock_cfg.notify_top_k = 2
        mock_cfg.llm_model = "test"
        mock_cfg.llm_base_url = "http://localhost:11434"
        mock_cfg.llm_api_key = ""
        mock_cfg.telegram_bot_token = ""
        mock_cfg.telegram_chat_id = ""
        mock_cfg.telegram_topic_picks = ""

        def mock_get_connection(path):
            return conn

        def mock_init_schema(c):
            init_schema(c)

        def mock_get_paper(c, arxiv_id):
            return get_paper(c, arxiv_id)

        def mock_update_abstract_score(c, arxiv_id, score, reason, tags):
            update_abstract_score(c, arxiv_id, score, reason, tags)

        def mock_update_deep_score(c, arxiv_id, result):
            update_deep_score(c, arxiv_id, result)

        def mock_mark_picked(c, arxiv_id):
            mark_picked(c, arxiv_id)

        def mock_start_run(c):
            return start_run(c)

        def mock_finish_run(c, run_id, **kw):
            finish_run(c, run_id, **kw)

        def mock_score_abstract(paper, *, cfg):
            return {"score": 8.5, "reason": "Good", "tags": []}

        def mock_score_deep(paper, pdf_text, *, cfg):
            return {
                "overall_score": 9.0,
                "novelty": 8.0,
                "rigor": 8.0,
                "reproducibility": 8.0,
                "practical_value": 8.0,
                "summary": "Good",
                "why_interesting": "Yes",
                "tags": [],
                "analysis": "Good",
            }

        def mock_download_pdf(arxiv_id, pdf_url, cfg):
            return Path(f"/tmp/fake_{arxiv_id}.pdf")

        def mock_extract_text(path, n=4000):
            return "text for testing"

        # Track notify calls
        notify_calls = []

        monkeypatch.setattr(runner, "config_module", MagicMock())
        monkeypatch.setattr(runner.config_module, "load_config", lambda: mock_cfg)

        monkeypatch.setattr(runner, "db_module", MagicMock())
        monkeypatch.setattr(runner.db_module, "get_connection", mock_get_connection)
        monkeypatch.setattr(runner.db_module, "init_schema", mock_init_schema)
        monkeypatch.setattr(runner.db_module, "upsert_paper", lambda c, p: upsert_paper(c, p))
        monkeypatch.setattr(runner.db_module, "get_paper", mock_get_paper)
        monkeypatch.setattr(runner.db_module, "update_abstract_score", mock_update_abstract_score)
        monkeypatch.setattr(runner.db_module, "update_deep_score", mock_update_deep_score)
        monkeypatch.setattr(runner.db_module, "mark_picked", mock_mark_picked)
        monkeypatch.setattr(runner.db_module, "start_run", mock_start_run)
        monkeypatch.setattr(runner.db_module, "finish_run", mock_finish_run)

        monkeypatch.setattr(runner.score_module, "score_abstract", mock_score_abstract)
        monkeypatch.setattr(runner.score_module, "score_deep", mock_score_deep)
        monkeypatch.setattr(runner.fetch_arxiv, "fetch_recent", lambda **k: sample_papers[:1])
        monkeypatch.setattr(runner.fetch_arxiv, "download_pdf", mock_download_pdf)
        monkeypatch.setattr(runner.pdf_extract, "extract_first_n_chars", mock_extract_text)

        monkeypatch.setattr(
            runner.notify, "send_top_picks", lambda *a, **kw: notify_calls.append((a, kw))
        )

        # Run with dry_run=True
        result = runner.run_pipeline(dry_run=True)

        # Notify should NOT have been called
        assert len(notify_calls) == 0
        assert result["papers_seen"] == 1
        assert result["papers_picked"] == 1

    def test_per_paper_failure_in_stage_a_does_not_abort(self, conn, monkeypatch, sample_papers):
        """Per-paper failure in Stage A should not abort the entire run."""
        from research_pipeline.runtime import runner

        mock_cfg = MagicMock()
        mock_cfg.pdf_dir = Path("/tmp/test_pdfs")
        mock_cfg.db_path = Path("/tmp/test.db")
        mock_cfg.score_stage_a_threshold = 5.0
        mock_cfg.score_stage_b_top_k = 10
        mock_cfg.notify_top_k = 2
        mock_cfg.llm_model = "test"
        mock_cfg.llm_base_url = "http://localhost:11434"
        mock_cfg.llm_api_key = ""
        mock_cfg.telegram_bot_token = ""
        mock_cfg.telegram_chat_id = ""
        mock_cfg.telegram_topic_picks = ""

        def mock_get_connection(path):
            return conn

        def mock_init_schema(c):
            init_schema(c)

        def mock_get_paper(c, arxiv_id):
            return get_paper(c, arxiv_id)

        def mock_start_run(c):
            return start_run(c)

        def mock_finish_run(c, run_id, **kw):
            finish_run(c, run_id, **kw)

        call_count = {"count": 0}

        def mock_score_abstract_with_failure(paper, *, cfg):
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise RuntimeError("Simulated error")
            return {"score": 8.5, "reason": "Good", "tags": []}

        monkeypatch.setattr(runner, "config_module", MagicMock())
        monkeypatch.setattr(runner.config_module, "load_config", lambda: mock_cfg)

        monkeypatch.setattr(runner, "db_module", MagicMock())
        monkeypatch.setattr(runner.db_module, "get_connection", mock_get_connection)
        monkeypatch.setattr(runner.db_module, "init_schema", mock_init_schema)
        monkeypatch.setattr(runner.db_module, "upsert_paper", lambda c, p: upsert_paper(c, p))
        monkeypatch.setattr(runner.db_module, "get_paper", mock_get_paper)
        monkeypatch.setattr(runner.db_module, "start_run", mock_start_run)
        monkeypatch.setattr(runner.db_module, "finish_run", mock_finish_run)

        monkeypatch.setattr(runner.score_module, "score_abstract", mock_score_abstract_with_failure)
        monkeypatch.setattr(runner.fetch_arxiv, "fetch_recent", lambda **k: sample_papers[:2])

        result = runner.run_pipeline(dry_run=True)

        # Should have processed both papers despite one failing
        assert result["papers_seen"] == 2
        # The first paper should be in errors
        assert "2401.00001" in result["errors"]


class TestDbHelpers:
    def test_update_abstract_score(self, conn):
        """Test update_abstract_score helper."""
        paper = {
            "arxiv_id": "2401.12345",
            "title": "Test",
            "authors": [],
            "abstract": "Test abstract",
            "categories": ["cs.LG"],
            "pdf_url": "",
            "published_at": "2024-01-01",
        }
        upsert_paper(conn, paper)

        update_abstract_score(conn, "2401.12345", 8.5, "Very relevant", ["trading", "ML"])

        result = get_paper(conn, "2401.12345")
        assert result["abs_score"] == 8.5
        assert result["abs_reason"] == "Very relevant"
        assert json.loads(result["abs_tags"]) == ["trading", "ML"]

    def test_update_deep_score(self, conn):
        """Test update_deep_score helper."""
        paper = {
            "arxiv_id": "2401.12345",
            "title": "Test",
            "authors": [],
            "abstract": "Test abstract",
            "categories": ["cs.LG"],
            "pdf_url": "",
            "published_at": "2024-01-01",
        }
        upsert_paper(conn, paper)

        result = {
            "overall_score": 9.2,
            "summary": "Excellent paper",
            "why_interesting": "Novel approach",
            "tags": ["trading", "quantum"],
            "analysis": "Detailed analysis",
        }
        update_deep_score(conn, "2401.12345", result)

        paper_result = get_paper(conn, "2401.12345")
        assert paper_result["deep_score"] == 9.2
        assert paper_result["deep_summary"] == "Excellent paper"
        assert paper_result["deep_why"] == "Novel approach"
        assert json.loads(paper_result["deep_tags"]) == ["trading", "quantum"]
        assert paper_result["deep_analysis"] == "Detailed analysis"
