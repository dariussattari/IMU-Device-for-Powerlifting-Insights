"""Pydantic request/response schemas for the IMU analysis API."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ────────────────────────────────────────────────────────────────────────
# Sessions
# ────────────────────────────────────────────────────────────────────────
class SessionInfo(BaseModel):
    session_id: str
    filename: str
    fs_hz: float
    duration_s: float
    n_samples: int
    has_annotations: bool
    lifter: Optional[str] = None
    load_lb: Optional[int] = None
    n_reps_prescribed: Optional[int] = None
    uploaded_at: str


class SessionListResponse(BaseModel):
    sessions: List[SessionInfo]


# ────────────────────────────────────────────────────────────────────────
# Analyze
# ────────────────────────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    method: str = Field(default="D", pattern="^[ABCD]$")
    include: List[str] = Field(default_factory=lambda: ["velocity", "sticking"])


class RepBoundary(BaseModel):
    num: int
    chest_s: float
    lockout_s: float
    peak_s: float


class PlotData(BaseModel):
    t: List[float]
    vy: List[float]
    ay_lin: List[float]
    gyro_mag: List[float]


class AnalyzeResponse(BaseModel):
    session_id: str
    method: str
    rep_boundaries: List[RepBoundary]
    reps: Optional[List[dict]] = None
    sticking: Optional[List[dict]] = None
    plot_data: PlotData


# ────────────────────────────────────────────────────────────────────────
# 1RM
# ────────────────────────────────────────────────────────────────────────
class OneRmRequest(BaseModel):
    session_ids: List[str]
    method: str = Field(default="D", pattern="^[ABCD]$")


class EstimatorOut(BaseModel):
    name: str
    one_rm_lb: Optional[float]
    slope: Optional[float]
    intercept: Optional[float]
    r2: Optional[float]
    mvt: Optional[float]
    x_points: List[float]
    y_points: List[float]
    notes: str = ""
    valid: bool = True


class SessionSummary(BaseModel):
    session_id: str
    name: str
    lifter: str
    load_lb: int
    n_reps_prescribed: int
    n_reps_detected: int
    best_mpv: Optional[float]
    best_mcv: Optional[float]
    best_pcv: Optional[float]
    top2_mpv: Optional[float]
    rep1_mpv: Optional[float]
    last_mpv: Optional[float]
    vl_frac: Optional[float]
    rep_mpv: List[float]
    rep_mcv: List[float]
    rep_pcv: List[float]


class OneRmResponse(BaseModel):
    lifter: str
    consensus_one_rm_lb: Optional[float]
    ci95: List[Optional[float]]
    method_used: str
    notes: str
    estimators: List[EstimatorOut]
    sessions: List[SessionSummary]
