from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from routers.health import router as health_router
from routers.optimize import router as optimize_router
from routers.optimize import shutdown_optimizer_executor
from routers.players import router as players_router
from services.scheduler import start_scheduler

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("lineuplab.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = start_scheduler()
    yield
    shutdown_optimizer_executor()
    scheduler.shutdown(wait=False)


app = FastAPI(title="LineupLab API", version="0.1.0", lifespan=lifespan)

APP_ENV = os.getenv("APP_ENV", "development").lower()
USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "true").lower()
origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",") if origin.strip()]

if APP_ENV == "production" and USE_MOCK_DATA == "true":
    raise RuntimeError("USE_MOCK_DATA must be false in production")
if APP_ENV == "production" and "*" in origins:
    raise RuntimeError("Wildcard CORS is not allowed in production")


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        self.requests: dict[str, deque[float]] = defaultdict(deque)
        self.window_seconds = 60
        self.limits = {
            "/optimize": 10,
            "/players/today": 60,
            "/health": 120,
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        limit = self._limit_for_path(request.url.path)
        if not limit:
            return await call_next(request)

        now = time.monotonic()
        key = f"{_client_ip(request)}:{request.url.path}"
        bucket = self.requests[key]
        while bucket and now - bucket[0] > self.window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please try again shortly."},
                headers={"Retry-After": str(self.window_seconds)},
            )
        bucket.append(now)
        return await call_next(request)

    def _limit_for_path(self, path: str) -> int | None:
        for prefix, limit in self.limits.items():
            if path.startswith(prefix):
                return limit
        return None


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Callable) -> Response:
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["x-request-id"] = request_id
        return response
    finally:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": _client_ip(request),
                }
            )
        )


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(players_router, prefix="/players", tags=["players"])
app.include_router(optimize_router, prefix="/optimize", tags=["optimize"])
app.include_router(health_router, tags=["health"])
