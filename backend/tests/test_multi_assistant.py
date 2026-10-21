"""Multi-assistant runs, position in lists, location relevance, and AI entity extraction."""

import pytest

from app.api import routes
from app.config import get_settings
from app.providers import registry
from app.providers.base import AIProvider, ProviderAnswer
from app.services import jobs
from app.visibility.detection import EntitySpec
from app.visibility.extraction import extract_businesses
from app.visibility.position import brand_position, list_items, location_terms, mentions_location
from tests.test_accounts_and_limits import fake_resolve
from tests.test_api import FakeCrawler

LIST_ANSWER = """Here are good agri stores in Akola:

1. **AgroStar Kendra** - wide range of seeds
2. **Gawande Krushi Kendra** - fertilizers and expert advice
3. BigHaat partner store

All are in Akola, Maharashtra."""


class Scripted(AIProvider):
    def __init__(self, name, assistant, text, location_aware=False):
        self.name, self.assistant, self.text = name, assistant, text
        self.display_name = assistant
        self.supports_location = location_aware
        self.locations = []

    def is_configured(self):
        return True

    def setup_instructions(self):
        return ""

    @property
    def model(self):
        return f"{self.name}-model"

    def answer(self, question, location=None):
        self.locations.append(location)
        return ProviderAnswer(text=self.text, model=self.model, sources=[])


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    monkeypatch.setattr(routes, "resolve_target", fake_resolve)
    monkeypatch.setattr(jobs, "crawler_factory", lambda: FakeCrawler())
    yield
    for name in ("openai", "anthropic", "gemini", "perplexity", "nvidia"):
        registry.override_provider(name, None)


# --------------------------------------------------------------------------- pure functions
def test_list_items_and_position():
    brand = EntitySpec(name="Gawande Krushi Kendra", entity_type="brand", domain="gkk.example")
    assert len(list_items(LIST_ANSWER)) == 3
    assert brand_position(LIST_ANSWER, brand) == {"position": 2, "listed": 3}
    assert brand_position("1. AgroStar\n2. BigHaat", brand) == {"position": None, "listed": 2}  # listed, but not you
    assert brand_position("Gawande Krushi Kendra is a good choice.", brand) is None  # no list: not determinable
    assert brand_position("- only one item", brand) is None


def test_location_relevance():
    terms = location_terms({"city": "Akola", "service_area": "Akola district, Washim"})
    assert terms == ["Akola", "Akola district", "Washim"]
    assert mentions_location(LIST_ANSWER, terms) is True
    assert mentions_location("Try AgroStar in Pune.", terms) is False
    assert mentions_location("anything", []) is None  # no location on file -> unknown, not "no"


def test_extraction_drops_businesses_not_in_the_answer():
    class Fake:
        def complete_json(self, system, prompt, schema):
            return {"businesses": [{"name": "AgroStar Kendra", "position": 1}, {"name": "Invented Agro Mart", "position": 2},
                                   {"name": "Gawande Krushi Kendra", "position": 3}, {"name": "agrostar kendra", "position": 4}]}

    assert extract_businesses(Fake(), "q", LIST_ANSWER) == [
        {"name": "AgroStar Kendra", "position": 1}, {"name": "Gawande Krushi Kendra", "position": 2}]


# --------------------------------------------------------------------------- API
def setup(client, **local):
    body = {"website_url": "gkk.example", "brand_name": "Gawande Krushi Kendra", "competitors": ["BigHaat"],
            "industry": "agricultural supplies store", **local}
    pid = client.post("/api/projects", json=body).json()["id"]
    client.post(f"/api/projects/{pid}/questions/generate")
    return pid


def test_multi_run_creates_one_run_per_configured_assistant(client):
    chatgpt = Scripted("openai", "ChatGPT", LIST_ANSWER, location_aware=True)
    claude = Scripted("anthropic", "Claude", "I couldn't find any reliable information about Gawande Krushi Kendra.")
    registry.override_provider("openai", chatgpt)
    registry.override_provider("anthropic", claude)
    pid = setup(client, city="Akola", region="Maharashtra", country="IN")
    r = client.post(f"/api/projects/{pid}/runs/multi", json={})
    assert r.status_code == 202, r.text
    runs = {x["provider"]: x for x in r.json()}
    assert set(runs) == {"openai", "anthropic"}  # Gemini/Perplexity aren't configured, so not run
    gpt = client.get(f"/api/runs/{runs['openai']['id']}").json()
    assert gpt["conditions"]["location"] == {"city": "Akola", "region": "Maharashtra", "country": "IN"}
    loc = chatgpt.locations[0]
    assert (loc.city, loc.country) == ("Akola", "IN")  # location-aware assistants get the location
    m = gpt["metrics"]
    assert m["answers_with_list"] == 20 and m["average_position"] == 2.0 and m["top3_count"] == 20
    assert m["location_relevance_rate"] == 100.0
    a = gpt["answers"][0]
    assert a["position"] == 2 and a["listed"] == 3 and a["location_mentioned"] is True
    cl = client.get(f"/api/runs/{runs['anthropic']['id']}").json()["metrics"]
    assert cl["average_position"] is None and cl["answers_with_list"] == 0 and cl["branded_unknown"] > 0


def test_multi_run_quota_is_checked_for_all_assistants_up_front(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "quota_visibility_runs_per_user_per_day", 1)
    registry.override_provider("openai", Scripted("openai", "ChatGPT", LIST_ANSWER))
    registry.override_provider("anthropic", Scripted("anthropic", "Claude", LIST_ANSWER))
    pid = setup(client)
    r = client.post(f"/api/projects/{pid}/runs/multi", json={})
    assert r.status_code == 429 and "needs 2" in r.json()["detail"]["message"]
    assert client.get(f"/api/projects/{pid}/runs").json() == []  # nothing half-started


def test_multi_run_without_any_assistant_configured(client):
    pid = setup(client)
    r = client.post(f"/api/projects/{pid}/runs/multi", json={})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "provider_not_configured"


def test_nvidia_extraction_finds_untracked_competitors(client):
    class FakeNvidia:
        name, model = "nvidia", "meta/llama-3.3-70b-instruct"

        def is_configured(self):
            return True

        def complete_json(self, system, prompt, schema):
            if "Extract" in system or "extract" in system:
                return {"businesses": [{"name": "AgroStar Kendra", "position": 1}, {"name": "Gawande Krushi Kendra", "position": 2},
                                       {"name": "BigHaat", "position": 3}, {"name": "Ghost Store", "position": 4}]}
            raise AssertionError("unexpected call")

    registry.override_provider("openai", Scripted("openai", "ChatGPT", LIST_ANSWER))
    pid = setup(client)
    registry.override_provider("nvidia", FakeNvidia())
    run_id = client.post(f"/api/projects/{pid}/runs/multi", json={"providers": ["openai"]}).json()[0]["id"]
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["answers"][0]["recommended_businesses"][0] == {"name": "AgroStar Kendra", "position": 1}
    others = run["metrics"]["other_businesses"]
    assert others == [{"name": "AgroStar Kendra", "answers": 20}]  # tracked brands and invented names excluded


def test_extraction_is_skipped_without_nvidia(client):
    registry.override_provider("openai", Scripted("openai", "ChatGPT", LIST_ANSWER))
    pid = setup(client)
    run_id = client.post(f"/api/projects/{pid}/runs/multi", json={"providers": ["openai"]}).json()[0]["id"]
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["answers"][0]["recommended_businesses"] is None and run["metrics"]["answers_analyzed"] == 0


def test_overview_score_excludes_untested_assistants(client):
    registry.override_provider("openai", Scripted("openai", "ChatGPT", LIST_ANSWER))  # mentions the brand
    registry.override_provider("anthropic", Scripted("anthropic", "Claude", "Try AgroStar Kendra."))  # never mentions it
    pid = setup(client, city="Akola")
    client.post(f"/api/projects/{pid}/runs/multi", json={})
    ov = client.get(f"/api/projects/{pid}/dashboard").json()["overview"]
    rows = {a["provider"]: a for a in ov["assistants"]}
    assert rows["openai"]["metrics"]["unbranded_mention_rate"] == 100.0 and rows["anthropic"]["metrics"]["unbranded_mention_rate"] == 0.0
    assert ov["ai_visibility"]["score"] == 50.0  # (100 + 0) / 2: Gemini and Perplexity not counted
    assert {e.split(":")[0] for e in ov["ai_visibility"]["excluded"]} == {"Gemini", "Perplexity"}
    assert rows["gemini"]["configured"] is False and "GEMINI_API_KEY" in rows["gemini"]["setup"]
    assert ov["website_health"]["score"] is None and ov["local_seo"]["score"] is None and ov["local_seo"]["note"]


def test_overview_without_any_runs_has_no_score(client):
    pid = setup(client)
    ov = client.get(f"/api/projects/{pid}/dashboard").json()["overview"]
    assert ov["ai_visibility"]["score"] is None and len(ov["ai_visibility"]["excluded"]) == 4


def test_action_plan_combines_all_assistants_with_labelled_evidence(client):
    registry.override_provider("openai", Scripted("openai", "ChatGPT", LIST_ANSWER))
    registry.override_provider("anthropic", Scripted("anthropic", "Claude", "Try AgroStar Kendra or BigHaat."))
    pid = setup(client)
    client.post(f"/api/projects/{pid}/runs/multi", json={})
    recs = {r["key"]: r for r in client.get(f"/api/projects/{pid}/recommendations").json()}
    # Counts combine both assistants: BigHaat in 20 + 20 answers, the brand only in ChatGPT's 20
    assert "(40 vs 20 of 40 answers)" in recs["competitors:bighaat"]["issue"]
    assert any(e.startswith('BigHaat mentioned, Gawande Krushi Kendra not: "[Claude]') for e in recs["competitors:bighaat"]["evidence"])
    unprompted = recs.get("visibility:unprompted")
    if unprompted:  # if raised, its evidence must say which assistant each example came from
        assert all(e.startswith("Not mentioned: \"[") for e in unprompted["evidence"])
