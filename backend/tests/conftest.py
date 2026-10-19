import os

# Never let tests pick up real credentials or databases from backend/.env or the environment.
os.environ["AEO_DISABLE_ENV_FILE"] = "1"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["DATABASE_URL"] = "sqlite://"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, configure_engine  # noqa: E402

get_settings.cache_clear()


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    configure_engine(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app.limits import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def anon_client(engine):
    """A client with no session."""
    from app.main import app

    with TestClient(app) as c:
        yield c


def login_as(client, email: str, password: str = "correct-horse-battery"):
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def client(engine):
    """A client logged in as a fresh user (the session cookie is kept by the TestClient)."""
    from app.main import app

    with TestClient(app) as c:
        login_as(c, "owner@example.com")
        yield c


@pytest.fixture()
def other_client(engine):
    """A second, separately logged-in user, for isolation tests."""
    from app.main import app

    with TestClient(app) as c:
        login_as(c, "intruder@example.com")
        yield c
