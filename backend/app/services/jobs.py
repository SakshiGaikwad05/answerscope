"""Background jobs: website audits and AI visibility runs.

Jobs run in FastAPI's background thread pool and record progress in the
database, which the frontend polls. This keeps V1 free of a separate queue.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.analysis import audit as audit_analysis
from app.config import get_settings
from app.crawler.crawler import SiteCrawler
from app.crawler.fetcher import FetchError
from app.crawler.url_safety import UnsafeURLError
from app.db import session_scope
from app.models import (
    AuditPage,
    Competitor,
    Mention,
    Project,
    ProviderAnswer,
    Question,
    VisibilityRun,
    WebsiteAudit,
)
from app.providers.base import AIProvider, ProviderError
from app.providers.registry import get_provider
from app.services.recommendations import refresh_recommendations
from app.visibility.detection import EntitySpec, analyze_answer, domain_of

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_crawler() -> SiteCrawler:
    s = get_settings()
    return SiteCrawler(
        user_agent=s.crawl_user_agent,
        max_pages=s.crawl_max_pages,
        timeout=s.crawl_timeout_seconds,
        max_bytes=s.crawl_max_bytes,
        max_redirects=s.crawl_max_redirects,
        max_seconds=s.crawl_max_seconds,
        renderer_factory=_renderer_factory(s),
        render_max_pages=s.render_max_pages,
    )


def _renderer_factory(s):
    """Browser renderer for JavaScript-only sites, if enabled and installed."""
    if not s.render_js:
        return None
    from app.crawler.renderer import PageRenderer, browser_available

    if not browser_available():
        logger.info("JavaScript rendering disabled: Playwright is not installed")
        return None
    return lambda root_host: PageRenderer(root_host, user_agent=s.crawl_user_agent, timeout=s.render_timeout_seconds)


# Tests replace this to avoid real network access.
crawler_factory = make_crawler


def recover_interrupted_jobs(db: Session, statuses: tuple[str, ...] = ("pending", "running")) -> None:
    """Jobs left in these states when their process stopped can never finish; mark them failed.

    Inline mode: the API owns its jobs, so pending and running jobs are both lost on restart.
    Worker mode: the API doesn't touch jobs; the worker fails only the jobs it was running.
    """
    msg = "Interrupted because the server restarted. Please run it again."
    for model in (WebsiteAudit, VisibilityRun):
        db.execute(
            update(model)
            .where(model.status.in_(statuses))
            .values(status="failed", error=msg, completed_at=utcnow())
        )
    db.commit()


def enqueue(background, job, job_id: int) -> None:
    """Run the job in this process (inline mode) or leave it pending for the worker (worker mode)."""
    if get_settings().job_mode == "inline":
        background.add_task(job, job_id)


def claim_next_job(db: Session) -> tuple | None:
    """Atomically claim the oldest pending job (worker mode). Returns (job_function, id) or None."""
    for model, job in ((WebsiteAudit, run_audit_job), (VisibilityRun, run_visibility_job)):
        query = select(model).where(model.status == "pending").order_by(model.id).limit(1)
        if db.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        row = db.scalar(query)
        if row is not None:
            row.status = "running"
            db.commit()
            return job, row.id
    db.rollback()
    return None


# --------------------------------------------------------------------------- audits
def run_audit_job(audit_id: int) -> None:
    with session_scope() as db:
        audit = db.get(WebsiteAudit, audit_id)
        if audit is None:
            return
        project = audit.project
        audit.status = "running"
        audit.progress_message = "Starting crawl"
        db.commit()

        def progress(message: str) -> None:
            audit.progress_message = message
            db.commit()

        crawler = crawler_factory()
        try:
            crawl = crawler.crawl(project.website_url, progress=progress)
            progress("Analyzing pages")
            outcome = audit_analysis.evaluate(crawl, project.brand_name)
            for cp in crawl.pages:
                p = cp.data
                db.add(
                    AuditPage(
                        audit_id=audit.id,
                        url=p.url[:2048],
                        status_code=cp.status_code,
                        title=p.title,
                        meta_description=p.meta_description,
                        canonical=p.canonical,
                        lang=p.lang,
                        h1=p.h1[:10],
                        headings=p.headings[:60],
                        word_count=p.word_count,
                        internal_links=len(p.internal_links),
                        external_links=len(p.external_links),
                        schema_types=p.schema_types,
                        has_faq=p.has_faq,
                        faq_questions=p.faq_questions[:20],
                        issues=outcome.page_issues.get(p.url, []),
                        text_excerpt=p.text[:2000],
                    )
                )
            audit.pages_crawled = len(crawl.pages)
            audit.score = outcome.score
            audit.checks = outcome.checks
            audit.content_gaps = outcome.content_gaps
            audit.site_info = outcome.site_info
            audit.status = "completed"
            audit.progress_message = None
            audit.completed_at = utcnow()
            db.commit()
            logger.info("audit %s completed: %s pages, score %s", audit.id, audit.pages_crawled, audit.score)
        except (FetchError, UnsafeURLError) as exc:
            db.rollback()
            details = (
                exc.as_dict()
                if isinstance(exc, FetchError)
                else {"code": "unsafe_url", "message": str(exc), "url": project.website_url, "status_code": None}
            )
            logger.warning(
                "audit %s failed for %s: code=%s status=%s %s",
                audit.id, project.website_url, details["code"], details["status_code"], details["message"],
            )
            # No score or pages are stored, so a failed fetch can never look like a completed audit.
            audit.site_info = {"error": details}
            _fail(db, audit, details["message"])
            return
        except Exception:  # noqa: BLE001 - record any unexpected failure on the job
            logger.exception("audit %s failed", audit_id)
            db.rollback()
            _fail(db, audit, "Unexpected error while auditing the website. Check the server logs for details.")
            return
        finally:
            crawler.close()
        _safe_refresh(db, project)


def _fail(db: Session, job, message: str) -> None:
    job.status = "failed"
    job.error = message
    job.completed_at = utcnow()
    if hasattr(job, "progress_message"):
        job.progress_message = None
    db.commit()


def _safe_refresh(db: Session, project: Project) -> None:
    try:
        refresh_recommendations(db, project)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to refresh recommendations for project %s", project.id)
        db.rollback()


# --------------------------------------------------------------------------- visibility runs
def build_run_conditions(project: Project, provider: AIProvider, questions: list[Question]) -> dict:
    return {
        **provider.conditions(),
        "brand": project.brand_name,
        "domain": project.domain,
        "competitors": [
            {"id": c.id, "name": c.name, "domain": domain_of(c.website_url)} for c in project.competitors
        ],
        "question_ids": [q.id for q in questions],
    }


def run_visibility_job(run_id: int, max_workers: int = 3) -> None:
    with session_scope() as db:
        run = db.get(VisibilityRun, run_id)
        if run is None:
            return
        project = run.project
        cond = run.conditions
        try:
            provider = get_provider(run.provider)
        except KeyError:
            _fail(db, run, f"Unknown provider {run.provider}")
            return
        if not provider.is_configured():
            _fail(db, run, provider.setup_instructions())
            return

        brand = EntitySpec(name=cond["brand"], entity_type="brand", domain=cond["domain"])
        competitors = [
            EntitySpec(name=c["name"], entity_type="competitor", domain=c.get("domain"), competitor_id=c.get("id"))
            for c in cond.get("competitors", [])
        ]
        valid_competitor_ids = set(db.scalars(select(Competitor.id).where(Competitor.project_id == project.id)))
        questions = list(db.scalars(select(Question).where(Question.id.in_(cond.get("question_ids", [])))))
        questions.sort(key=lambda q: q.id)

        run.status = "running"
        run.total_questions = len(questions)
        db.commit()

        fatal_error: str | None = None
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(provider.answer, q.text): q for q in questions}
            for future in as_completed(futures):
                if future.cancelled():
                    continue
                q = futures[future]
                record = ProviderAnswer(
                    run_id=run.id,
                    question_id=q.id,
                    question_text=q.text,
                    question_category=q.category,
                    provider=run.provider,
                    model=run.model,
                    created_at=utcnow(),
                )
                try:
                    result = future.result()
                except ProviderError as exc:
                    record.error = exc.message
                    if exc.fatal and fatal_error is None:
                        fatal_error = exc.message
                        for f in futures:
                            f.cancel()
                except Exception:  # noqa: BLE001
                    logger.exception("Unexpected provider failure for question %s", q.id)
                    record.error = "Unexpected error while querying the provider."
                else:
                    record.answer_text = result.text
                    record.sources = result.sources
                    record.model = result.model
                    record.latency_ms = result.latency_ms
                    analysis = analyze_answer(result.text, result.sources, brand, competitors)
                    record.brand_mentioned = analysis.brand_mentioned
                    record.website_cited = analysis.website_cited
                    for d in analysis.detections:
                        cid = d["competitor_id"] if d["competitor_id"] in valid_competitor_ids else None
                        record.mentions.append(
                            Mention(
                                entity_type=d["entity_type"],
                                entity_name=d["entity_name"],
                                competitor_id=cid,
                                kind=d["kind"],
                                occurrences=d["occurrences"],
                                evidence=d["evidence"],
                            )
                        )
                db.add(record)
                run.completed_questions += 1
                db.commit()

        successes = db.scalar(
            select(ProviderAnswer.id).where(ProviderAnswer.run_id == run.id, ProviderAnswer.error.is_(None)).limit(1)
        )
        if fatal_error:
            _fail(db, run, fatal_error)
        elif successes is None:
            _fail(db, run, "Every question failed. See individual errors in the results.")
        else:
            run.status = "completed"
            run.completed_at = utcnow()
            db.commit()
        logger.info("run %s finished with status %s", run.id, run.status)
        _safe_refresh(db, project)
