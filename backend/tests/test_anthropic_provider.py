from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app.config import Settings
from app.providers.anthropic_provider import AnthropicProvider, parse_response_content
from app.providers.base import ProviderError


def text_block(text, citations=None):
    return SimpleNamespace(type="text", text=text, citations=citations)


def response(content, stop_reason="end_turn", model="claude-opus-5-5"):
    return SimpleNamespace(content=content, stop_reason=stop_reason, model=model)


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def provider_with(responses, **settings):
    messages = FakeMessages(responses)
    client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))
    # Prefixed options are set through their AEO_* aliases
    s = Settings(_env_file=None, anthropic_api_key=None, **{f"AEO_{k.upper()}": v for k, v in settings.items()})
    return AnthropicProvider(s, client=client), messages


def test_not_configured_without_key():
    p = AnthropicProvider(Settings(_env_file=None, anthropic_api_key=None))
    assert not p.is_configured()
    assert "ANTHROPIC_API_KEY" in p.status()["setup_instructions"]
    assert AnthropicProvider(Settings(_env_file=None, anthropic_api_key="sk-test")).is_configured()


def test_status_never_exposes_the_key():
    p = AnthropicProvider(Settings(_env_file=None, anthropic_api_key="sk-secret-value"))
    assert "sk-secret-value" not in repr(p.status())


def test_parse_response_content_collects_citations_and_search_results():
    content = [
        {"type": "server_tool_use", "name": "web_search"},
        {
            "type": "web_search_tool_result",
            "content": [{"type": "web_search_result", "url": "https://a.com", "title": "A"}, {"url": "https://b.com", "title": "B"}],
        },
        {"type": "text", "text": "Acme is great. ", "citations": [{"url": "https://b.com", "title": "B", "cited_text": "quote"}]},
        {"type": "text", "text": "Done.", "citations": None},
        {"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}},
    ]
    text, sources = parse_response_content(content)
    assert text == "Acme is great. Done."
    by_url = {s["url"]: s for s in sources}
    assert by_url["https://a.com"]["type"] == "search_result"
    assert by_url["https://b.com"]["type"] == "cited"
    assert by_url["https://b.com"]["cited_text"] == "quote"


def test_answer_resumes_pause_turn_and_sends_web_search_tool():
    p, msgs = provider_with([response([text_block("Part one. ")], stop_reason="pause_turn"), response([text_block("Part two.")])])
    result = p.answer("best project tools?")
    assert result.text == "Part one. Part two."
    assert len(msgs.calls) == 2
    first = msgs.calls[0]
    assert first["tools"][0]["type"] == "web_search_20260209"
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert msgs.calls[1]["messages"][-1]["role"] == "assistant"


def test_answer_without_web_search_or_fallbacks():
    p, msgs = provider_with([response([text_block("ok")])], anthropic_web_search=False, anthropic_server_fallbacks=False)
    p.answer("q")
    assert "tools" not in msgs.calls[0] and "fallbacks" not in msgs.calls[0]


def test_refusal_and_empty_answers_raise():
    p, _ = provider_with([response([], stop_reason="refusal")])
    with pytest.raises(ProviderError, match="declined"):
        p.answer("q")
    p, _ = provider_with([response([], stop_reason="max_tokens")])
    with pytest.raises(ProviderError, match="no answer text"):
        p.answer("q")


def _api_error(cls, status):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("err", response=httpx2.Response(status, request=req), body=None)


def test_error_mapping():
    p, _ = provider_with([_api_error(anthropic.AuthenticationError, 401)])
    with pytest.raises(ProviderError) as exc:
        p.answer("q")
    assert exc.value.fatal
    p, _ = provider_with([_api_error(anthropic.RateLimitError, 429)])
    with pytest.raises(ProviderError) as exc:
        p.answer("q")
    assert exc.value.retryable and not exc.value.fatal
    p, _ = provider_with([_api_error(anthropic.InternalServerError, 503)])
    with pytest.raises(ProviderError) as exc:
        p.answer("q")
    assert exc.value.retryable
    p, _ = provider_with([anthropic.APITimeoutError(request=httpx2.Request("POST", "https://x"))])
    with pytest.raises(ProviderError, match="timed out"):
        p.answer("q")


def test_complete_json_handles_malformed_output():
    p, _ = provider_with([response([text_block("not json")])])
    with pytest.raises(ProviderError, match="malformed"):
        p.complete_json("s", "p", {"type": "object"})
    p, msgs = provider_with([response([text_block('{"questions": []}')])])
    assert p.complete_json("s", "p", {"type": "object"}) == {"questions": []}
    assert msgs.calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_settings_ignore_unprefixed_shell_variables(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "some-other-model")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy.invalid")
    monkeypatch.setenv("AEO_ANTHROPIC_EFFORT", "high")
    s = Settings(_env_file=None)
    assert s.anthropic_model == "claude-opus-5-5"
    assert s.anthropic_base_url == "https://api.anthropic.com"
    assert s.anthropic_effort == "high"


def test_env_file_takes_priority_over_shell_variables(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-from-env-file\nCRAWL_MAX_PAGES=7\n")
    monkeypatch.delenv("AEO_DISABLE_ENV_FILE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "opencode-shell-key")  # e.g. exported for another tool
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")  # not in .env -> shell value still applies
    s = Settings(_env_file=env_file)
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-from-env-file"
    assert s.crawl_max_pages == 7
    assert s.log_level == "DEBUG"


def test_env_file_can_be_disabled(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-from-env-file\n")
    monkeypatch.setenv("AEO_DISABLE_ENV_FILE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert not Settings(_env_file=env_file).anthropic_configured


def test_default_env_file_path_is_absolute():
    from app.config import ENV_FILE

    assert ENV_FILE.is_absolute() and ENV_FILE.name == ".env" and ENV_FILE.parent.name == "backend"
