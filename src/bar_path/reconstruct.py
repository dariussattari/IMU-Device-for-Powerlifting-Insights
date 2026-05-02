"""Bar-path reconstruction: IMU samples → per-rep 2D/3D trajectory.

End-to-end pipeline:

    CSV  →  filter + gravity-compensate in world frame
         →  integrate twice per rep with endpoint anchoring
         →  per-rep (x, y, z) path relative to rep start

Design notes
------------
* A single barbell IMU cannot give stable *absolute* position over long
  durations — double integration turns accel bias into quadratic drift.
  The mitigation (standard in sports-IMU literature) is to bound the
  problem to the length of a single rep and use the rep boundaries as
  anchors. The bar is stationary (v=0) at both ends of each rep, so
  velocity drift after integration is a linear ramp we subtract.
  We integrate over the *full* lockout→chest→lockout window in one
  pass: both endpoints are at the same stationary lockout pose, so
  X, Y, AND Z all legitimately return to their starting value, and we
  endpoint-anchor every axis. ROM lives in the middle of the window
  (at chest), not at an endpoint, so anchoring doesn't erase the lift.

* The world frame is Z = up, X = bar's initial forward/back direction,
  Y = bar's initial lateral direction. Yaw is not observable without a
  magnetometer, so at t=0 we pin X to the horizontal projection of the
  IMU body's +X axis. This keeps "forward" meaningful for the sagittal-
  plane bar-path plot the frontend draws.

* Orientation is tracked with a Mahony-style complementary filter
  (src/bar_path/orientation.py). Gravity is removed in the world frame
  after rotation, not in the body frame, so we handle bar tilt properly.

* Reps are detected with the project's existing sign-change rep
  counter (src/rep_counting/sign_change_rep_counter.py). We extend each
  concentric rep backward through the preceding eccentric phase so the
  reconstructed window is full-cycle (lockout → chest → lockout). Both
  ends are stationary, which gives us the per-axis drift anchors.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt

from .orientation import (
    GRAVITY_MS2,
    estimate_orientation,
    rotate_body_to_world,
)

# Re-use the project's existing rep detector. We don't want a second
# implementation drifting out of sync with velocity_metrics / analyze.
_REP_COUNT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "rep_counting")
)
if _REP_COUNT_DIR not in sys.path:
    sys.path.insert(0, _REP_COUNT_DIR)
from sign_change_rep_counter import (  # noqa: E402
    build_reps,
    compute_vy,
    filter_by_post_motion,
    filter_by_rerack_gyro,
)


# ─────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────
ACCEL_LP_HZ = 15.0         # Low-pass cutoff on raw accel before integration
GYRO_LP_HZ = 15.0          # Low-pass cutoff on raw gyro
FILTER_ORDER = 4
CAL_DURATION_S = 1.0       # Pre-lift still window used for orientation + bias
# Body-frame stationarity thresholds (no orientation needed to evaluate):
#   bar is still when |a_body| ≈ g (no dynamic accel) AND |gyro| ≈ 0.
BODY_ACCEL_STILL_TOL = 1.0   # m/s² deviation from g on |a_body|
BODY_GYRO_STILL_TOL = 0.30   # rad/s — |gyro|
ZUPT_MIN_LEN_S = 0.10      # require ≥ 100 ms of contiguous stillness
ECC_BACKTRACK_S = 2.5      # max seconds we'll look back for rep-start rest
REP_PATH_SAMPLES = 120     # points per rep in the downsampled output


# ─────────────────────────────────────────────────────────────────────
# Result types (pure dataclasses — serialized elsewhere)
# ─────────────────────────────────────────────────────────────────────
@dataclass
class RepBarPath:
    num: int
    start_s: float           # absolute session time at rep start (rest)
    end_s: float             # absolute session time at rep end (rest)
    chest_s: float           # absolute session time at chest turnaround
    lockout_s: float         # absolute session time at concentric lockout
    duration_s: float
    t_s: List[float]         # (REP_PATH_SAMPLES,) — relative time, starts at 0
    x_m: List[float]         # forward/back, 0 at rep start
    y_m: List[float]         # lateral, 0 at rep start
    z_m: List[float]         # vertical, 0 at rep start
    chest_idx: int           # index of chest within t_s / positions
    lockout_idx: int         # index of lockout within t_s / positions
    rom_m: float             # vertical range of motion (|max(z) - min(z)|)
    peak_x_dev_m: float      # max |x| — forward/back drift magnitude
    peak_y_dev_m: float      # max |y| — lateral drift magnitude


@dataclass
class BarPathResult:
    fs_hz: float
    duration_s: float
    n_reps: int
    reps: List[RepBarPath] = field(default_factory=list)
    notes: str = ""


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
def _butter_lp(x: np.ndarray, fs: float, cutoff_hz: float,
               order: int = FILTER_ORDER) -> np.ndarray:
    nyq = fs / 2.0
    b, a = butter(order, cutoff_hz / nyq, btype="low")
    return filtfilt(b, a, x)


def _body_stationary_mask(a_body_mag: np.ndarray,
                          gyro_mag: np.ndarray,
                          fs: float) -> np.ndarray:
    """Return a bool mask marking samples where the bar is stationary.

    Detected in the *body* frame so no orientation estimate is needed:

        ``bar is still  ⇔  ||a_body| − g| < BODY_ACCEL_STILL_TOL
                          AND |gyro| < BODY_GYRO_STILL_TOL``

    plus a ≥ZUPT_MIN_LEN_S contiguity requirement. At rest the sensor
    reads +g in the up direction regardless of tilt, so |a_body| = g is
    a rotation-invariant stillness check.
    """
    still = (
        (np.abs(a_body_mag - GRAVITY_MS2) < BODY_ACCEL_STILL_TOL)
        & (gyro_mag < BODY_GYRO_STILL_TOL)
    )
    min_len = max(1, int(ZUPT_MIN_LEN_S * fs))
    out = np.zeros_like(still, dtype=bool)
    run_start = None
    for i, s in enumerate(still):
        if s and run_start is None:
            run_start = i
        elif not s and run_start is not None:
            if i - run_start >= min_len:
                out[run_start:i] = True
            run_start = None
    if run_start is not None and len(still) - run_start >= min_len:
        out[run_start:] = True
    return out


def _rep_subwindows(
    chest_idx: int,
    lockout_idx: int,
    vy: np.ndarray,
    prev_lockout_idx: int,
    next_chest_idx: int,
    fs: float,
) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Return ``(ecc_window, conc_window)`` — two separate sub-windows
    for a rep, each with v ≈ 0 at both endpoints.

    We integrate eccentric and concentric *separately* because double
    integration over a single long window accumulates bias into
    inflated displacement. Two short windows (≤ ~1.2 s each) with
    clean v=0 endpoints at every boundary are much better-behaved.

    Boundaries
    ----------
        eccentric : [ecc_start, chest_idx]
            ecc_start = the last sign-change of vy before chest_idx,
            searched in (prev_lockout_idx, chest_idx). vy transitions
            from ≈0 (lockout hold) to negative at that crossing — a
            clean v=0 anchor. Capped to 1.5 s of eccentric maximum.

        concentric : [chest_idx, conc_end]
            conc_end = lockout_idx (the detector's zero-crossing of vy
            at the top of the lift). Both endpoints are zero-crossings
            by construction, so v=0 at each.
    """
    n = len(vy)
    sig = np.sign(vy)
    for i in range(1, len(sig)):
        if sig[i] == 0:
            sig[i] = sig[i - 1]
    crossings = np.where(np.diff(sig) != 0)[0] + 1

    # ── Eccentric start ──
    ecc_floor = max(0, chest_idx - int(1.5 * fs))
    lo_bound = max(ecc_floor, prev_lockout_idx + int(0.05 * fs))
    mask = (crossings >= lo_bound) & (crossings < chest_idx - int(0.1 * fs))
    preceding = crossings[mask]
    if len(preceding) > 0:
        ecc_start = int(preceding[-1])
    else:
        ecc_start = lo_bound

    # ── Concentric end: just use the detector's lockout ──
    hi_bound = min(n - 1, next_chest_idx - int(0.05 * fs))
    conc_end = min(int(lockout_idx), hi_bound)

    return (ecc_start, int(chest_idx)), (int(chest_idx), conc_end)


def _integrate_subwindow(
    t: np.ndarray,
    accel_world: np.ndarray,
    start: int,
    end: int,
    anchor_pos_axes: Tuple[bool, bool, bool] = (True, True, True),
) -> np.ndarray:
    """Twice-integrate ``accel_world[start:end+1]`` with linear endpoint
    anchoring on velocity (always) and position (per-axis).

    Velocity is always endpoint-anchored. Both endpoints of every
    sub-window we pass in are vy zero-crossings (rep boundaries), so
    v=0 holds physically and any nonzero v after integration is
    accelerometer bias drift — subtracting the line that joins
    v[0] → v[end] removes it.

    Position is endpoint-anchored only on the axes given by
    ``anchor_pos_axes``.

    Use ``(True, True, True)`` when both endpoints are at the same
    stationary pose (e.g., the full lockout→chest→lockout window): the
    bar genuinely returns to its starting position on every axis, so
    anchoring removes the linear drift component everywhere. The lift's
    ROM still shows up: chest depth is in the *middle* of the window,
    not at an endpoint.

    Use ``(True, True, False)`` when only the *concentric* sub-window
    is being integrated (chest→lockout): the bar moves by ROM between
    those endpoints, and anchoring Z would erase the lift. X and Y are
    safe to anchor (lateral and forward drift return close to zero).
    """
    if end <= start:
        return np.zeros((0, 3))

    t_seg = t[start:end + 1] - t[start]
    a_seg = accel_world[start:end + 1]
    dtvec = np.diff(t_seg)

    pos = np.zeros_like(a_seg)
    for ax in range(3):
        vel = np.concatenate((
            [0.0],
            np.cumsum(0.5 * (a_seg[1:, ax] + a_seg[:-1, ax]) * dtvec),
        ))
        vel = _detrend_endpoints(vel)
        p = np.concatenate((
            [0.0],
            np.cumsum(0.5 * (vel[1:] + vel[:-1]) * dtvec),
        ))
        if anchor_pos_axes[ax]:
            p = _detrend_endpoints(p)
        pos[:, ax] = p

    return pos


def _detrend_endpoints(series: np.ndarray) -> np.ndarray:
    """Subtract the straight line that joins series[0] → series[-1].

    After this, series[0] == series[-1] == 0 (up to float precision).
    This is how we remove the linear drift that accumulates across one
    double-integration window — valid because we chose endpoints where
    the bar is at rest.
    """
    n = len(series)
    if n < 2:
        return series - series[0] if n == 1 else series
    ramp = np.linspace(series[0], series[-1], n)
    return series - ramp


def _resample(arr: np.ndarray, n_out: int) -> np.ndarray:
    """Linearly resample a 1-D array to exactly n_out points."""
    if len(arr) == n_out:
        return arr.astype(float)
    if len(arr) < 2:
        return np.full(n_out, float(arr[0]) if len(arr) == 1 else 0.0)
    x_old = np.linspace(0.0, 1.0, len(arr))
    x_new = np.linspace(0.0, 1.0, n_out)
    return np.interp(x_new, x_old, arr)


# ─────────────────────────────────────────────────────────────────────
# Main entry points
# ─────────────────────────────────────────────────────────────────────
def reconstruct_csv(csv_path: str) -> BarPathResult:
    """Convenience: load a session CSV and run the full pipeline."""
    df = pd.read_csv(csv_path)
    return reconstruct_session(df)


def reconstruct_session(
    df: pd.DataFrame,
    fs_hz: Optional[float] = None,
) -> BarPathResult:
    """Reconstruct per-rep bar paths from a session DataFrame.

    The DataFrame must contain the columns written by the project's
    firmware: ``timestamp_ms, a1x, a1y, a1z, g1x, g1y, g1z``. Units are
    SI (m/s², rad/s, ms).
    """
    required = {"timestamp_ms", "a1x", "a1y", "a1z", "g1x", "g1y", "g1z"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"bar_path.reconstruct_session: missing required columns "
            f"{sorted(missing)}"
        )

    # ── Time axis + fs ───────────────────────────────────────────────
    t = df["timestamp_ms"].values.astype(float) / 1000.0
    if len(t) < 2:
        return BarPathResult(
            fs_hz=float(fs_hz or 0.0),
            duration_s=0.0,
            n_reps=0,
            reps=[],
            notes="not enough samples",
        )
    dts = np.diff(t, prepend=t[0])
    if fs_hz is None:
        fs = 1.0 / float(np.median(np.diff(t)))
    else:
        fs = float(fs_hz)

    # ── Body-frame signals (low-passed) ──────────────────────────────
    accel_body = np.column_stack([
        _butter_lp(df["a1x"].values.astype(float), fs, ACCEL_LP_HZ),
        _butter_lp(df["a1y"].values.astype(float), fs, ACCEL_LP_HZ),
        _butter_lp(df["a1z"].values.astype(float), fs, ACCEL_LP_HZ),
    ])
    gyro_body = np.column_stack([
        _butter_lp(df["g1x"].values.astype(float), fs, GYRO_LP_HZ),
        _butter_lp(df["g1y"].values.astype(float), fs, GYRO_LP_HZ),
        _butter_lp(df["g1z"].values.astype(float), fs, GYRO_LP_HZ),
    ])

    # ── Stationary detection (body-frame, no orientation needed) ─────
    a_body_mag = np.linalg.norm(accel_body, axis=1)
    gyro_mag_vec = np.linalg.norm(gyro_body, axis=1)
    cal_samples = max(1, int(CAL_DURATION_S * fs))
    stationary = _body_stationary_mask(a_body_mag, gyro_mag_vec, fs)
    # Force the calibration window to count as stationary (the lift
    # protocol guarantees the bar is still on the rack at t=0).
    stationary[:cal_samples] = True

    # ── Orientation: a single rotation fitted from the pre-lift
    # calibration window and held constant. For a powerlifting set the
    # bar's tilt doesn't meaningfully change during the set (lifter
    # starts and ends each rep in the same lockout pose), and adding
    # gyro-based updates has, in practice, introduced more drift than
    # it corrects — one bad unrack gives an inverted world-Z. The
    # calibration-only rotation is the safer default. ────────────────
    quats = estimate_orientation(
        accel_body, gyro_body, dts,
        cal_samples=cal_samples,
        stationary_mask=None,
    )

    # ── World-frame linear acceleration ──────────────────────────────
    accel_world = rotate_body_to_world(accel_body, quats)
    accel_world[:, 2] -= GRAVITY_MS2

    # Tiny residual bias from calibration (world frame should read ~0
    # when the bar is still at the start): subtract the mean of the
    # calibration window on every axis.
    bias_world = accel_world[:cal_samples].mean(axis=0)
    accel_world = accel_world - bias_world

    # ── Rep detection (same as analyze.py / velocity_metrics) ────────
    _, vy_detect, gyro_mag_smooth, fs_detect = compute_vy(df)
    # compute_vy re-derives fs; for internal consistency with the
    # detected rep indices we use its fs.
    fs_rep = float(fs_detect) if fs_detect else fs

    rep_candidates = build_reps(vy_detect, v_hi=0.25, fs=fs_rep)
    rep_candidates = filter_by_rerack_gyro(
        rep_candidates, gyro_mag_smooth, fs_rep
    )
    rep_candidates = filter_by_post_motion(
        rep_candidates, vy_detect, gyro_mag_smooth, fs_rep
    )

    if len(rep_candidates) == 0:
        return BarPathResult(
            fs_hz=fs, duration_s=float(t[-1] - t[0]),
            n_reps=0, reps=[], notes="no reps detected",
        )

    # ── Per-rep reconstruction ───────────────────────────────────────
    # We reconstruct each rep's path over the FULL lockout→chest→lockout
    # window in a single double-integration with endpoint anchoring on
    # every axis:
    #
    #     [ecc_start (vy zero-crossing before descent) → lockout]
    #
    # Both endpoints are at the same stationary lockout pose, so v=0
    # AND p=0 on every axis at both ends — anchoring removes the linear
    # drift component everywhere, including Z. ROM lives in the *middle*
    # of the window (at chest), so this anchoring doesn't erase it.
    #
    # If the eccentric leg can't be cleanly identified (no plausible vy
    # zero-crossing in the right window), we fall back to a *mirrored*
    # concentric for the descent half — a common simplification in
    # commercial VBT devices (they assume eccentric and concentric
    # trace approximately the same path).
    n_samples = len(t)
    reps_out: List[RepBarPath] = []
    for i, rep in enumerate(rep_candidates):
        chest_idx_abs = int(rep["chest_idx"])
        lockout_idx_abs = int(rep["lockout_idx"])
        prev_lockout = (
            int(rep_candidates[i - 1]["lockout_idx"]) if i > 0 else 0
        )
        next_chest = (
            int(rep_candidates[i + 1]["chest_idx"])
            if i + 1 < len(rep_candidates) else n_samples - 1
        )

        (ecc_s, ecc_e), (conc_s, conc_e) = _rep_subwindows(
            chest_idx_abs, lockout_idx_abs, vy_detect,
            prev_lockout_idx=prev_lockout,
            next_chest_idx=next_chest,
            fs=fs,
        )

        # Concentric is mandatory — it has the cleanest v=0 anchors.
        if (conc_e - conc_s) < int(0.2 * fs):
            continue

        # Try the full lockout→chest→lockout integration first. Accept
        # it if the eccentric duration is plausible AND the resulting
        # path has chest as its deepest point (sanity that integration
        # didn't drift past the chest depth somewhere else).
        ecc_dur_s = (ecc_e - ecc_s) / fs
        have_ecc = False
        pos_full = np.zeros((0, 3))
        if 0.25 <= ecc_dur_s <= 1.5:
            pos_try = _integrate_subwindow(
                t, accel_world, ecc_s, conc_e,
                anchor_pos_axes=(True, True, True),
            )
            if len(pos_try) > 0:
                chest_local = chest_idx_abs - ecc_s
                z_try = pos_try[:, 2]
                if (
                    0 <= chest_local < len(z_try)
                    and z_try[chest_local] < 0
                    and z_try[chest_local] <= z_try.min() + 0.03
                ):
                    pos_full = pos_try
                    have_ecc = True

        if have_ecc:
            t_full = t[ecc_s:conc_e + 1] - t[ecc_s]
            chest_in_full = chest_idx_abs - ecc_s
            lockout_in_full = len(pos_full) - 1
            start_s_abs = float(t[ecc_s])
        else:
            # Concentric-only fallback. Anchor X/Y but not Z (chest and
            # lockout are at different vertical heights), then mirror
            # the concentric for the eccentric half so the plotted path
            # is still a visible J-curve.
            pos_conc = _integrate_subwindow(
                t, accel_world, conc_s, conc_e,
                anchor_pos_axes=(True, True, False),
            )
            if len(pos_conc) == 0:
                continue
            conc_t = t[conc_s:conc_e + 1] - t[conc_s]
            mirror_pos = pos_conc[::-1].copy()
            mirror_t = conc_t[-1] - conc_t[::-1]
            pos_full = np.vstack([mirror_pos[:-1], pos_conc])
            t_full = np.concatenate([mirror_t[:-1], conc_t + conc_t[-1]])
            # Translate so start is at (0,0,0). Mirror starts at
            # lockout (z = +Δz_conc) and pos_conc ends at lockout, so
            # after the shift: start ≈ 0, chest ≈ −Δz_conc, end ≈ 0.
            pos_full = pos_full - pos_full[0]
            chest_in_full = len(mirror_pos) - 1
            lockout_in_full = len(pos_full) - 1
            start_s_abs = float(t[conc_s]) - float(conc_t[-1])

        # ── Downsample to fixed length for the frontend ──────────────
        t_out = _resample(t_full, REP_PATH_SAMPLES)
        x_out = _resample(pos_full[:, 0], REP_PATH_SAMPLES)
        y_out = _resample(pos_full[:, 1], REP_PATH_SAMPLES)
        z_out = _resample(pos_full[:, 2], REP_PATH_SAMPLES)

        chest_ds = int(round(chest_in_full / max(1, len(pos_full) - 1)
                             * (REP_PATH_SAMPLES - 1)))
        lockout_ds = int(round(lockout_in_full / max(1, len(pos_full) - 1)
                               * (REP_PATH_SAMPLES - 1)))
        chest_ds = max(0, min(REP_PATH_SAMPLES - 1, chest_ds))
        lockout_ds = max(0, min(REP_PATH_SAMPLES - 1, lockout_ds))

        # ── Summary metrics ──────────────────────────────────────────
        rom = float(np.ptp(z_out))
        peak_x = float(np.max(np.abs(x_out - x_out[chest_ds])))
        peak_y = float(np.max(np.abs(y_out - y_out[chest_ds])))

        reps_out.append(RepBarPath(
            num=i + 1,
            start_s=start_s_abs,
            end_s=float(t[conc_e]),
            chest_s=float(t[chest_idx_abs]),
            lockout_s=float(t[lockout_idx_abs]),
            duration_s=float(t_full[-1]),
            t_s=t_out.tolist(),
            x_m=x_out.tolist(),
            y_m=y_out.tolist(),
            z_m=z_out.tolist(),
            chest_idx=chest_ds,
            lockout_idx=lockout_ds,
            rom_m=rom,
            peak_x_dev_m=peak_x,
            peak_y_dev_m=peak_y,
        ))

    return BarPathResult(
        fs_hz=fs,
        duration_s=float(t[-1] - t[0]),
        n_reps=len(reps_out),
        reps=reps_out,
        notes=(
            "calibration-only orientation + single full-rep "
            "(lockout→chest→lockout) double integration; velocity AND "
            "position endpoint-anchored on all 3 axes (legitimate — "
            "both endpoints at the same lockout pose). Real ROM is "
            "preserved at the chest mid-window."
        ),
    )
