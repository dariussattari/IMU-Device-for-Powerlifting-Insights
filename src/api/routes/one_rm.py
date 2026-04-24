"""Multi-session 1RM estimation endpoint."""
from __future__ import annotations

import os
import sys

from fastapi import APIRouter, HTTPException

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "one_rm")))
from one_rm import (  # noqa: E402
    estimate_lifter_1rm, extract_session_features,
)

from ..models import (
    EstimatorOut, OneRmRequest, OneRmResponse, SessionSummary,
)
from ..serializers import nullable_float, safe_float
from ..storage import get_store

router = APIRouter(prefix="/api", tags=["one_rm"])


@router.post("/one-rm", response_model=OneRmResponse)
def one_rm(req: OneRmRequest) -> OneRmResponse:
    if not req.session_ids:
        raise HTTPException(status_code=400, detail="session_ids is empty")

    store = get_store()
    records = []
    for sid in req.session_ids:
        r = store.get(sid)
        if r is None:
            raise HTTPException(status_code=404,
                                detail=f"session not found: {sid}")
        if r.lifter is None or r.load_lb is None:
            raise HTTPException(
                status_code=400,
                detail=(f"session {sid} is missing lifter or load_lb "
                        f"(required for 1RM)"),
            )
        records.append(r)

    lifters = {r.lifter for r in records}
    if len(lifters) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"All sessions must belong to one lifter; got {sorted(lifters)}",
        )

    try:
        features = [
            extract_session_features(
                csv_path=r.csv_path,
                ann_path=r.annotations_path,
                method=req.method,
                name=r.filename.replace(".csv", ""),
                lifter=r.lifter,
                load_lb=r.load_lb,
                # optional — downstream estimators don't use this value;
                # fall back to 0 so the dataclass int-cast succeeds.
                n_reps_prescribed=r.n_reps_prescribed or 0,
            )
            for r in records
        ]
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Feature extraction failed: {e}")

    try:
        est = estimate_lifter_1rm(features)
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"1RM estimation failed: {e}")

    estimators = [
        EstimatorOut(
            name=e.name,
            one_rm_lb=nullable_float(e.one_rm_lb),
            slope=nullable_float(e.slope),
            intercept=nullable_float(e.intercept),
            r2=nullable_float(e.r2),
            mvt=nullable_float(e.mvt),
            x_points=[safe_float(x) for x in e.x_points],
            y_points=[safe_float(y) for y in e.y_points],
            notes=e.notes,
            valid=bool(e.valid),
        )
        for e in est.estimators
    ]

    session_summaries = [
        SessionSummary(
            session_id=r.session_id,
            name=f.name,
            lifter=f.lifter,
            load_lb=f.load_lb,
            n_reps_prescribed=f.n_reps_prescribed,
            n_reps_detected=f.n_reps_detected,
            best_mpv=nullable_float(f.best_mpv),
            best_mcv=nullable_float(f.best_mcv),
            best_pcv=nullable_float(f.best_pcv),
            top2_mpv=nullable_float(f.top2_mpv),
            rep1_mpv=nullable_float(f.rep1_mpv),
            last_mpv=nullable_float(f.last_mpv),
            vl_frac=nullable_float(f.vl_frac),
            rep_mpv=[safe_float(v) for v in f.rep_mpv],
            rep_mcv=[safe_float(v) for v in f.rep_mcv],
            rep_pcv=[safe_float(v) for v in f.rep_pcv],
        )
        for r, f in zip(records, features)
    ]

    return OneRmResponse(
        lifter=est.lifter,
        consensus_one_rm_lb=nullable_float(est.consensus_one_rm_lb),
        ci95=[nullable_float(est.ci95[0]), nullable_float(est.ci95[1])],
        method_used=est.method_used,
        notes=est.notes,
        estimators=estimators,
        sessions=session_summaries,
    )
