from __future__ import annotations

import hmac
import os
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from services.cache_store import cache_store

router = APIRouter()

CONTENT_ARTICLES_KEY = "content/articles"
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class PublishArticleRequest(BaseModel):
    article: dict[str, Any]
    source_revision: str | None = Field(default=None, max_length=120)


def _article_store() -> dict[str, dict[str, Any]]:
    stored = cache_store.read_json(CONTENT_ARTICLES_KEY, default={})
    return stored if isinstance(stored, dict) else {}


def _public_article(article: dict[str, Any]) -> dict[str, Any] | None:
    if article.get("status") != "approved":
        return None
    return article


@router.get("/articles")
def list_articles() -> dict[str, Any]:
    articles = [
        article
        for article in _article_store().values()
        if _public_article(article) is not None
    ]
    articles.sort(
        key=lambda article: str(article.get("publishedAt") or article.get("updatedAt") or ""),
        reverse=True,
    )
    return {"articles": articles, "count": len(articles)}


@router.get("/articles/{slug}")
def get_article(slug: str) -> dict[str, Any]:
    if not SLUG_PATTERN.fullmatch(slug):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    article = _article_store().get(slug)
    if not isinstance(article, dict) or _public_article(article) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    return {"article": article}


@router.post("/articles/{slug}", status_code=status.HTTP_201_CREATED)
def publish_article(
    slug: str,
    payload: PublishArticleRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_publish_token(authorization)
    article = payload.article
    _validate_publishable_article(slug, article)

    now = datetime.now(UTC).isoformat()
    published = dict(article)
    published["status"] = "approved"
    published["publishedAt"] = published.get("publishedAt") or now[:10]
    published["updatedAt"] = now[:10]
    published["_publication"] = {
        "publishedAt": now,
        "sourceRevision": payload.source_revision,
    }

    stored = _article_store()
    stored[slug] = published
    cache_store.write_json(CONTENT_ARTICLES_KEY, stored)
    return {
        "ok": True,
        "slug": slug,
        "publishedAt": published["publishedAt"],
        "updatedAt": published["updatedAt"],
    }


def _require_publish_token(authorization: str | None) -> None:
    expected = os.getenv("CONTENT_PUBLISH_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Content publishing is not configured",
        )
    scheme, _, provided = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid publishing credentials",
        )


def _validate_publishable_article(slug: str, article: dict[str, Any]) -> None:
    if not SLUG_PATTERN.fullmatch(slug) or article.get("slug") != slug:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid slug")
    if article.get("status") != "approved":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only approved articles can be published",
        )
    reviewer = str(article.get("reviewer") or "").strip()
    if len(reviewer) < 2 or "pending" in reviewer.lower():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A named reviewer is required",
        )
    required = (
        "title",
        "description",
        "primaryKeyword",
        "category",
        "excerpt",
        "publishedAt",
        "updatedAt",
        "sections",
        "sources",
        "internalLinks",
        "cta",
    )
    missing = [field for field in required if not article.get(field)]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Missing required fields: {', '.join(missing)}",
        )
    if len(article.get("sections", [])) < 4 or len(article.get("sources", [])) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Article does not meet minimum evidence requirements",
        )
