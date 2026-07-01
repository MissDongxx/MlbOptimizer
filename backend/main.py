from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.health import router as health_router
from routers.optimize import router as optimize_router
from routers.optimize import shutdown_optimizer_executor
from routers.players import router as players_router
from services.scheduler import start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = start_scheduler()
    yield
    shutdown_optimizer_executor()
    scheduler.shutdown(wait=False)


app = FastAPI(title="LineupLab API", version="0.1.0", lifespan=lifespan)

origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(players_router, prefix="/players", tags=["players"])
app.include_router(optimize_router, prefix="/optimize", tags=["optimize"])
app.include_router(health_router, tags=["health"])
