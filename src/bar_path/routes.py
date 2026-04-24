"""FastAPI router for bar-path reconstruction.

Designed to plug into the existing ``src/api/app.py`` on main with a
single line::

    from ..bar_path.routes import router as bar_path_router
    app.include_router(bar_path_router)

The router reuses main's ``SessionStore`` (``src/api/storage.get_store``)
so uploaded sessions are shared across the analyze, one-rm, and
bar-path endpoints without duplication.

Endpoint
--------
``POST /api/sessions/{session_id}/bar-path``

    Request body: (empty — nothing to configure today)
    Response:      ``BarPathResponse`` (see models.py)

The handler is tolerant: if it can't import main's session store (e.g.
when bar-path is running in isolation), it falls back to looking up
the CSV by a query parameter. That keeps the module standalone-
testable without forcing the whole API infra to exist in this branch.
"""
from __future__ import annotations

import os
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

from .models import BarPathRep, BarPathResponse
from .reconstruct import RepBarPath, reconstruct_session

router = APIRouter(prefix="/api/sessions", tags=["bar-path"])


def _try_get_store():
    """Import main's session store lazily and only if present. Returns
    None when this branch is used standalone (no src/api package)."""
    try:
        from ..api.storage import get_store  # type: ignore  # noqa: E402
    except Exception:  # pragma: no cover — standalone mode
        return None
    return get_store()


def _to_api_rep(r: RepBarPath) -> BarPathRep:
    """Cast the internal dataclass to the Pydantic wire model. Keeps
    arrays as float32 lists to match main's PlotData serialization
    (smaller payload, same precision as the frontend plotter needs)."""
    to_f32 = lambda a: np.asarray(a, dtype=np.float32).tolist()  # noqa: E731
    return BarPathRep(
        num=r.num,
        start_s=float(r.start_s),
        chest_s=float(r.chest_s),
        lockout_s=float(r.lockout_s),
        end_s=float(r.end_s),
        duration_s=float(r.duration_s),
        t_s=to_f32(r.t_s),
        x_m=to_f32(r.x_m),
        y_m=to_f32(r.y_m),
        z_m=to_f32(r.z_m),
        chest_idx=int(r.chest_idx),
        lockout_idx=int(r.lockout_idx),
        rom_m=float(r.rom_m),
        peak_x_dev_m=float(r.peak_x_dev_m),
        peak_y_dev_m=float(r.peak_y_dev_m),
    )


@router.post("/{session_id}/bar-path", response_model=BarPathResponse)
def compute_bar_path(session_id: str,
                     csv_path: Optional[str] = None) -> BarPathResponse:
    """Reconstruct per-rep 3-D bar path for a previously-uploaded
    session.

    The ``csv_path`` query parameter is a fallback for standalone
    deployments (tests, notebooks, single-module runs). In production
    the session is resolved through the shared ``SessionStore`` from
    ``src/api/storage`` on main — just as ``/analyze`` does.
    """
    store = _try_get_store()

    if store is not None:
        record = store.get(session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="session not found")
        csv_to_read = record.csv_path
    else:
        if not csv_path or not os.path.isfile(csv_path):
            raise HTTPException(
                status_code=404,
                detail="session store unavailable and csv_path not supplied",
            )
        csv_to_read = csv_path

    try:
        df = pd.read_csv(csv_to_read)
    except Exception as e:
        raise HTTPException(status_code=400,
                            detail=f"cannot read session CSV: {e}")

    try:
        result = reconstruct_session(df)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500,
                            detail=f"bar-path reconstruction failed: {e}")

    return BarPathResponse(
        session_id=session_id,
        fs_hz=float(result.fs_hz),
        duration_s=float(result.duration_s),
        n_reps=int(result.n_reps),
        reps=[_to_api_rep(r) for r in result.reps],
        notes=result.notes,
    )
