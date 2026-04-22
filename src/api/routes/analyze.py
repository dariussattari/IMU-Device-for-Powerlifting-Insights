"""Single-session analysis endpoint.

Runs rep counting, velocity metrics, and/or sticking-point detection on a
previously-uploaded session. The response always includes rep boundaries
and downsampled plot arrays; per-rep metrics and sticking results are
included when requested via the `include` list.
"""
from __future__ import annotations

import os
import sys
from typing import List

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "velocity")))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "sticking_point")))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "rep_counting")))
from velocity_metrics import compute_metrics  # noqa: E402
from sticking_point import compute_sticking  # noqa: E402
from sign_change_rep_counter import (  # noqa: E402
    build_reps, compute_vy, filter_by_post_motion, filter_by_rerack_gyro,
)

from ..models import AnalyzeRequest, AnalyzeResponse, PlotData, RepBoundary
from ..serializers import (
    serialize_reps, serialize_sticking, to_float32_list,
)
from ..storage import get_store

router = APIRouter(prefix="/api/sessions", tags=["analyze"])

VALID_INCLUDES = {"rep_counting", "velocity", "sticking"}


@router.post("/{session_id}/analyze", response_model=AnalyzeResponse)
def analyze_session(session_id: str, req: AnalyzeRequest) -> AnalyzeResponse:
    store = get_store()
    record = store.get(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="session not found")

    invalid = set(req.include) - VALID_INCLUDES
    if invalid:
        raise HTTPException(status_code=400,
                            detail=f"Invalid include values: {sorted(invalid)}."
                                   f" Allowed: {sorted(VALID_INCLUDES)}")

    want_velocity = "velocity" in req.include
    want_sticking = "sticking" in req.include
    want_rep_counting_only = (
        "rep_counting" in req.include
        and not want_velocity
        and not want_sticking
    )

    rep_boundaries: List[RepBoundary]
    plot = PlotData(t=[], vy=[], ay_lin=[], gyro_mag=[])
    reps_out = None
    sticking_out = None

    if want_rep_counting_only:
        df = pd.read_csv(record.csv_path)
        t, vy, gyro_mag, fs = compute_vy(df)
        candidates = build_reps(vy, v_hi=0.25, fs=fs)
        after_rerack = filter_by_rerack_gyro(candidates, gyro_mag, fs)
        kept = filter_by_post_motion(after_rerack, vy, gyro_mag, fs)
        for i, r in enumerate(kept):
            r["rep_num"] = i + 1

        rep_boundaries = [
            RepBoundary(
                num=r["rep_num"],
                chest_s=float(r["chest_s"]),
                lockout_s=float(r["lockout_s"]),
                peak_s=float(r["peak_idx"] / fs),
            )
            for r in kept
        ]
        plot = PlotData(
            t=to_float32_list(t),
            vy=to_float32_list(vy),
            ay_lin=to_float32_list(np.zeros_like(vy)),
            gyro_mag=to_float32_list(gyro_mag),
        )
    else:
        if want_sticking:
            result = compute_sticking(
                record.csv_path, record.annotations_path, method=req.method
            )
            sticking_out = serialize_sticking(result["sticking"])
        else:
            result = compute_metrics(
                record.csv_path, record.annotations_path, method=req.method,
                snap=False, use_detector=True,
            )
        if want_velocity or want_sticking:
            reps_out = serialize_reps(result["reps"])

        t = result["t"]
        vy = result["vy"]
        ay_lin = result["ay_lin"]
        gyro_mag = result["gyro_mag"]
        boundaries = result["boundaries"]
        rep_nums = [r.num for r in result["reps"]]

        rep_boundaries = [
            RepBoundary(
                num=num,
                chest_s=float(t[ci]),
                lockout_s=float(t[li]),
                peak_s=float(t[ci + int(np.argmax(vy[ci:li + 1]))]),
            )
            for num, (ci, li) in zip(rep_nums, boundaries)
        ]
        plot = PlotData(
            t=to_float32_list(t),
            vy=to_float32_list(vy),
            ay_lin=to_float32_list(ay_lin),
            gyro_mag=to_float32_list(gyro_mag),
        )

    return AnalyzeResponse(
        session_id=session_id,
        method=req.method,
        rep_boundaries=rep_boundaries,
        reps=reps_out,
        sticking=sticking_out,
        plot_data=plot,
    )
