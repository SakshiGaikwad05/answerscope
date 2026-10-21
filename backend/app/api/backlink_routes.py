"""Backlink & brand-mention discovery, tracking and verification."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes import _owned, _project_or_404
from app.auth import current_user
from app.backlinks import discovery
from app.backlinks.search import backend_name, cached_search
from app.config import get_settings
from app.crawler.fetcher import SafeFetcher
from app.crawler.url_safety import site_key
from app.db import get_db
from app.limits import consume_quota, limit_writes
from app.models import BacklinkItem, Project, User
from app.providers.registry import search_backend
from app.schemas import BacklinkCreate, BacklinkOut, BacklinkUpdate
from app.services.recommendations import refresh_recommendations
from app.services.user_keys import user_settings, uses_own_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# Indirection so tests can supply a fetcher with a mock transport.
fetcher_factory = lambda: SafeFetcher(user_agent="AEOAuditBot/0.1 (+backlink verification)", timeout=10, max_bytes=1_500_000)  # noqa: E731

SERVER_SETUP = (
    "Backlink discovery needs a web search API. Set BRAVE_API_KEY (Brave Search API) or PERPLEXITY_API_KEY "
    "(Perplexity Search API) in backend/.env and restart the backend. You can still add pages manually."
)
USER_SETUP = (
    "Backlink discovery needs a web search API. Add a Brave Search or Perplexity API key on the API keys page. "
    "You can still add pages manually."
)


def _setup() -> str:
    return USER_SETUP if get_settings().user_keys_enabled else SERVER_SETUP


def _profile(project: Project) -> discovery.DiscoveryProfile:
    return discovery.DiscoveryProfile(
        brand=project.brand_name, domain=project.domain, category=project.industry,
        city=project.city, region=project.region, country=project.country,
        competitors=[c.name for c in project.competitors],
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/projects/{project_id}/backlinks")
def list_backlinks(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    project = _project_or_404(db, project_id, user)
    items = db.scalars(select(BacklinkItem).where(BacklinkItem.project_id == project.id).order_by(BacklinkItem.id)).all()
    backend = search_backend(user_settings(db, user.id))
    return {
        "search_configured": backend is not None,
        "search_backend": backend_name(backend) if backend else None,
        "setup": None if backend else _setup(),
        "items": [BacklinkOut.model_validate(i).model_dump(mode="json") for i in items],
    }


def _apply(db: Session, project: Project, found: dict) -> BacklinkItem:
    """Insert a newly found page, or update an existing row without overwriting the user's progress."""
    row = db.scalar(select(BacklinkItem).where(BacklinkItem.project_id == project.id, BacklinkItem.url == found["url"]))
    if row is None:
        row = BacklinkItem(project_id=project.id, **found)
        db.add(row)
        return row
    for attr in ("title", "evidence", "link_rel", "value_type", "last_checked_at", "relevance"):
        setattr(row, attr, found[attr])
    row.check_error = None
    if found["kind"] == "existing":
        if row.kind == "opportunity" and row.status != "dismissed":
            # The opportunity now links to / mentions the business: verified after completion
            row.status, row.verified_at = "verified", _now()
        elif row.kind == "existing":
            row.status = "found"
    return row


@router.post("/projects/{project_id}/backlinks/discover", response_model=list[BacklinkOut])
def discover_backlinks(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id, user)
    limit_writes(f"user:{user.id}")
    backend = search_backend(user_settings(db, user.id))
    if backend is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": "search_not_configured", "message": "No search API is configured.", "setup": _setup()})
    consume_quota(db, user, "backlink_discovery", own_key=uses_own_key(db, user.id, backend_name(backend)))
    db.commit()
    fetcher = fetcher_factory()
    try:
        found = discovery.discover(db, backend, _profile(project), cached_search, fetcher=fetcher)
    finally:
        fetcher.close()
    rows = [_apply(db, project, f) for f in found]
    db.commit()
    refresh_recommendations(db, project)
    logger.info("user %s backlink discovery for project %s: %d verified pages", user.id, project.id, len(rows))
    return list_backlinks(project_id, user, db)["items"]


def _recheck(db: Session, row: BacklinkItem) -> BacklinkItem:
    project = row.project
    fetcher = fetcher_factory()
    try:
        check = discovery.check_page(fetcher, row.url, project.brand_name, project.domain)
    finally:
        fetcher.close()
    row.last_checked_at = _now()
    if not check.ok:
        row.check_error = check.error
        return row
    row.check_error = None
    value, rel = discovery.value_and_rel(check)
    present = value != "unknown"
    row.value_type, row.link_rel = value, rel
    row.evidence = ([f"Links to you: {l['href']} (rel: {l['rel']})" for l in check.links_to_site]
                    + [f"Mentions you: {s}" for s in check.mention_snippets]) or [f"Checked {row.last_checked_at:%Y-%m-%d}: no link or mention found"]
    if row.kind == "existing":
        row.status = "found" if present else "not_found"
    elif present:
        row.status, row.verified_at = "verified", row.last_checked_at
    elif row.status in ("completed", "verified"):
        row.status = "not_found"  # marked done, but the page doesn't show the business yet
    return row


@router.post("/projects/{project_id}/backlinks", response_model=BacklinkOut, status_code=status.HTTP_201_CREATED)
def add_backlink(project_id: int, payload: BacklinkCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Track a page you found yourself; it is fetched and checked like discovered ones."""
    project = _project_or_404(db, project_id, user)
    limit_writes(f"user:{user.id}")
    if db.scalar(select(BacklinkItem.id).where(BacklinkItem.project_id == project.id, BacklinkItem.url == payload.url)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This page is already tracked")
    fetcher = fetcher_factory()
    try:
        check = discovery.check_page(fetcher, payload.url, project.brand_name, project.domain)
    finally:
        fetcher.close()
    if not check.ok:
        raise HTTPException(422, f"Couldn't load that page: {check.error}")
    value, rel = discovery.value_and_rel(check)
    existing = value != "unknown"
    category = discovery.classify(check.url, check.title or "", check.text)
    row = BacklinkItem(
        project_id=project.id, kind="existing" if existing else "opportunity", status="found" if existing else "suggested",
        url=check.url, domain=site_key(urlsplit(check.url).hostname or ""), title=check.title, category=category,
        submission_url=None if existing else check.submission_url, relevance=discovery.relevance_note(check, _profile(project)),
        why_it_helps=discovery.WHY[category], value_type=value, link_rel=rel, discovered_via="added manually",
        evidence=[f"Links to you: {l['href']} (rel: {l['rel']})" for l in check.links_to_site] + [f"Mentions you: {s}" for s in check.mention_snippets],
        outreach=None if existing else discovery.outreach_message(category, _profile(project), check.title),
        last_checked_at=_now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/backlinks/{item_id}", response_model=BacklinkOut)
def update_backlink(item_id: int, payload: BacklinkUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = _owned(db.get(BacklinkItem, item_id), user, "Item")
    if payload.status is not None and payload.status != row.status:
        if row.kind == "existing":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Existing links and mentions are updated by re-checking, not by hand")
        row.status, row.status_updated_at = payload.status, _now()
    if "note" in payload.model_fields_set:
        row.note = (payload.note or "").strip() or None
    db.commit()
    db.refresh(row)
    return row


@router.post("/backlinks/{item_id}/verify", response_model=BacklinkOut)
def verify_backlink(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Re-fetch the page and record whether it now links to or mentions the business."""
    row = _owned(db.get(BacklinkItem, item_id), user, "Item")
    limit_writes(f"user:{user.id}")
    _recheck(db, row)
    db.commit()
    db.refresh(row)
    refresh_recommendations(db, row.project)
    return row


@router.delete("/backlinks/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backlink(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    row = _owned(db.get(BacklinkItem, item_id), user, "Item")
    db.delete(row)
    db.commit()
