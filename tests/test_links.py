import csv
import io
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from linklane.web import SLUG


def test_full_lifecycle(owner, link):
    created = owner.post("/api/links", json=link)
    assert created.status_code == 201
    assert created.json()["short_url"] == "http://testserver/s/hello"
    followed = owner.get("/s/hello", follow_redirects=False)
    assert followed.status_code == 302
    assert followed.headers["location"] == link["destination"]
    rows = owner.get("/api/overview").json()
    assert rows["links"][0]["clicks"] == 1
    assert rows["analytics"]["total_clicks"] == 1
    assert owner.put("/api/links/hello", json={**link, "active": False}).status_code == 200
    assert owner.get("/s/hello").status_code == 410
    assert owner.delete("/api/links/hello").status_code == 200
    assert owner.get("/s/hello").status_code == 404


def test_custom_address_case_and_conflict(owner, link):
    assert owner.post("/api/links", json={**link, "slug": "Hello"}).status_code == 201
    assert owner.post("/api/links", json=link).status_code == 409
    assert owner.get("/s/HELLO", follow_redirects=False).status_code == 302


def test_random_addresses_and_initial_pause(owner, link):
    a = owner.post("/api/links", json={**link, "slug": "", "active": False}).json()
    b = owner.post("/api/links", json={**link, "slug": ""}).json()
    assert a["slug"] != b["slug"]
    assert a["status"] == "paused"
    assert owner.get("/s/" + a["slug"]).status_code == 410


def test_generated_addresses_always_match_route(owner, link):
    for _ in range(25):
        row = owner.post("/api/links", json={**link, "slug": ""}).json()
        assert SLUG.fullmatch(row["slug"])
        assert owner.get("/s/" + row["slug"], follow_redirects=False).status_code == 302


@pytest.mark.parametrize(
    "destination",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://",
        "https://user:secret@example.com",
        "https://example.com\r\nX-Bad: yes",
        "https://example.com:bad",
        "https://example.com\\@evil.test",
        "data:text/html,hi",
    ],
)
def test_dangerous_urls_rejected(owner, link, destination):
    assert owner.post("/api/links", json={**link, "destination": destination}).status_code == 400


@pytest.mark.parametrize("slug", ["a", "ab", "привет", "hello world", "a/b", "a" * 41])
def test_invalid_slugs(owner, link, slug):
    assert owner.post("/api/links", json={**link, "slug": slug}).status_code == 400


def test_unicode_url_normalization(owner, link):
    response = owner.post("/api/links", json={**link, "destination": "https://пример.рф/путь"})
    assert response.status_code == 201
    assert "xn--" in response.json()["destination"]


def test_expiration_head_and_preview_do_not_count(owner, link):
    owner.post("/api/links", json=link)
    assert owner.head("/s/hello", follow_redirects=False).status_code == 302
    assert owner.get("/p/hello").status_code == 200
    assert owner.get("/api/overview").json()["links"][0]["clicks"] == 0
    owner.put("/api/links/hello", json={**link, "expires_at": time.time() - 10})
    assert owner.get("/s/hello").status_code == 410
    assert owner.get("/p/hello").status_code == 410
    assert (
        owner.post("/api/links", json={**link, "slug": "expired", "expires_at": 1}).status_code
        == 400
    )


def test_qr_export_and_csv_formula_protection(owner, link):
    owner.post("/api/links", json={**link, "title": "=SUM(1,2)"})
    qr = owner.get("/api/links/hello/qr.svg")
    assert qr.status_code == 200
    assert "image/svg+xml" in qr.headers["content-type"]
    assert b"<svg" in qr.content and b"<path" in qr.content
    exported = owner.get("/api/export.csv")
    rows = list(csv.reader(io.StringIO(exported.text.lstrip("\ufeff"))))
    assert rows[1][0] == "'=SUM(1,2)"
    assert rows[1][1] == "http://testserver/s/hello"


def test_analytics_avoid_personal_visitor_fields(owner, link, app):
    owner.post("/api/links", json=link)
    owner.get(
        "/s/hello",
        headers={
            "User-Agent": "Mozilla Chrome/123.0",
            "Referer": "https://example.org/private?token=secret",
        },
        follow_redirects=False,
    )
    analytics = owner.get("/api/overview").json()["analytics"]
    assert analytics["browsers"] == [{"name": "Chrome", "count": 1}]
    assert analytics["sources"] == [{"name": "example.org", "count": 1}]
    with app.state.db.connection() as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(visits)")]
    assert "ip" not in columns and "user_agent" not in columns


def test_concurrent_redirects_do_not_lose_clicks(owner, link, app):
    owner.post("/api/links", json=link)

    def follow(_):
        with TestClient(app) as guest:
            return guest.get("/s/hello", follow_redirects=False).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert list(pool.map(follow, range(18))) == [302] * 18
    assert owner.get("/api/overview").json()["links"][0]["clicks"] == 18


def test_request_size_json_and_recursion_guard(owner, link):
    assert owner.post("/api/links", content="x" * 17000).status_code == 413
    assert owner.post("/api/links", content="{not json}").status_code == 400
    assert (
        owner.post(
            "/api/links", json={**link, "destination": "http://testserver/s/other"}
        ).status_code
        == 400
    )
