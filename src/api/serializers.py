"""JSON serialization helpers for numpy + analysis dataclasses."""
from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, List

import numpy as np


def to_float32_list(arr: Any) -> List[float]:
    """Convert a numpy array (or list) to a JSON-safe float list (float32
    precision, with NaN/Inf replaced by None-compatible 0.0 to keep strict
    JSON). Downsampling to float32 keeps plot payloads small."""
    a = np.asarray(arr, dtype=np.float32)
    a = np.where(np.isfinite(a), a, 0.0)
    return a.tolist()


def safe_float(x: Any) -> float:
    v = float(x)
    if math.isnan(v) or math.isinf(v):
        return 0.0
    return v


def nullable_float(x: Any) -> float | None:
    if x is None:
        return None
    v = float(x)
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def dataclass_to_dict(obj: Any) -> dict:
    """asdict() but scrubs NaN/Inf to None for JSON compatibility."""
    if not is_dataclass(obj):
        return obj
    d = asdict(obj)
    return _scrub(d)


def _scrub(v: Any) -> Any:
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(v, dict):
        return {k: _scrub(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_scrub(x) for x in v]
    if isinstance(v, tuple):
        return [_scrub(x) for x in v]
    return v


def serialize_reps(reps: Iterable) -> List[dict]:
    return [dataclass_to_dict(r) for r in reps]


def serialize_sticking(sticking: Iterable) -> List[dict]:
    return [dataclass_to_dict(s) for s in sticking]
