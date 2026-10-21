"""Users' own API keys: encrypted storage, masking, isolation, per-user providers and quotas."""

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from app.api import routes
from app.config import get_settings
from app.db import session_scope
from app.models import UsageEvent, UserApiKey
from app.services import jobs, user_keys
from tests.test_accounts_and_limits import fake_resolve
from tests.test_multi_assistant import setup

OPENAI_KEY = "sk-test-0123456789abcdefWXYZ"


@pytest.fixture()
def keys_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "secrets_key", SecretStr(Fernet.generate_key().decode()))
    monkeypatch.setattr(s, "use_server_api_keys", False)
    monkeypatch.setattr(user_keys, "key_checker", lambda provider, key: True if provider == "openai" else None)
    monkeypatch.setattr(routes, "resolve_target", fake_resolve)
    monkeypatch.setattr(jobs, "enqueue", lambda *a, **k: None)  # never call a real provider
    return s


def _key(body, provider):
    return next(k for k in body["keys"] if k["provider"] == provider)


def test_saving_is_disabled_without_server_secret(client):
    assert client.get("/api/keys").json()["enabled"] is False
    r = client.put("/api/keys/openai", json={"api_key": OPENAI_KEY})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "user_keys_disabled"


def test_key_is_encrypted_masked_and_used_only_for_its_owner(client, other_client, keys_on):
    r = client.put("/api/keys/openai", json={"api_key": f"  {OPENAI_KEY}  "})
    assert r.status_code == 200, r.text
    assert OPENAI_KEY not in r.text
    k = _key(r.json(), "openai")
    assert k["saved"] and k["last4"] == "WXYZ" and k["verified"] is True
    assert OPENAI_KEY not in client.get("/api/keys").text
    with session_scope() as db:
        row = db.scalar(select(UserApiKey))
        assert OPENAI_KEY not in row.ciphertext
        assert Fernet(keys_on.secrets_key.get_secret_value()).decrypt(row.ciphertext.encode()).decode() == OPENAI_KEY

    mine = {p["name"]: p["configured"] for p in client.get("/api/providers").json()}
    theirs = {p["name"]: p["configured"] for p in other_client.get("/api/providers").json()}
    assert mine["openai"] is True and theirs["openai"] is False
    assert not _key(other_client.get("/api/keys").json(), "openai")["saved"]


def test_server_keys_are_not_used_when_disabled(client, keys_on, monkeypatch):
    monkeypatch.setattr(keys_on, "anthropic_api_key", SecretStr("server-anthropic-key-123456"))
    providers = {p["name"]: p for p in client.get("/api/providers").json()}
    assert providers["anthropic"]["configured"] is False
    assert "API keys page" in providers["anthropic"]["setup_instructions"]
    monkeypatch.setattr(keys_on, "use_server_api_keys", True)
    assert {p["name"]: p["configured"] for p in client.get("/api/providers").json()}["anthropic"] is True


def test_rejected_and_malformed_keys_are_not_saved(client, keys_on, monkeypatch):
    monkeypatch.setattr(user_keys, "key_checker", lambda provider, key: False)
    r = client.put("/api/keys/openai", json={"api_key": OPENAI_KEY})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "key_rejected"
    r = client.put("/api/keys/openai", json={"api_key": "sk short"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_key_format"
    assert client.put("/api/keys/nope", json={"api_key": OPENAI_KEY}).status_code == 404
    assert not _key(client.get("/api/keys").json(), "openai")["saved"]


def test_unchecked_key_is_saved_as_unverified(client, keys_on):
    r = client.put("/api/keys/perplexity", json={"api_key": "pplx-abcdefghijklmnop1234"})
    k = _key(r.json(), "perplexity")
    assert k["saved"] and k["verified"] is None


def test_changed_server_secret_asks_for_reentry(client, keys_on, monkeypatch):
    client.put("/api/keys/openai", json={"api_key": OPENAI_KEY})
    monkeypatch.setattr(keys_on, "secrets_key", SecretStr(Fernet.generate_key().decode()))
    k = _key(client.get("/api/keys").json(), "openai")
    assert k["saved"] is False and k["needs_reentry"] is True
    assert {p["name"]: p["configured"] for p in client.get("/api/providers").json()}["openai"] is False


def test_delete_key(client, keys_on):
    client.put("/api/keys/openai", json={"api_key": OPENAI_KEY})
    assert client.delete("/api/keys/openai").status_code == 204
    assert not _key(client.get("/api/keys").json(), "openai")["saved"]


def test_own_key_runs_skip_the_global_cap(client, keys_on, monkeypatch):
    monkeypatch.setattr(keys_on, "quota_visibility_runs_global_per_day", 0)
    client.put("/api/keys/openai", json={"api_key": OPENAI_KEY})
    pid = setup(client)
    r = client.post(f"/api/projects/{pid}/runs", json={"provider": "openai"})
    assert r.status_code == 202, r.text
    with session_scope() as db:
        assert [e.own_key for e in db.scalars(select(UsageEvent).where(UsageEvent.kind == "visibility_run"))] == [True]
    # The per-user limit still applies
    monkeypatch.setattr(keys_on, "quota_visibility_runs_per_user_per_day", 1)
    pid2 = client.post("/api/projects", json={"website_url": "second.example", "brand_name": "Second Shop"}).json()["id"]
    client.post(f"/api/projects/{pid2}/questions/generate")
    r = client.post(f"/api/projects/{pid2}/runs", json={"provider": "openai"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "quota_exceeded"


def test_check_key_maps_provider_responses():
    def transport(code):
        return httpx.MockTransport(lambda req: httpx.Response(code, json={}))

    assert user_keys.check_key("openai", OPENAI_KEY, transport(200)) is True
    assert user_keys.check_key("anthropic", OPENAI_KEY, transport(401)) is False
    assert user_keys.check_key("gemini", OPENAI_KEY, transport(503)) is None
    assert user_keys.check_key("brave", OPENAI_KEY, transport(200)) is None  # not checkable for free


def test_proxy_secret_blocks_direct_calls_and_sets_client_ip(anon_client, monkeypatch):
    from app.limits import client_ip

    monkeypatch.setattr(get_settings(), "proxy_secret", SecretStr("s3cret-proxy-value"))
    assert anon_client.get("/api/health").status_code == 200
    assert anon_client.get("/api/auth/me").status_code == 403
    assert anon_client.get("/api/auth/me", headers={"x-aeo-proxy-secret": "wrong"}).status_code == 403
    assert anon_client.get("/api/auth/me", headers={"x-aeo-proxy-secret": "s3cret-proxy-value"}).status_code == 401

    class Req:
        headers = {"x-aeo-client-ip": "203.0.113.9", "x-forwarded-for": "1.2.3.4"}
        client = None

    assert client_ip(Req()) == "203.0.113.9"


def test_platform_generated_secret_and_database_url(monkeypatch):
    from app.config import Settings

    monkeypatch.setattr(get_settings(), "secrets_key", SecretStr("Zm9vYmFyYmF6+/random-platform-secret-value=="))
    f = user_keys._fernet(get_settings())
    assert f.decrypt(f.encrypt(b"k")) == b"k"
    monkeypatch.setattr(get_settings(), "secrets_key", SecretStr("short"))
    with pytest.raises(user_keys.UserKeyError):
        user_keys._fernet(get_settings())
    assert Settings(database_url="postgresql://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url="postgres://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"
