"""Complementary-filter attitude estimation for a 6-DoF IMU.

A single IMU gives us accel + gyro at each sample. Gyro integration
drifts quickly (bias + rate noise), and accel alone is only valid when
the bar is stationary (it then measures -g in body frame). A
complementary filter combines the two: gyro provides fast attitude
updates and accel provides a slow absolute reference for the tilt
component (pitch/roll). Yaw is unobservable without a magnetometer.

This file implements a minimal Mahony-style complementary filter. It is
deliberately small and dependency-light so it can be read end-to-end.

Inputs are SI units:  accel in m/s², gyro in rad/s.
Output is a quaternion in scalar-first (w, x, y, z) form, normalized.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

GRAVITY_MS2 = 9.80665


def _quat_mul(q: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Hamilton product q * r. Both are (w, x, y, z)."""
    w0, x0, y0, z0 = q
    w1, x1, y1, z1 = r
    return np.array([
        w0 * w1 - x0 * x1 - y0 * y1 - z0 * z1,
        w0 * x1 + x0 * w1 + y0 * z1 - z0 * y1,
        w0 * y1 - x0 * z1 + y0 * w1 + z0 * x1,
        w0 * z1 + x0 * y1 - y0 * x1 + z0 * w1,
    ])


def _quat_normalize(q: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(q)
    if n < 1e-12:
        return np.array([1.0, 0.0, 0.0, 0.0])
    return q / n


def quat_to_rotmat(q: np.ndarray) -> np.ndarray:
    """3x3 rotation matrix R such that v_world = R @ v_body."""
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z),     2 * (x * y - z * w),     2 * (x * z + y * w)],
        [    2 * (x * y + z * w), 1 - 2 * (x * x + z * z),     2 * (y * z - x * w)],
        [    2 * (x * z - y * w),     2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def quat_from_gravity(g_body: np.ndarray) -> np.ndarray:
    """Build a quaternion that rotates body → world s.t. the measured
    gravity direction in the body frame maps to +Z_world.

    Yaw is left arbitrary (set to 0). This is appropriate when we have no
    magnetometer: we can only observe tilt, not heading.
    """
    g = np.asarray(g_body, dtype=float)
    g = g / max(np.linalg.norm(g), 1e-12)

    # A proper-acceleration accelerometer at rest reads +g in the
    # direction *opposite* gravity — i.e. the accel vector in the
    # body frame points *up*. So the body-frame "up" direction is
    # +g_body, not -g_body. We want R such that R @ up_body = +Z_world.
    up_body = g
    # We want R such that R @ up_body = (0,0,1).
    target = np.array([0.0, 0.0, 1.0])
    v = np.cross(up_body, target)
    s = np.linalg.norm(v)
    c = float(np.dot(up_body, target))
    if s < 1e-8:
        # up_body already aligned with target (or exactly anti-aligned).
        if c > 0:
            return np.array([1.0, 0.0, 0.0, 0.0])
        # 180° rotation around any axis perpendicular to up_body
        axis = np.array([1.0, 0.0, 0.0])
        if abs(up_body[0]) > 0.9:
            axis = np.array([0.0, 1.0, 0.0])
        return _quat_normalize(np.array([0.0, axis[0], axis[1], axis[2]]))

    axis = v / s
    angle = np.arctan2(s, c)
    half = 0.5 * angle
    return _quat_normalize(np.array([
        np.cos(half),
        axis[0] * np.sin(half),
        axis[1] * np.sin(half),
        axis[2] * np.sin(half),
    ]))


def estimate_orientation(
    accel: np.ndarray,
    gyro: np.ndarray,
    dt: np.ndarray,
    *,
    cal_samples: int = 200,
    stationary_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Estimate body→world orientation as a per-sample quaternion.

    Strategy (pause-anchored, not a pure complementary filter):

        * Whenever the bar is stationary, gravity is the only accel and
          we can solve for orientation exactly from a single sample —
          up to the unobservable yaw. We trust those samples fully.

        * Between stationary windows, the bar is in motion so accel has
          dynamic components; we can't trust it for attitude. We fall
          back to the rotation from the last stationary window. For a
          single-IMU barbell this is accurate enough: the bar's
          orientation doesn't meaningfully change during one rep.

        * If no stationary mask is supplied we use the initial
          calibration window only, giving a single static orientation
          for the whole session. That is exactly what the user's
          guideline "calibrate orientation before the set" prescribes.

    We deliberately do NOT integrate gyro across the whole session,
    because double-integration drift on the *tilt* component after one
    bad unrack is enough to invert the world Z axis. Pause-anchored
    orientation is robust to that failure mode.

    Parameters
    ----------
    accel : (N, 3) body-frame acceleration in m/s²
    gyro  : (N, 3) body-frame angular velocity in rad/s   (unused in the
            current estimator; kept for API stability and future use)
    dt    : (N,) per-sample Δt (unused in the current estimator)
    cal_samples : how many leading samples to average for the initial
                  gravity estimate (bar assumed stationary in rack)
    stationary_mask : optional (N,) bool mask of samples where the bar
                      is at rest. When provided, we re-fit the rotation
                      inside each contiguous stationary run and apply it
                      from the *midpoint* of that run forward.

    Returns
    -------
    quats : (N, 4) quaternions (w, x, y, z), body → world.
    """
    del gyro, dt  # reserved for future AHRS variants

    accel = np.asarray(accel, dtype=float)
    n = len(accel)
    if n == 0:
        return np.zeros((0, 4))

    # ── Initial orientation from calibration gravity ────────────────
    m = min(cal_samples, n)
    g_cal = np.mean(accel[:m], axis=0)
    q0 = quat_from_gravity(g_cal)

    quats = np.tile(q0, (n, 1))

    if stationary_mask is None:
        return quats

    mask = np.asarray(stationary_mask, dtype=bool)
    if mask.shape != (n,):
        return quats

    # Find contiguous stationary runs
    runs: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            runs.append((i, j - 1))
            i = j
        else:
            i += 1
    if not runs:
        return quats

    # For each run, build a rotation from its mean accel, then apply it
    # from the run's midpoint up to the midpoint of the next run. This
    # interpolation-by-halves scheme keeps the rotation "centered" on
    # the stationary evidence while still covering the full timeline.
    midpoints = [(lo + hi) // 2 for lo, hi in runs]
    run_quats = [
        quat_from_gravity(np.mean(accel[lo:hi + 1], axis=0))
        for lo, hi in runs
    ]

    # Samples before the first run → use the calibration quat if the
    # first run starts after sample 0, otherwise use the first run's quat.
    first_mid = midpoints[0]
    quats[:first_mid + 1] = run_quats[0] if runs[0][0] == 0 else q0

    for k in range(len(runs) - 1):
        start = midpoints[k]
        end = midpoints[k + 1]
        quats[start:end] = run_quats[k]

    quats[midpoints[-1]:] = run_quats[-1]

    # Re-normalize (cheap guarantee)
    norms = np.linalg.norm(quats, axis=1, keepdims=True)
    norms[norms < 1e-12] = 1.0
    return quats / norms


def rotate_body_to_world(vec_body: np.ndarray, quats: np.ndarray) -> np.ndarray:
    """Rotate a (N, 3) body-frame vector series into the world frame
    using per-sample quaternions (N, 4). Returns (N, 3).

    Vectorized: applies R_i to vec_body[i] for every i.
    """
    w = quats[:, 0]
    x = quats[:, 1]
    y = quats[:, 2]
    z = quats[:, 3]

    # R rows (see quat_to_rotmat)
    r00 = 1 - 2 * (y * y + z * z)
    r01 = 2 * (x * y - z * w)
    r02 = 2 * (x * z + y * w)
    r10 = 2 * (x * y + z * w)
    r11 = 1 - 2 * (x * x + z * z)
    r12 = 2 * (y * z - x * w)
    r20 = 2 * (x * z - y * w)
    r21 = 2 * (y * z + x * w)
    r22 = 1 - 2 * (x * x + y * y)

    vx = vec_body[:, 0]
    vy = vec_body[:, 1]
    vz = vec_body[:, 2]

    out = np.empty_like(vec_body)
    out[:, 0] = r00 * vx + r01 * vy + r02 * vz
    out[:, 1] = r10 * vx + r11 * vy + r12 * vz
    out[:, 2] = r20 * vx + r21 * vy + r22 * vz
    return out
