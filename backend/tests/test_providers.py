"""Provider adapters: parsing of the documented response shapes, errors, retries, location."""

import json
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.providers.base import ProviderError, SearchLocation
from app.providers.common import parse_json_object, to_dict
from app.providers.gemini_provider import GeminiProvider, parse_interaction
from app.providers.nvidia_provider import NvidiaAnalysisProvider
from app.providers.openai_provider import OpenAIProvider, parse_response
from app.providers.perplexity_provider import PerplexityProvider, parse_agent_response


def settings(**env):
    return Settings(_env_file=None, **env)


class Dumpable:
    """Mimics SDK response objects that expose model_dump()."""

    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


# --------------------------------------------------------------------------- OpenAI (ChatGPT)
OPENAI_RESPONSE = {
    "model": "gpt-5.5-2026-09-01",
    "status": "completed",
    "output": [
        {"type": "web_search_call", "action": {"type": "search", "sources": [
            {"type": "url", "url": "https://agrostar.in/"}, {"type": "url", "url": "https://gkk.example/"}]}},
        {"type": "message", "content": [{"type": "output_text", "text": "Try AgroStar or Gawande Krushi Kendra.",
            "annotations": [{"type": "url_citation", "url": "https://gkk.example/", "title": "GKK", "start_index": 0, "end_index": 5}]}]},
    ],
}


def test_openai_parse_citations_and_sources():
    text, sources = parse_response(OPENAI_RESPONSE)
    assert text == "Try AgroStar or Gawande Krushi Kendra."
    by = {s["url"]: s for s in sources}
    assert by["https://gkk.example/"]["type"] == "cited" and by["https://agrostar.in/"]["type"] == "search_result"


def test_openai_answer_sends_web_search_location_and_include():
    calls = []

    class Responses:
        def create(self, **kw):
            calls.append(kw)
            return Dumpable(OPENAI_RESPONSE)

    p = OpenAIProvider(settings(), client=SimpleNamespace(responses=Responses()))
    ans = p.answer("best agri store in Akola?", location=SearchLocation(city="Akola", country="IN"))
    assert ans.model == "gpt-5.5-2026-09-01" and len(ans.sources) == 2
    tool = calls[0]["tools"][0]
    assert tool == {"type": "web_search", "user_location": {"type": "approximate", "city": "Akola", "country": "IN"}}
    assert calls[0]["include"] == ["web_search_call.action.sources"]


def test_openai_error_mapping():
    import openai

    req = httpx.Request("POST", "https://api.openai.com/v1/responses")

    class Responses:
        def __init__(self, exc):
            self.exc = exc

        def create(self, **kw):
            raise self.exc

    def provider(exc):
        return OpenAIProvider(settings(), client=SimpleNamespace(responses=Responses(exc)))

    with pytest.raises(ProviderError) as e:
        provider(openai.AuthenticationError("bad", response=httpx.Response(401, request=req), body=None)).answer("q")
    assert e.value.fatal
    with pytest.raises(ProviderError) as e:
        provider(openai.RateLimitError("slow", response=httpx.Response(429, request=req), body=None)).answer("q")
    assert e.value.retryable and not e.value.fatal


def test_openai_not_configured_without_key():
    p = OpenAIProvider(settings())
    assert not p.is_configured() and "OPENAI_API_KEY" in p.setup_instructions()
    assert OpenAIProvider(settings(openai_api_key="sk-x")).is_configured()


# --------------------------------------------------------------------------- Gemini
GEMINI_INTERACTION = {
    "steps": [
        {"type": "google_search_call", "arguments": {"queries": ["agri store akola"]}},
        {"type": "model_output", "content": [{"type": "text", "text": "Gawande Krushi Kendra in Akola sells seeds.",
            "annotations": [{"type": "url_citation", "url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc",
                             "title": "gawandekrushikendra.store", "start_index": 0, "end_index": 10}]}]},
    ],
    "output_text": "Gawande Krushi Kendra in Akola sells seeds.",
}


def test_gemini_parse_keeps_redirect_url_and_domain_title():
    text, sources = parse_interaction(GEMINI_INTERACTION)
    assert text.startswith("Gawande") and sources[0]["title"] == "gawandekrushikendra.store" and sources[0]["type"] == "cited"


def test_gemini_answer_calls_interactions_with_google_search():
    calls = []

    class Interactions:
        def create(self, **kw):
            calls.append(kw)
            return Dumpable(GEMINI_INTERACTION)

    p = GeminiProvider(settings(), client=SimpleNamespace(interactions=Interactions()))
    ans = p.answer("best agri store in Akola?")
    assert ans.text.startswith("Gawande") and calls[0]["tools"] == [{"type": "google_search"}]
    assert calls[0]["model"] == "gemini-3.8-flash" and calls[0]["store"] is False


def test_gemini_error_mapping():
    from google.genai import errors

    class Interactions:
        def create(self, **kw):
            raise errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})

    with pytest.raises(ProviderError) as e:
        GeminiProvider(settings(), client=SimpleNamespace(interactions=Interactions())).answer("q")
    assert e.value.retryable


# --------------------------------------------------------------------------- Perplexity
PPLX_RESPONSE = {
    "id": "r1", "object": "response", "status": "completed", "model": "perplexity/sonar-next",
    "output": [
        {"type": "search_results", "results": [{"id": 1, "url": "https://justdial.com/akola/agri", "title": "Agri shops in Akola"}]},
        {"type": "message", "content": [{"type": "output_text", "text": "Top agri stores in Akola: Gawande Krushi Kendra.",
            "annotations": [{"type": "url_citation", "url": "https://justdial.com/akola/agri", "title": "Justdial"}]}]},
    ],
}


def pplx(handler, **env):
    return PerplexityProvider(settings(perplexity_api_key="pplx-test", **env), transport=httpx.MockTransport(handler))


def test_perplexity_parse_and_request_shape():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=PPLX_RESPONSE)

    ans = pplx(handler).answer("best agri store in Akola?")
    assert ans.text.startswith("Top agri stores") and ans.model == "perplexity/sonar-next"
    assert seen["auth"] == "Bearer pplx-test" and seen["body"]["preset"] == "low" and seen["body"]["input"].startswith("best")
    text, sources = parse_agent_response(PPLX_RESPONSE)
    assert sources == [{"url": "https://justdial.com/akola/agri", "title": "Justdial", "type": "cited"}]


def test_perplexity_retries_rate_limits_then_fails_fast_on_auth(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    attempts = []

    def flaky(request):
        attempts.append(1)
        return httpx.Response(429) if len(attempts) < 3 else httpx.Response(200, json=PPLX_RESPONSE)

    assert pplx(flaky).answer("q").text and len(attempts) == 3

    with pytest.raises(ProviderError) as e:
        pplx(lambda r: httpx.Response(401, text="bad key")).answer("q")
    assert e.value.fatal

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderError, match="timed out"):
        pplx(timeout).answer("q")


def test_perplexity_incomplete_or_empty_responses_are_errors():
    with pytest.raises(ProviderError, match="did not complete"):
        pplx(lambda r: httpx.Response(200, json={**PPLX_RESPONSE, "status": "in_progress"})).answer("q")
    with pytest.raises(ProviderError, match="no answer text"):
        pplx(lambda r: httpx.Response(200, json={"status": "completed", "output": []})).answer("q")


def test_perplexity_search_api():
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/search" and body["query"] == "akola directory" and body["country"] == "IN"
        return httpx.Response(200, json={"id": "s", "results": [{"title": "Akola Directory", "url": "https://akoladir.in/", "snippet": "List"}]})

    assert pplx(handler).search("akola directory", country="in") == [{"url": "https://akoladir.in/", "title": "Akola Directory", "snippet": "List"}]


# --------------------------------------------------------------------------- NVIDIA (analysis)
def nvidia_with(content, finish="stop"):
    class Completions:
        def __init__(self):
            self.calls = []

        def create(self, **kw):
            self.calls.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)])

    comps = Completions()
    return NvidiaAnalysisProvider(settings(), client=SimpleNamespace(chat=SimpleNamespace(completions=comps))), comps


def test_nvidia_json_parsing_is_defensive():
    p, comps = nvidia_with('Here you go:\n```json\n{"questions": [{"text": "q", "category": "pricing"}]}\n```')
    assert p.complete_json("sys", "prompt", {"type": "object"}) == {"questions": [{"text": "q", "category": "pricing"}]}
    call = comps.calls[0]
    assert call["model"] == "meta/llama-3.3-70b-instruct" and call["max_tokens"] <= 4096
    assert "JSON Schema" in call["messages"][0]["content"]
    with pytest.raises(ProviderError, match="malformed"):
        nvidia_with("no json here")[0].complete_json("s", "p", {})
    with pytest.raises(ProviderError, match="cut off"):
        nvidia_with('{"a": 1', finish="length")[0].complete_json("s", "p", {})


def test_parse_json_object_and_to_dict():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure! {"a": {"b": 2}} Hope this helps.') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        parse_json_object("[1, 2]")
    assert to_dict(Dumpable({"x": [Dumpable({"y": 1})]})) == {"x": [{"y": 1}]}


def test_analysis_provider_prefers_nvidia_then_claude(monkeypatch):
    from app.providers import registry

    s_none = settings()
    assert registry.analysis_provider(s_none) is None
    assert registry.analysis_provider(settings(anthropic_api_key="sk-ant-x")).name == "anthropic"
    assert registry.analysis_provider(settings(anthropic_api_key="sk-ant-x", nvidia_api_key="nvapi-x")).name == "nvidia"


def test_location_reaches_claude_web_search_tool():
    from app.providers.anthropic_provider import AnthropicProvider

    class Messages:
        def __init__(self):
            self.calls = []

        def create(self, **kw):
            self.calls.append(kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="Answer", citations=None)], stop_reason="end_turn", model="m")

    msgs = Messages()
    p = AnthropicProvider(Settings(_env_file=None, AEO_ANTHROPIC_SERVER_FALLBACKS=False), client=SimpleNamespace(messages=msgs, beta=SimpleNamespace(messages=msgs)))
    p.answer("best dentist?", location=SearchLocation(city="Pune", region="Maharashtra", country="IN"))
    assert msgs.calls[0]["tools"][0]["user_location"] == {"type": "approximate", "city": "Pune", "region": "Maharashtra", "country": "IN"}
