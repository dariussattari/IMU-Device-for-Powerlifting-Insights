"""Pydantic schemas for the bar-path API.

These mirror the style used in ``src/api/models.py`` on main (float32
downsampled arrays, nullable floats via serializers.nullable_float).

Kept in this module (rather than added directly to src/api/models.py)
so the bar_path package stays self-contained and can be merged without
touching unrelated files.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class BarPathRep(BaseModel):
    """One rep's reconstructed 3-D bar path, sampled to a fixed length.

    Coordinate convention (world frame)
    -----------------------------------
        x : forward / back (sagittal axis). Positive is forward as seen
            from the lifter's perspective at the time of calibration.
            Yaw is not observable with a single 6-DoF IMU so this is a
            pseudo-forward — stable within a set, not comparable
            across sessions.
        y : lateral (frontal axis). Expected magnitude is tiny for
            bench.
        z : vertical. Positive is up. ``z[0] = 0`` at rep start (top of
            lift = previous lockout), dips negative through chest, and
            returns toward 0 at the concentric lockout.

    All position arrays are in metres and have length
    ``len(t_s) == len(x_m) == len(y_m) == len(z_m)``.
    """

    num: int = Field(description="1-indexed rep number")

    start_s: float = Field(
        description="Absolute session time (s) at rep start (top of lift)"
    )
    chest_s: float = Field(
        description="Absolute session time (s) at chest turnaround"
    )
    lockout_s: float = Field(
        description="Absolute session time (s) at concentric lockout"
    )
    end_s: float = Field(
        description="Absolute session time (s) at rep end"
    )
    duration_s: float = Field(description="Rep window duration (s)")

    t_s: List[float] = Field(
        description="Relative time within the rep window, starts at 0"
    )
    x_m: List[float] = Field(description="Forward/back position (m)")
    y_m: List[float] = Field(description="Lateral position (m)")
    z_m: List[float] = Field(description="Vertical position (m)")

    chest_idx: int = Field(
        description="Index into t_s/x_m/y_m/z_m at chest turnaround"
    )
    lockout_idx: int = Field(
        description="Index into t_s/x_m/y_m/z_m at concentric lockout"
    )

    rom_m: float = Field(description="Vertical range of motion (m)")
    peak_x_dev_m: float = Field(
        description="Max forward/back deviation from chest (m)"
    )
    peak_y_dev_m: float = Field(
        description="Max lateral deviation from chest (m)"
    )


class BarPathResponse(BaseModel):
    session_id: str
    fs_hz: float
    duration_s: float
    n_reps: int
    reps: List[BarPathRep]
    notes: str = ""
