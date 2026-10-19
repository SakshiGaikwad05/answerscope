"""Retest the same questions and compare runs like-for-like."""

import pytest

from app.api import routes
from app.db import session_scope
from app.models import Question, VisibilityRun
from app.providers import registry
from app.providers.base import AIProvider, ProviderAnswer
from app.services import jobs
from app.visibility.compare import question_key
from tests.test_accounts_and_limits import fake_resolve
from tests.test_api import FakeCrawler


class ScriptedProvider(AIProvider):
    """Answers every question with the same text (configurable per phase)."""

    name = "anthropic"
    display_name = "Scripted"

    def __init__(self, text, model="model-a"):
        self.text, self._model = text, model

    def is_configured(self):
        return True

    def setup_instructions(self):
        return ""

    @property
    def model(self):
        return self._model

    def conditions(self):
        return {"provider": self.name, "model": self._model, "web_search": True}

    def answer(self, question):
        return ProviderAnswer(text=self.text, model=self._model, sources=[])


BEFORE = "I couldn't find any reliable information about Acme. Globex is a popular choice."
AFTER = "Acme is a good option for small teams; Globex is also popular. See https://acme.com/pricing"


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    monkeypatch.setattr(routes, "resolve_target", fake_resolve)
    monkeypatch.setattr(jobs, "crawler_factory", lambda: FakeCrawler())
    yield
    registry.override_provider("anthropic", None)


def setup_project(client):
    pid = client.post("/api/projects", json={"website_url": "acme.com", "brand_name": "Acme", "competitors": ["Globex"]}).json()["id"]
    client.post(f"/api/projects/{pid}/questions/generate")
    return pid


def run_with(client, pid, text, model="model-a", retest_of=None):
    registry.override_provider("anthropic", ScriptedProvider(text, model))
    url = f"/api/runs/{retest_of}/retest" if retest_of else f"/api/projects/{pid}/runs"
    r = client.post(url, json={})
    assert r.status_code == 202, r.text
    run = client.get(f"/api/runs/{r.json()['id']}").json()
    assert run["status"] == "completed", run
    return run


def test_question_key_normalization():
    assert question_key("  What is Acme?  ") == question_key("what is   acme")


def test_retest_reuses_the_exact_questions(client):
    pid = setup_project(client)
    first = run_with(client, pid, BEFORE)
    # The user regenerates questions in between; a retest must still ask the original ones
    client.post(f"/api/projects/{pid}/questions/generate")
    second = run_with(client, pid, AFTER, retest_of=first["id"])
    assert second["conditions"]["retest_of"] == first["id"]
    assert second["conditions"]["question_ids"] == first["conditions"]["question_ids"]
    assert [a["question_text"] for a in second["answers"]] and \
        sorted(a["question_text"] for a in second["answers"]) == sorted(a["question_text"] for a in first["answers"])


def test_compare_reports_deltas_and_per_question_changes(client):
    pid = setup_project(client)
    first = run_with(client, pid, BEFORE)
    second = run_with(client, pid, AFTER, retest_of=first["id"])
    c = client.get(f"/api/projects/{pid}/compare", params={"base": first["id"], "target": second["id"]}).json()
    assert c["comparable"] and c["warnings"] == []
    n = c["questions_compared"]
    assert n == 20 and c["questions_only_in_base"] == 0 and c["one_answer_pts"] == 5.0
    m = {row["key"]: row for row in c["metrics"]}
    assert m["brand_mention_rate"]["base"] == 0.0 and m["brand_mention_rate"]["target"] == 100.0
    assert m["brand_mention_rate"]["delta_pts"] == 100.0 and not m["brand_mention_rate"]["may_be_noise"]
    assert m["website_citation_rate"]["delta_pts"] == 100.0
    assert len(c["question_changes"]["gained_mention"]) == n
    branded = m["branded_known_rate"]
    assert branded["base"] == 0.0 and branded["target"] == 100.0
    # Every "before" answer said the AI couldn't find Acme; every "after" answer knows it
    assert len(c["question_changes"]["now_known"]) == n
    globex = next(e for e in c["entities"] if e["name"] == "Globex")
    assert globex["base_mention_rate"] == globex["target_mention_rate"] == 100.0 and globex["delta_pts"] == 0.0


def test_one_answer_difference_is_flagged_as_possible_noise(client):
    pid = setup_project(client)
    first = run_with(client, pid, BEFORE)
    second = run_with(client, pid, BEFORE, retest_of=first["id"])
    # Flip exactly one answer in the second run to mention the brand
    with session_scope() as db:
        run = db.get(VisibilityRun, second["id"])
        a = next(x for x in run.answers if "Acme" not in x.question_text)
        a.answer_text, a.brand_mentioned = "Acme is worth a look.", True
        db.commit()
    c = client.get(f"/api/projects/{pid}/compare", params={"base": first["id"], "target": second["id"]}).json()
    row = next(r for r in c["metrics"] if r["key"] == "unbranded_mention_rate")
    assert row["answers_changed"] == 1 and row["may_be_noise"] is True
    assert c["question_changes"]["gained_mention"] == [a.question_text]


def test_different_models_are_flagged_as_not_comparable(client):
    pid = setup_project(client)
    first = run_with(client, pid, BEFORE, model="model-a")
    second = run_with(client, pid, AFTER, model="model-b", retest_of=first["id"])
    c = client.get(f"/api/projects/{pid}/compare", params={"base": first["id"], "target": second["id"]}).json()
    assert not c["comparable"] and any("model" in w for w in c["warnings"])


def test_compare_only_uses_shared_questions(client):
    pid = setup_project(client)
    first = run_with(client, pid, BEFORE)
    second = run_with(client, pid, AFTER, retest_of=first["id"])
    with session_scope() as db:  # drop 5 answers from the second run
        run = db.get(VisibilityRun, second["id"])
        for a in run.answers[:5]:
            db.delete(a)
        db.commit()
    c = client.get(f"/api/projects/{pid}/compare", params={"base": first["id"], "target": second["id"]}).json()
    assert c["questions_compared"] == 15 and c["questions_only_in_base"] == 5


def test_compare_validation_and_isolation(client, other_client):
    pid = setup_project(client)
    first = run_with(client, pid, BEFORE)
    assert client.get(f"/api/projects/{pid}/compare", params={"base": first["id"], "target": first["id"]}).status_code == 400
    assert client.get(f"/api/projects/{pid}/compare", params={"base": first["id"], "target": 9999}).status_code == 404
    with session_scope() as db:
        pending = VisibilityRun(project_id=pid, provider="anthropic", model="m", status="running", conditions={})
        db.add(pending)
        db.commit()
        pending_id = pending.id
    assert client.get(f"/api/projects/{pid}/compare", params={"base": first["id"], "target": pending_id}).status_code == 400
    assert other_client.get(f"/api/projects/{pid}/compare", params={"base": first["id"], "target": pending_id}).status_code == 404
    assert other_client.post(f"/api/runs/{first['id']}/retest").status_code == 404


def test_retest_counts_against_the_quota(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "quota_visibility_runs_per_user_per_day", 1)
    pid = setup_project(client)
    first = run_with(client, pid, BEFORE)
    r = client.post(f"/api/runs/{first['id']}/retest")
    assert r.status_code == 429


def test_resolved_action_items_between_runs_are_listed(client, monkeypatch):
    from tests.test_api import FIXED_HOME  # the same homepage, plus FAQ content

    pid = setup_project(client)
    client.post(f"/api/projects/{pid}/audits")
    first = run_with(client, pid, BEFORE)
    monkeypatch.setattr(jobs, "crawler_factory", lambda: _HtmlCrawler(FIXED_HOME))
    client.post(f"/api/projects/{pid}/audits")  # the FAQ item is no longer detected
    second = run_with(client, pid, AFTER, retest_of=first["id"])
    c = client.get(f"/api/projects/{pid}/compare", params={"base": first["id"], "target": second["id"]}).json()
    assert any("FAQ" in item["issue"] for item in c["resolved_between"])


class _HtmlCrawler(FakeCrawler):
    def __init__(self, html):
        super().__init__()
        self.html = html

    def crawl(self, url, progress=None):
        from app.analysis.extract import extract_page
        from app.crawler.crawler import CrawledPage, CrawlResult

        return CrawlResult(start_url=url, root_url=url, pages=[CrawledPage(extract_page(url, self.html), 200)],
                           robots={"found": True, "ai_crawlers": {}}, sitemap={"found": False}, https=True)


def test_question_rows_still_exist_after_regeneration(client):
    pid = setup_project(client)
    client.post(f"/api/projects/{pid}/questions/generate")
    with session_scope() as db:
        assert db.query(Question).filter_by(project_id=pid).count() == 40  # old ones kept (inactive) for retests
