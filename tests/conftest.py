import os
import tempfile
from pathlib import Path

# Settings are read when `config` is first imported, so set the environment first.
_tmp_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_tmp_dir) / 'test.db'}"
os.environ["SECRET_KEY"] = "test-secret-key-test-secret-key-0123456789"
os.environ["SEED_DEMO_USERS"] = "true"
os.environ["SEED_PASSWORD"] = "demo-pass-123"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from security import login_limiter  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:  # runs the lifespan: creates tables, seeds users
        yield test_client


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    login_limiter.clear()
    yield
    login_limiter.clear()


def login(client: TestClient, username: str, password: str = "demo-pass-123"):
    return client.post("/token", data={"username": username, "password": password})


def auth_headers(client: TestClient, username: str) -> dict[str, str]:
    response = login(client, username)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_headers(client):
    return auth_headers(client, "Calven")


@pytest.fixture(scope="session")
def user_headers(client):
    return auth_headers(client, "Mahymar")
