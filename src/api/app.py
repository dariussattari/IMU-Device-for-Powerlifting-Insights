"""FastAPI app for IMU analysis.

Exposes upload, analyze, and 1RM endpoints backed by the existing
analysis modules in src/{rep_counting,velocity,sticking_point,one_rm}.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routes import analyze, one_rm, sessions

app = FastAPI(
    title="IMU Analysis API",
    version="0.1.0",
    description="REST API for bench-press rep counting, velocity metrics, "
                "sticking-point detection, and 1RM estimation.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(analyze.router)
app.include_router(one_rm.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


_HERE = os.path.dirname(__file__)
FRONTEND_DIST = os.path.abspath(
    os.path.join(_HERE, "..", "..", "frontend", "dist")
)


if os.path.isdir(FRONTEND_DIST):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")),
        name="assets",
    )

    @app.get("/{full_path:path}")
    def spa_catchall(full_path: str):
        candidate = os.path.join(FRONTEND_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
