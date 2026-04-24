"""Session upload / list / delete endpoints."""
from __future__ import annotations

import io
import os
import sys
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "rep_counting")))
from sign_change_rep_counter import compute_vy  # noqa: E402

from ..models import SessionInfo, SessionListResponse
from ..storage import SessionRecord, get_store

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _record_to_info(r: SessionRecord) -> SessionInfo:
    return SessionInfo(
        session_id=r.session_id,
        filename=r.filename,
        fs_hz=r.fs_hz,
        duration_s=r.duration_s,
        n_samples=r.n_samples,
        has_annotations=r.has_annotations,
        lifter=r.lifter,
        load_lb=r.load_lb,
        n_reps_prescribed=r.n_reps_prescribed,
        uploaded_at=r.uploaded_at,
    )


@router.post("", response_model=SessionInfo, status_code=201)
async def upload_session(
    csv: UploadFile = File(...),
    annotations: Optional[UploadFile] = File(None),
    lifter: Optional[str] = Form(None),
    load_lb: Optional[int] = Form(None),
    n_reps_prescribed: Optional[int] = Form(None),
):
    csv_bytes = await csv.read()
    if len(csv_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="CSV exceeds 50 MB limit")
    if len(csv_bytes) == 0:
        raise HTTPException(status_code=400, detail="CSV is empty")

    try:
        df = pd.read_csv(io.BytesIO(csv_bytes))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot parse CSV: {e}")

    required = {"timestamp_ms", "a1x", "a1y", "a1z", "g1x", "g1y", "g1z"}
    missing = required - set(df.columns)
    if missing:
        raise HTTPException(status_code=400,
                            detail=f"CSV missing columns: {sorted(missing)}")

    try:
        t, _, _, fs = compute_vy(df)
    except Exception as e:
        raise HTTPException(status_code=400,
                            detail=f"Cannot process IMU data: {e}")

    duration_s = float(t[-1] - t[0]) if len(t) >= 2 else 0.0

    ann_bytes: Optional[bytes] = None
    if annotations is not None:
        ann_bytes = await annotations.read()
        if len(ann_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413,
                                detail="Annotations file exceeds 50 MB limit")
        if len(ann_bytes) == 0:
            ann_bytes = None
        else:
            try:
                ann_df = pd.read_csv(io.BytesIO(ann_bytes))
            except Exception as e:
                raise HTTPException(status_code=400,
                                    detail=f"Cannot parse annotations: {e}")
            if not {"label", "timestamp_ms"}.issubset(ann_df.columns):
                raise HTTPException(status_code=400,
                                    detail="Annotations must have label,"
                                           " timestamp_ms columns")

    store = get_store()
    record = store.create(
        filename=csv.filename or "session.csv",
        csv_bytes=csv_bytes,
        annotations_bytes=ann_bytes,
        lifter=lifter,
        load_lb=int(load_lb) if load_lb is not None else None,
        n_reps_prescribed=(int(n_reps_prescribed)
                           if n_reps_prescribed is not None else None),
        fs_hz=float(fs),
        duration_s=duration_s,
        n_samples=int(len(df)),
    )
    return _record_to_info(record)


@router.get("", response_model=SessionListResponse)
def list_sessions():
    store = get_store()
    return SessionListResponse(
        sessions=[_record_to_info(r) for r in store.list()]
    )


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: str) -> Response:
    store = get_store()
    if not store.delete(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return Response(status_code=204)
