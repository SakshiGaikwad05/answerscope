"""Accounts, per-user isolation, usage quotas, rate limits and the job worker."""

import pytest

from app.api import routes
from app.auth import hash_password, verify_password
from app.config import get_settings
from app.crawler.url_safety import ResolvedTarget, normalize_url
from app.db import session_scope
from app.models import Project, UsageEvent, VisibilityRun, WebsiteAudit
from app.providers import registry
from app.services import jobs
from tests.conftest import login_as
from tests.test_api import FakeCrawler, FakeProvider


def fake_resolve(url):
    normalized = normalize_url(url)
    return ResolvedTarget(url=normalized, scheme="https", host=normalized.split("/")[2], port=443, ip="93.184.216.34")


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    monkeypatch.setattr(routes, "resolve_target", fake_resolve)
    monkeypatch.setattr(jobs, "crawler_factory", lambda: FakeCrawler())
    yield
    registry.override_provider("anthropic", None)


def new_project(client, url="acme.com"):
    r = client.post("/api/projects", json={"website_url": url, "brand_name": "Acme"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------- accounts
def test_password_hashing():
    h = hash_password("s3cret-password")
    assert h.startswith("scrypt$") and "s3cret" not in h
    assert verify_password("s3cret-password", h) and not verify_password("wrong", h)
    assert hash_password("same") != hash_password("same")  # salted
    assert not verify_password("x", "garbage")


def test_register_login_logout_me(anon_client):
    c = anon_client
    assert c.get("/api/auth/me").status_code == 401
    assert c.get("/api/projects").status_code == 401
    r = c.post("/api/auth/register", json={"email": "  Sakshi@Example.COM ", "password": "long-enough-pw"})
    assert r.status_code == 201 and r.json()["email"] == "sakshi@example.com"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert c.get("/api/auth/me").json()["email"] == "sakshi@example.com"
    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/login", json={"email": "sakshi@example.com", "password": "wrong-password"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever-pw"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "SAKSHI@example.com", "password": "long-enough-pw"}).status_code == 200
    assert c.get("/api/auth/me").status_code == 200


def test_registration_validation(anon_client):
    c = anon_client
    assert c.post("/api/auth/register", json={"email": "not-an-email", "password": "long-enough-pw"}).status_code == 422
    assert c.post("/api/auth/register", json={"email": "a@b.co", "password": "short"}).status_code == 422
    assert c.post("/api/auth/register", json={"email": "a@b.co", "password": "long-enough-pw"}).status_code == 201
    assert c.post("/api/auth/register", json={"email": "A@B.co", "password": "long-enough-pw"}).status_code == 409


def test_session_cookie_is_not_stored_in_plain_text(anon_client, engine):
    from sqlalchemy import select

    from app.models import UserSession

    r = anon_client.post("/api/auth/register", json={"email": "a@b.co", "password": "long-enough-pw"})
    token = r.cookies.get("aeo_session") or anon_client.cookies.get("aeo_session")
    with session_scope() as db:
        stored = db.scalars(select(UserSession.token_hash)).all()
    assert token and stored and token not in stored and all(len(h) == 64 for h in stored)


def test_first_account_claims_projects_created_before_accounts(anon_client):
    with session_scope() as db:
        db.add(Project(brand_name="Old", website_url="https://old.com/", domain="old.com"))
        db.commit()
    login_as(anon_client, "first@example.com")
    assert [p["brand_name"] for p in anon_client.get("/api/projects").json()] == ["Old"]


# --------------------------------------------------------------------------- isolation
def test_users_cannot_see_or_change_each_others_data(client, other_client):
    pid = new_project(client)
    audit_id = client.post(f"/api/projects/{pid}/audits").json()["id"]
    rec_id = client.get(f"/api/projects/{pid}/recommendations").json()[0]["id"]

    assert other_client.get("/api/projects").json() == []
    for method, path in [
        ("get", f"/api/projects/{pid}"),
        ("get", f"/api/projects/{pid}/dashboard"),
        ("get", f"/api/projects/{pid}/audits"),
        ("get", f"/api/audits/{audit_id}"),
        ("post", f"/api/projects/{pid}/audits"),
        ("post", f"/api/projects/{pid}/questions/generate"),
        ("get", f"/api/projects/{pid}/recommendations"),
        ("get", f"/api/recommendations/{rec_id}/fixes"),
        ("post", f"/api/recommendations/{rec_id}/fixes"),
        ("delete", f"/api/projects/{pid}"),
    ]:
        assert getattr(other_client, method)(path).status_code == 404, path
    assert other_client.patch(f"/api/recommendations/{rec_id}", json={"status": "dismissed"}).status_code == 404
    assert other_client.put(f"/api/projects/{pid}", json={"competitors": []}).status_code == 404
    # The owner's data is untouched
    assert client.get(f"/api/projects/{pid}").status_code == 200
    assert client.get(f"/api/projects/{pid}/recommendations").json()[0]["status"] == "open"


def test_runs_are_private(client, other_client):
    pid = new_project(client)
    client.post(f"/api/projects/{pid}/questions/generate")
    registry.override_provider("anthropic", FakeProvider())
    run_id = client.post(f"/api/projects/{pid}/runs", json={}).json()["id"]
    assert client.get(f"/api/runs/{run_id}").status_code == 200
    assert other_client.get(f"/api/runs/{run_id}").status_code == 404
    assert other_client.post(f"/api/projects/{pid}/runs", json={}).status_code == 404


# --------------------------------------------------------------------------- quotas
def test_visibility_run_quota_per_user(client, other_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "quota_visibility_runs_per_user_per_day", 1)
    registry.override_provider("anthropic", FakeProvider())
    pid = new_project(client)
    client.post(f"/api/projects/{pid}/questions/generate")
    assert client.post(f"/api/projects/{pid}/runs", json={}).status_code == 202
    r = client.post(f"/api/projects/{pid}/runs", json={})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "quota_exceeded"
    usage = client.get("/api/usage").json()["visibility_run"]
    assert usage == {"used": 1, "limit": 1, "remaining": 0}
    # Another user has their own allowance
    pid2 = new_project(other_client, "globex.com")
    other_client.post(f"/api/projects/{pid2}/questions/generate")
    assert other_client.post(f"/api/projects/{pid2}/runs", json={}).status_code == 202


def test_global_cap_protects_the_server_key(client, other_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "quota_visibility_runs_global_per_day", 1)
    registry.override_provider("anthropic", FakeProvider())
    pid = new_project(client)
    client.post(f"/api/projects/{pid}/questions/generate")
    assert client.post(f"/api/projects/{pid}/runs", json={}).status_code == 202
    pid2 = new_project(other_client, "globex.com")
    other_client.post(f"/api/projects/{pid2}/questions/generate")
    r = other_client.post(f"/api/projects/{pid2}/runs", json={})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "global_quota_exceeded"


def test_failed_validation_does_not_consume_quota(client):
    registry.override_provider("anthropic", FakeProvider())
    pid = new_project(client)
    assert client.post(f"/api/projects/{pid}/runs", json={}).status_code == 400  # no questions yet
    with session_scope() as db:
        assert db.query(UsageEvent).filter_by(kind="visibility_run").count() == 0


def test_template_questions_are_free(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "quota_question_generations_per_user_per_day", 0)
    pid = new_project(client)  # no provider configured -> template questions
    assert client.post(f"/api/projects/{pid}/questions/generate").status_code == 200


# --------------------------------------------------------------------------- rate limits
def test_login_attempts_are_rate_limited(anon_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_auth_per_minute", 3)
    for _ in range(3):
        assert anon_client.post("/api/auth/login", json={"email": "x@y.co", "password": "wrong-pass"}).status_code == 401
    r = anon_client.post("/api/auth/login", json={"email": "x@y.co", "password": "wrong-pass"})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_writes_are_rate_limited_per_user(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_writes_per_minute", 2)
    assert client.post("/api/projects", json={"website_url": "a.com", "brand_name": "A"}).status_code == 201
    assert client.post("/api/projects", json={"website_url": "b.com", "brand_name": "B"}).status_code == 201
    assert client.post("/api/projects", json={"website_url": "c.com", "brand_name": "C"}).status_code == 429


# --------------------------------------------------------------------------- worker mode
def test_worker_mode_queues_jobs_for_the_worker(client, monkeypatch):
    from app import worker

    monkeypatch.setattr(get_settings(), "job_mode", "worker")
    pid = new_project(client)
    audit_id = client.post(f"/api/projects/{pid}/audits").json()["id"]
    assert client.get(f"/api/audits/{audit_id}").json()["status"] == "pending"  # not run by the API
    assert worker.run_once() is True
    assert client.get(f"/api/audits/{audit_id}").json()["status"] == "completed"
    assert worker.run_once() is False  # queue empty


def test_worker_recovery_only_fails_running_jobs(client, engine):
    pid = new_project(client)
    with session_scope() as db:
        db.add_all([WebsiteAudit(project_id=pid, status="running"), WebsiteAudit(project_id=pid, status="pending")])
        db.commit()
        jobs.recover_interrupted_jobs(db, statuses=("running",))
        statuses = sorted(a.status for a in db.query(WebsiteAudit).all())
    assert statuses == ["failed", "pending"]


def test_claim_next_job_takes_audits_then_runs(client):
    pid = new_project(client)
    with session_scope() as db:
        db.add(VisibilityRun(project_id=pid, provider="anthropic", model="m", status="pending", conditions={}))
        db.commit()
        job, job_id = jobs.claim_next_job(db)
        assert job is jobs.run_visibility_job
        assert db.get(VisibilityRun, job_id).status == "running"
        assert jobs.claim_next_job(db) is None
