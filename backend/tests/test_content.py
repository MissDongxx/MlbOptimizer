from __future__ import annotations

from fastapi.testclient import TestClient

from main import app
from routers import content


def article(status: str = "approved") -> dict:
    return {
        "status": status,
        "slug": "test-article",
        "title": "Test Article With a Valid Editorial Title",
        "description": "A sufficiently descriptive summary for a test article and its editorial publishing workflow.",
        "primaryKeyword": "test article",
        "category": "tests",
        "excerpt": "Test excerpt",
        "reviewer": "Test Reviewer",
        "publishedAt": "2026-07-24",
        "updatedAt": "2026-07-24",
        "sections": [{"heading": f"Section {index}"} for index in range(4)],
        "sources": [{"id": "one"}, {"id": "two"}],
        "internalLinks": [{"href": "/"}, {"href": "/blog"}],
        "cta": {"label": "Open", "href": "/"},
    }


def test_publish_and_read_article(monkeypatch) -> None:
    stored: dict = {}
    monkeypatch.setenv("CONTENT_PUBLISH_TOKEN", "test-secret")
    monkeypatch.setattr(content.cache_store, "read_json", lambda *_args, **_kwargs: stored.copy())
    monkeypatch.setattr(content.cache_store, "write_json", lambda _key, value: stored.update(value))
    client = TestClient(app)

    response = client.post(
        "/content/articles/test-article",
        headers={"Authorization": "Bearer test-secret"},
        json={"article": article(), "source_revision": "abc123"},
    )
    assert response.status_code == 201
    assert client.get("/content/articles/test-article").status_code == 200
    listing = client.get("/content/articles").json()
    assert listing["count"] == 1


def test_publish_rejects_unapproved_article(monkeypatch) -> None:
    monkeypatch.setenv("CONTENT_PUBLISH_TOKEN", "test-secret")
    client = TestClient(app)
    response = client.post(
        "/content/articles/test-article",
        headers={"Authorization": "Bearer test-secret"},
        json={"article": article(status="review")},
    )
    assert response.status_code == 422


def test_publish_rejects_bad_token(monkeypatch) -> None:
    monkeypatch.setenv("CONTENT_PUBLISH_TOKEN", "test-secret")
    client = TestClient(app)
    response = client.post(
        "/content/articles/test-article",
        headers={"Authorization": "Bearer wrong"},
        json={"article": article()},
    )
    assert response.status_code == 401
