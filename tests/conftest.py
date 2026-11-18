import re

import pytest
from fastapi.testclient import TestClient

from linklane.config import Config
from linklane.web import create_app

PASSWORD = "local-test-password-2026"


def token(client, path="/app"):
    response = client.get(path)
    return re.search(r'name="csrf-token" content="([^"]+)"', response.text).group(1)


@pytest.fixture
def app(tmp_path):
    return create_app(
        Config(tmp_path, "http://testserver", allow_setup=True, session_secret="test-only-secret")
    )


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def owner(client):
    csrf = token(client, "/setup")
    assert (
        client.post(
            "/api/setup", json={"password": PASSWORD}, headers={"X-CSRF-Token": csrf}
        ).status_code
        == 200
    )
    client.headers["X-CSRF-Token"] = token(client)
    return client


@pytest.fixture
def link():
    return {
        "title": "Example",
        "destination": "https://example.com/path?q=test",
        "slug": "hello",
        "tag": "Work",
    }
