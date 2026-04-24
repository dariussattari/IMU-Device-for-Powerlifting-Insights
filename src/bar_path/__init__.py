"""Bar-path reconstruction from a single barbell-mounted IMU.

Public API
----------
    reconstruct_session(df, fs_hz=None) -> BarPathResult
    reconstruct_csv(csv_path) -> BarPathResult

The algorithm follows the single-IMU guidelines that this project targets:

    1. Estimate sensor orientation from gyro+accel with a complementary
       filter, initialized from the gravity vector during the pre-lift
       calibration window. Yaw is unobservable without a magnetometer,
       so the world frame is anchored so that the bar's initial long
       axis projects onto +X.

    2. Rotate body-frame acceleration into the world frame and subtract
       [0, 0, g] to recover linear acceleration in world coordinates.

    3. Segment the session into reps using the vertical-velocity
       sign-change detector already used elsewhere in this repo (kept
       as a hard dependency on src/rep_counting/sign_change_rep_counter).

    4. For each rep's full cycle (lockout → eccentric → chest →
       concentric → lockout) we integrate twice with zero-velocity
       anchoring at both endpoints and per-axis endpoint detrending.
       The bar is at rest at both ends of the cycle, so any drift shows
       up as a linear ramp — which we remove. This bounds drift to
       within a single rep.

    5. We report per-rep x (forward/back), y (vertical), z (lateral)
       position traces relative to the rep's starting pose.
"""
from __future__ import annotations

from .reconstruct import (  # noqa: F401
    BarPathResult,
    RepBarPath,
    reconstruct_csv,
    reconstruct_session,
)

__all__ = [
    "BarPathResult",
    "RepBarPath",
    "reconstruct_csv",
    "reconstruct_session",
]
