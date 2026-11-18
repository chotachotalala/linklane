from conftest import PASSWORD, token
from fastapi.testclient import TestClient

from linklane.config import Config
from linklane.security import password_hash, verify_password
from linklane.web import create_app


def test_private_api_requires_authentication(client, link):
    assert client.get("/api/overview").status_code == 401
    assert client.post("/api/links", json=link).status_code == 401
    assert client.get("/api/export.csv").status_code == 401
    assert client.get("/api/links/hello/qr.svg").status_code == 401


def test_csrf_and_cross_origin_rejected(owner, link):
    assert owner.post("/api/links", json=link, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert (
        owner.post("/api/links", json=link, headers={"Origin": "https://evil.test"}).status_code
        == 403
    )
    assert owner.get("/api/overview", headers={"Host": "evil.test"}).status_code == 400


def test_first_run_only_once_and_only_local(client, owner, app):
    assert client.post("/api/setup", json={"password": PASSWORD}).status_code == 403
    assert app.state.db.owner()["password_hash"] != PASSWORD


def test_remote_setup_disabled(tmp_path):
    app = create_app(
        Config(tmp_path, "http://testserver", allow_setup=False, session_secret="test-only")
    )
    with TestClient(app) as client:
        assert client.get("/setup").status_code == 403
        assert client.post("/api/setup", json={"password": PASSWORD}).status_code == 403


def test_password_hash_salted():
    a, b = password_hash(PASSWORD), password_hash(PASSWORD)
    assert a != b
    assert verify_password(PASSWORD, a)
    assert not verify_password("wrong", a)


def test_logout_invalidates_current_session(owner):
    assert owner.post("/api/logout").status_code == 200
    assert owner.get("/api/overview").status_code == 401


def test_login_throttling(client, owner):
    owner.post("/api/logout")
    csrf = token(client, "/login")
    client.headers["X-CSRF-Token"] = csrf
    for _ in range(5):
        assert (
            client.post("/api/login", json={"password": "wrong-password-long"}).status_code == 401
        )
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 429


def test_password_change_revokes_other_sessions(owner, app):
    with TestClient(app) as other:
        csrf = token(other, "/login")
        assert (
            other.post(
                "/api/login", json={"password": PASSWORD}, headers={"X-CSRF-Token": csrf}
            ).status_code
            == 200
        )
        assert other.get("/api/overview").status_code == 200
        assert (
            owner.post(
                "/api/password",
                json={"current_password": PASSWORD, "password": "changed-password-2026"},
            ).status_code
            == 200
        )
        assert owner.get("/api/overview").status_code == 401
        assert other.get("/api/overview").status_code == 401


def test_headers_and_escaped_preview(owner, link):
    owner.post("/api/links", json={**link, "title": "<script>alert(1)</script>"})
    preview = owner.get("/p/hello")
    assert "<script>alert(1)</script>" not in preview.text
    assert "&lt;script&gt;" in preview.text
    assert "script-src 'self'" in preview.headers["content-security-policy"]
    assert preview.headers["x-frame-options"] == "DENY"
    assert "no-store" in owner.get("/app").headers["cache-control"]


def test_cookie_security_flags(owner):
    owner.post("/api/logout")
    csrf = token(owner, "/login")
    response = owner.post("/api/login", json={"password": PASSWORD}, headers={"X-CSRF-Token": csrf})
    cookie = response.headers.get("set-cookie", "").lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_secure_configuration_and_session_key_persistence(tmp_path):
    config = Config(tmp_path, "https://links.example.com", secure_cookies=True)
    assert config.secret() == config.secret()
    config.validate()
