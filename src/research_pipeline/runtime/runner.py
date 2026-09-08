"""Pipeline runner orchestrator — fetch, score, notify."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from research_pipeline import config as config_module
from research_pipeline import db as db_module
from research_pipeline import fetch_arxiv
from research_pipeline import notify
from research_pipeline import pdf_extract
from research_pipeline import score as score_module
from research_pipeline.logging_setup import setup_logging
from research_pipeline.config import Config

logger = setup_logging("research_pipeline")

# Max workers for parallel scoring
MAX_SCORE_WORKERS = 4


def run_pipeline(
    *,
    dry_run: bool = False,
    lookback_hours: int | None = None,
    max_papers: int | None = None,
) -> dict:
    """Run the full research pipeline: fetch → score (abstract) → score (deep) → notify.

    Args:
        dry_run: If True, don't actually send notifications
        lookback_hours: Override default lookback window
        max_papers: Override default max papers to fetch

    Returns:
        dict with keys: papers_seen, papers_picked, errors
    """
    errors: list[str] = []
    papers_seen = 0
    papers_picked = 0
    run_id = None

    try:
        # Step 1: Init
        cfg = config_module.load_config()
        cfg.pdf_dir.mkdir(parents=True, exist_ok=True)

        conn = db_module.get_connection(cfg.db_path)
        db_module.init_schema(conn)

        # Step 2: Run lifecycle
        run_id = db_module.start_run(conn)
        conn.commit()

        logger.info("Pipeline run started (run_id=%d)", run_id)

        # Step 3: Fetch
        papers = fetch_arxiv.fetch_recent(lookback_hours=lookback_hours, cfg=cfg)
        if max_papers:
            papers = papers[:max_papers]

        papers_seen = len(papers)
        logger.info("Fetched %d papers", papers_seen)

        # Step 4: Persist + Stage A (abstract scoring)
        for paper in papers:
            db_module.upsert_paper(conn, paper)
        conn.commit()

        # Score abstracts in parallel
        stage_a_papers = []
        with ThreadPoolExecutor(max_workers=MAX_SCORE_WORKERS) as executor:
            futures = {}
            for paper in papers:
                # Check if already has abs_score
                existing = db_module.get_paper(conn, paper["arxiv_id"])
                if existing and existing.get("abs_score") is not None:
                    stage_a_papers.append(paper)
                    continue

                future = executor.submit(
                    _score_abstract_safe, paper, cfg
                )
                futures[future] = paper

            for future in as_completed(futures):
                paper = futures[future]
                try:
                    result = future.result()
                    if result is not None:
                        db_module.update_abstract_score(
                            conn,
                            paper["arxiv_id"],
                            result["score"],
                            result["reason"],
                            result["tags"],
                        )
                        stage_a_papers.append(paper)
                    else:
                        errors.append(paper["arxiv_id"])
                except Exception as e:
                    logger.warning(
                        "Stage A error for %s: %s",
                        paper["arxiv_id"],
                        str(e),
                    )
                    errors.append(paper["arxiv_id"])

        conn.commit()
        logger.info("Stage A (abstract scoring) complete: %d papers scored", len(stage_a_papers))

        # Step 5: Stage B (deep scoring)
        # Filter by threshold and take top-k
        stage_b_papers = []
        for paper in stage_a_papers:
            existing = db_module.get_paper(conn, paper["arxiv_id"])
            if existing and existing.get("abs_score", 0) >= cfg.score_stage_a_threshold:
                stage_b_papers.append((existing["abs_score"], paper))

        stage_b_papers.sort(key=lambda x: x[0], reverse=True)
        stage_b_papers = [p for _, p in stage_b_papers[: cfg.score_stage_b_top_k]]

        logger.info(
            "Stage B: %d papers above threshold, taking top %d",
            len(stage_b_papers),
            cfg.score_stage_b_top_k,
        )

        # Download PDFs and score deeply in parallel
        deep_scored_papers = []
        with ThreadPoolExecutor(max_workers=MAX_SCORE_WORKERS) as executor:
            futures = {}
            for paper in stage_b_papers:
                future = executor.submit(
                    _score_deep_safe, paper, cfg
                )
                futures[future] = paper

            for future in as_completed(futures):
                paper = futures[future]
                try:
                    result = future.result()
                    if result is not None:
                        db_module.update_deep_score(conn, paper["arxiv_id"], result)
                        deep_scored_papers.append((result.get("overall_score", 0), paper))
                    else:
                        errors.append(f"{paper['arxiv_id']} (deep)")
                except Exception as e:
                    logger.warning(
                        "Stage B error for %s: %s",
                        paper["arxiv_id"],
                        str(e),
                    )
                    errors.append(f"{paper['arxiv_id']} (deep)")

        conn.commit()
        logger.info("Stage B (deep scoring) complete: %d papers scored", len(deep_scored_papers))

        # Step 6: Pick
        # Filter by threshold and take top-k
        picks = []
        for score, paper in deep_scored_papers:
            if score >= cfg.score_stage_a_threshold:
                picks.append((score, paper))

        picks.sort(key=lambda x: x[0], reverse=True)
        picks = [p for _, p in picks[: cfg.notify_top_k]]

        # Mark as picked
        for paper in picks:
            db_module.mark_picked(conn, paper["arxiv_id"])
        conn.commit()

        papers_picked = len(picks)
        logger.info("Picked %d papers (top %d)", papers_picked, cfg.notify_top_k)

        # Step 7: Notify
        date_str = datetime.now().strftime("%Y-%m-%d")
        if dry_run:
            logger.info("[DRY RUN] Would send %d picks: %s", papers_picked, [p["title"] for p in picks])
        else:
            # Prepare pick dicts for notify
            pick_dicts = []
            for paper in picks:
                existing = db_module.get_paper(conn, paper["arxiv_id"])
                if existing:
                    pick_dicts.append(existing)
            notify.send_top_picks(pick_dicts, date_str=date_str, cfg=cfg)

        # Step 8: Finish
        db_module.finish_run(
            conn,
            run_id,
            papers_seen=papers_seen,
            papers_picked=papers_picked,
        )
        conn.commit()

        logger.info(
            "Pipeline run finished: seen=%d, picked=%d, errors=%d",
            papers_seen,
            papers_picked,
            len(errors),
        )

    except Exception as e:
        logger.exception("Pipeline run failed: %s", e)
        if conn and run_id is not None:
            try:
                db_module.finish_run(
                    conn,
                    run_id,
                    papers_seen=0,
                    papers_picked=0,
                    error=str(e),
                )
                conn.commit()
            except Exception:
                pass
        return {"papers_seen": papers_seen, "papers_picked": 0, "errors": errors + [str(e)]}

    finally:
        if conn:
            conn.close()

    return {"papers_seen": papers_seen, "papers_picked": papers_picked, "errors": errors}


def _score_abstract_safe(paper: dict, cfg: Config) -> dict | None:
    """Score paper abstract, returning None on error."""
    try:
        return score_module.score_abstract(paper, cfg=cfg)
    except Exception as e:
        logger.warning("Abstract scoring failed for %s: %s", paper["arxiv_id"], e)
        return None


def _score_deep_safe(paper: dict, cfg: Config) -> dict | None:
    """Download PDF and score deeply, returning None on error."""
    try:
        arxiv_id = paper["arxiv_id"]
        pdf_url = paper.get("pdf_url", "")
        pdf_path = fetch_arxiv.download_pdf(arxiv_id, pdf_url, cfg)
        if pdf_path is None:
            logger.warning("PDF download failed for %s", arxiv_id)
            return None

        pdf_text = pdf_extract.extract_first_n_chars(pdf_path, n=4000)
        if not pdf_text:
            logger.warning("PDF text extraction failed for %s", arxiv_id)
            return None

        return score_module.score_deep(paper, pdf_text, cfg=cfg)
    except Exception as e:
        logger.warning("Deep scoring failed for %s: %s", paper["arxiv_id"], e)
        return None
