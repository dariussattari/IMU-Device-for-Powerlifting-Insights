"""
Velocity metrics — per-rep kinematic extraction.

Computes the standard velocity-based-training metrics for each rep in a
bench-press session:

    MCV   mean concentric velocity (m/s)   — averaged across chest→lockout
    PCV   peak concentric velocity (m/s)
    MPV   mean propulsive velocity (m/s)   — averaged across chest→end of
          propulsion (last sample where linear-vertical accel ≥ 0)
    ROM   concentric range of motion (m)   — ∫vy dt over chest→lockout
    CD    concentric duration (s)
    TPV   time-to-peak velocity (s)        — chest → argmax(vy)
    EMV   mean eccentric velocity (m/s)    — averaged across lockout_prev
          → chest (sign-flipped, so reported as negative magnitude)
    EROM  eccentric range of motion (m)    — |∫vy dt| eccentric

Three integration pipelines ("methods") are implemented, each trying to
reduce a different source of drift error:

    A   baseline      LP5 → cumsum → HP0.3Hz filtfilt        (matches the
                     existing plot_session.py / sign_change_rep_counter.py
                     curve)
    B   per-rep      LP5 → trapezoid → linear detrend so that
        detrend      v(chest) = v(lockout) = 0 for every rep (bar is
                     momentarily at rest at every turnaround, so any
                     residual there is pure integration bias)
    C   ZUPT +       LP5 → trapezoid, with zero-velocity update (v:=0)
        detrend      whenever |gyro| AND accel-variance say the bar is
                     still, PLUS per-rep endpoint detrend
    D   hybrid       accel-level HP (0.1 Hz) → trapezoid → ZUPT → per-rep
                     detrend. Moves drift control upstream of integration
                     (so the integrator can't spin up), while still
                     anchoring rep endpoints at v=0.

Method D is the lowest-error option on this dataset (see compare_methods.py).
It is the default.

CLI:
    python3 src/velocity/velocity_metrics.py <csv> <annotations_csv>
        [--method A|B|C] [--out <json>]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import List, Tuple, Optional

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt

_trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz")  # NumPy 2.x compat

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rep_counting"))
# sign_change_rep_counter.py provides a robust zero-crossing-based rep
# detector. We use it to locate true concentric boundaries instead of
# trusting the annotator's click timing.
from sign_change_rep_counter import (  # noqa: E402
    build_reps as _sc_build_reps,
    filter_by_rerack_gyro as _sc_rerack_gyro,
    filter_by_post_motion as _sc_post_motion,
)

LP_CUTOFF_HZ = 5.0
HP_CUTOFF_HZ = 0.3
FILTER_ORDER = 4
GYRO_LP_HZ = 2.0
ZUPT_GYRO_THRESH = 0.15    # rad/s   — bar is "still"
ZUPT_ACCEL_STD_THRESH = 0.10  # m/s² std over 100 ms window
ZUPT_MIN_LEN_S = 0.10      # require at least 100 ms of stillness


# ────────────────────────────────────────────────────────────────────────
# Signal prep
# ────────────────────────────────────────────────────────────────────────
def _butter_lp(x: np.ndarray, fs: float, cutoff_hz: float, order: int = FILTER_ORDER):
    b, a = butter(order, cutoff_hz / (fs / 2), btype="low")
    return filtfilt(b, a, x)


def _butter_hp(x: np.ndarray, fs: float, cutoff_hz: float, order: int = FILTER_ORDER):
    b, a = butter(order, cutoff_hz / (fs / 2), btype="high")
    return filtfilt(b, a, x)


def prepare_signals(df: pd.DataFrame):
    """Return (t, ay_lin, gyro_mag, fs) — shared across every method."""
    t = df["timestamp_ms"].values.astype(float) / 1000.0
    fs = 1.0 / np.median(np.diff(t))

    # Calibration window = first ~1 s (bar still before unrack). Same as
    # plot_session.py so the curve matches the existing plots.
    cal_n = min(int(fs), len(df))
    ay_raw = df["a1y"].values.astype(float)
    ay_lin = ay_raw - np.mean(ay_raw[:cal_n])
    ay_lin = _butter_lp(ay_lin, fs, LP_CUTOFF_HZ)

    gx = df["g1x"].values.astype(float)
    gy = df["g1y"].values.astype(float)
    gz = df["g1z"].values.astype(float)
    gyro_mag = np.sqrt(gx**2 + gy**2 + gz**2)
    gyro_mag = _butter_lp(gyro_mag, fs, GYRO_LP_HZ, order=2)

    return t, ay_lin, gyro_mag, fs


# ────────────────────────────────────────────────────────────────────────
# Integration strategies (A = baseline HP, B = per-rep detrend, C = ZUPT)
# ────────────────────────────────────────────────────────────────────────
def integrate_vy_A(t: np.ndarray, ay_lin: np.ndarray) -> np.ndarray:
    """Baseline: cumulative sum integration then HP filter to kill drift."""
    fs = 1.0 / np.median(np.diff(t))
    dt = np.diff(t, prepend=t[0])
    vy = np.cumsum(ay_lin * dt)
    vy = _butter_hp(vy, fs, HP_CUTOFF_HZ)
    return vy


def _trapezoid_vy(t: np.ndarray, ay_lin: np.ndarray) -> np.ndarray:
    """Trapezoidal integration (more accurate than rect/cumsum)."""
    dt = np.diff(t)
    incr = 0.5 * (ay_lin[1:] + ay_lin[:-1]) * dt
    vy = np.concatenate(([0.0], np.cumsum(incr)))
    return vy


def integrate_vy_B(t: np.ndarray, ay_lin: np.ndarray,
                   rep_boundaries: List[Tuple[int, int]]) -> np.ndarray:
    """Per-rep linear detrend. For each rep window [chest, lockout], solve
    for a linear ramp to subtract so v(chest)=v(lockout)=0. Between reps
    we use the chained endpoint values as anchors."""
    vy = _trapezoid_vy(t, ay_lin)
    # Anchor points: every chest and lockout index sorted ascending.
    anchors = []
    for chest_i, lockout_i in rep_boundaries:
        anchors.append(chest_i)
        anchors.append(lockout_i)
    anchors = sorted(set(anchors))
    if not anchors:
        return vy - np.mean(vy)

    # Linear piecewise trend built from (anchor_i, vy[anchor_i])
    trend = np.interp(np.arange(len(vy)), anchors, vy[anchors])
    return vy - trend


def _zupt_mask(ay_lin: np.ndarray, gyro_mag: np.ndarray, fs: float) -> np.ndarray:
    """Boolean mask of samples where the bar is "still enough" to ZUPT."""
    win = max(3, int(0.1 * fs))
    # Rolling std of linear accel
    pad = win // 2
    a_padded = np.pad(ay_lin, pad, mode="edge")
    rolling_std = np.array([
        np.std(a_padded[i:i + win]) for i in range(len(ay_lin))
    ])
    still = (gyro_mag < ZUPT_GYRO_THRESH) & (rolling_std < ZUPT_ACCEL_STD_THRESH)

    # Require MIN_LEN_S contiguous stillness before accepting a run
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


ACCEL_HP_CUTOFF_HZ = 0.1  # used by Method D


def integrate_vy_D(t: np.ndarray, ay_lin: np.ndarray, gyro_mag: np.ndarray,
                   rep_boundaries: List[Tuple[int, int]]) -> Tuple[np.ndarray, np.ndarray]:
    """Hybrid: accel-level 0.1 Hz HP (remove slow bias drift BEFORE
    integration) + trapezoid + ZUPT + per-rep endpoint detrend."""
    fs = 1.0 / np.median(np.diff(t))
    ay_hp = _butter_hp(ay_lin, fs, ACCEL_HP_CUTOFF_HZ, order=2)
    vy = _trapezoid_vy(t, ay_hp)
    zupt = _zupt_mask(ay_hp, gyro_mag, fs)

    still_idx = np.where(zupt)[0]
    if len(still_idx) >= 2:
        drift = np.interp(np.arange(len(vy)), still_idx, vy[still_idx])
        vy = vy - drift
    elif len(still_idx) == 1:
        vy = vy - vy[still_idx[0]]

    anchors = sorted({a for pair in rep_boundaries for a in pair})
    if anchors:
        trend = np.interp(np.arange(len(vy)), anchors, vy[anchors])
        vy = vy - trend
    return vy, zupt


def integrate_vy_C(t: np.ndarray, ay_lin: np.ndarray, gyro_mag: np.ndarray,
                   rep_boundaries: List[Tuple[int, int]]) -> Tuple[np.ndarray, np.ndarray]:
    """ZUPT + per-rep endpoint detrend. Returns (vy, zupt_mask)."""
    fs = 1.0 / np.median(np.diff(t))
    vy = _trapezoid_vy(t, ay_lin)
    zupt = _zupt_mask(ay_lin, gyro_mag, fs)

    # ZUPT: linearly interpolate drift between successive still runs.
    # Concretely: for every still sample, vy should equal 0. Build a drift
    # signal that equals vy at still samples and is linearly interpolated
    # between, then subtract it everywhere.
    still_idx = np.where(zupt)[0]
    if len(still_idx) >= 2:
        drift = np.interp(np.arange(len(vy)), still_idx, vy[still_idx])
        vy = vy - drift
    elif len(still_idx) == 1:
        vy = vy - vy[still_idx[0]]

    # Per-rep endpoint detrend on top of ZUPT
    anchors = []
    for chest_i, lockout_i in rep_boundaries:
        anchors.append(chest_i)
        anchors.append(lockout_i)
    anchors = sorted(set(anchors))
    if anchors:
        trend = np.interp(np.arange(len(vy)), anchors, vy[anchors])
        vy = vy - trend
    return vy, zupt


# ────────────────────────────────────────────────────────────────────────
# Annotations → rep windows
# ────────────────────────────────────────────────────────────────────────
def parse_annotations(ann_path: str):
    """Return {initial_lockout_s, reps: [{num, chest_s, top_s}], rack_s}."""
    ann = pd.read_csv(ann_path)
    initial_lockout_s = None
    rack_s = None
    chests_s: List[float] = []
    tops: List[Tuple[int, float]] = []
    for _, row in ann.iterrows():
        lbl = str(row["label"]).strip()
        ts = float(row["timestamp_ms"]) / 1000.0
        if lbl == "lockout" and initial_lockout_s is None:
            initial_lockout_s = ts
        elif lbl == "chest":
            chests_s.append(ts)
        elif lbl == "rack":
            rack_s = ts
        elif re.fullmatch(r"\d+", lbl):
            tops.append((int(lbl), ts))
    tops.sort(key=lambda x: x[0])
    chests_s.sort()

    # Pair chests and tops. Each top N is preceded by one chest.
    reps = []
    for num, top_s in tops:
        # Nearest preceding chest
        preceding = [c for c in chests_s if c < top_s]
        if not preceding:
            continue
        chest_s = preceding[-1]
        reps.append({"num": num, "chest_s": chest_s, "top_s": top_s})
    return {
        "initial_lockout_s": initial_lockout_s,
        "reps": reps,
        "rack_s": rack_s,
    }


def reps_to_index_boundaries(t: np.ndarray, reps: list) -> List[Tuple[int, int]]:
    """Convert annotation times to sample indices (chest, lockout=top)."""
    out = []
    for rep in reps:
        ci = int(np.argmin(np.abs(t - rep["chest_s"])))
        li = int(np.argmin(np.abs(t - rep["top_s"])))
        if li <= ci:
            continue
        out.append((ci, li))
    return out


def snap_boundaries_to_zero_crossings(t: np.ndarray, vy_seed: np.ndarray,
                                      boundaries: List[Tuple[int, int]],
                                      max_snap_s: float = 0.15) -> List[Tuple[int, int]]:
    """Shift each (chest, lockout) pair to the nearest sign change of
    vy_seed within ±max_snap_s. Rationale: the annotator's click is only
    accurate to ≈50–150 ms. The *true* turnaround is where vy = 0; if we
    force v(chest)=v(lockout)=0 via endpoint detrend, we want those
    endpoints to actually be at zero-crossings of the signal. Otherwise
    the endpoint detrend overcorrects and distorts mid-rep kinematics.

    vy_seed can be any smooth velocity estimate (e.g. Method A output)."""
    sign = np.sign(vy_seed)
    # Treat exact zeros as the previous non-zero sign so sign changes are
    # counted once, not twice.
    for i in range(1, len(sign)):
        if sign[i] == 0:
            sign[i] = sign[i - 1]
    sign_change = np.where(np.diff(sign) != 0)[0] + 1

    if len(sign_change) == 0:
        return boundaries

    fs = 1.0 / np.median(np.diff(t))
    max_snap = int(max_snap_s * fs)

    def snap(idx: int, want_sign_after: int) -> int:
        """Find nearest sign change where sign flips to want_sign_after."""
        best = idx
        best_dist = max_snap + 1
        for cr in sign_change:
            if abs(cr - idx) > max_snap:
                continue
            after = sign[cr]
            if want_sign_after != 0 and after != want_sign_after:
                continue
            if abs(cr - idx) < best_dist:
                best = int(cr)
                best_dist = abs(cr - idx)
        return best

    snapped = []
    for ci, li in boundaries:
        # At chest the concentric begins, so vy goes − → + ⇒ want sign +
        new_ci = snap(ci, +1)
        # At lockout concentric ends, vy goes + → − ⇒ want sign −
        new_li = snap(li, -1)

        raw_dur = (li - ci) / fs
        new_dur = (new_li - new_ci) / fs
        # Guard against obviously wrong snaps (post-rack oscillation,
        # spurious mid-rep sign change). If the snapped duration deviates
        # by more than 40% from the annotated duration, revert to raw.
        if (new_li <= new_ci
                or new_dur < 0.6 * raw_dur
                or new_dur > 1.4 * raw_dur
                or new_dur < 0.2):  # reps are never <200 ms
            new_ci, new_li = ci, li
        snapped.append((new_ci, new_li))
    return snapped


# ────────────────────────────────────────────────────────────────────────
# Per-rep metric extraction
# ────────────────────────────────────────────────────────────────────────
@dataclass
class RepMetrics:
    num: int
    chest_s: float
    top_s: float
    duration_s: float
    mcv: float          # mean concentric velocity (m/s)
    pcv: float          # peak concentric velocity (m/s)
    mpv: float          # mean propulsive velocity (m/s)
    rom_m: float        # concentric ROM (m)
    tpv_s: float        # time to peak velocity (s) from chest
    emv: float          # mean eccentric velocity (m/s, negative)
    erom_m: float       # eccentric ROM magnitude (m)
    ecc_dur_s: float    # eccentric duration (s)
    propulsive_frac: float  # propulsive-phase fraction of concentric


def _rep_metrics(num: int, ci: int, li: int,
                 prev_li: Optional[int], t: np.ndarray, vy: np.ndarray,
                 ay_lin: np.ndarray) -> RepMetrics:
    # Concentric slice (inclusive of both endpoints)
    c_t = t[ci:li + 1]
    c_v = vy[ci:li + 1]
    c_a = ay_lin[ci:li + 1]
    dur = float(c_t[-1] - c_t[0])
    pcv = float(np.max(c_v))
    pk_idx_rel = int(np.argmax(c_v))
    tpv = float(c_t[pk_idx_rel] - c_t[0])

    # Trapezoidal for integrated quantities (higher accuracy than mean*dt)
    rom = float(_trapz(c_v, c_t))
    mcv = rom / max(dur, 1e-6)

    # Propulsive phase: chest → last sample where linear accel ≥ 0.
    # Per Sanchez-Medina: phase while applied force exceeds gravity (i.e.
    # bar is still accelerating upward). In our world-vertical linear-accel
    # signal, that's a_lin_y ≥ 0.
    prop_end_rel = pk_idx_rel  # fallback: peak velocity
    # Walk from peak forward while accel stays ≥ 0 (tie-break)
    for k in range(pk_idx_rel, len(c_a)):
        if c_a[k] < 0:
            prop_end_rel = k
            break
        prop_end_rel = k
    prop_slice_t = c_t[:prop_end_rel + 1]
    prop_slice_v = c_v[:prop_end_rel + 1]
    prop_dur = float(prop_slice_t[-1] - prop_slice_t[0]) if len(prop_slice_t) > 1 else 0.0
    mpv = (float(_trapz(prop_slice_v, prop_slice_t)) / max(prop_dur, 1e-6)
           if prop_dur > 0 else pcv)
    propulsive_frac = prop_dur / max(dur, 1e-6)

    # Eccentric slice
    if prev_li is not None and ci > prev_li:
        e_t = t[prev_li:ci + 1]
        e_v = vy[prev_li:ci + 1]
        ecc_dur = float(e_t[-1] - e_t[0])
        erom = float(_trapz(e_v, e_t))  # negative number (descent)
        emv = erom / max(ecc_dur, 1e-6)
    else:
        ecc_dur = 0.0
        erom = 0.0
        emv = 0.0

    return RepMetrics(
        num=num,
        chest_s=float(t[ci]),
        top_s=float(t[li]),
        duration_s=dur,
        mcv=mcv,
        pcv=pcv,
        mpv=mpv,
        rom_m=rom,
        tpv_s=tpv,
        emv=emv,
        erom_m=abs(erom),
        ecc_dur_s=ecc_dur,
        propulsive_frac=propulsive_frac,
    )


# ────────────────────────────────────────────────────────────────────────
# Top-level compute
# ────────────────────────────────────────────────────────────────────────
def _detector_boundaries(t: np.ndarray, vy_seed: np.ndarray,
                         gyro_mag: np.ndarray, fs: float):
    """Run the sign-change rep detector on vy_seed and return
    (chest_idx, lockout_idx) pairs for every KEPT rep. These boundaries
    land on real zero-crossings, which is what we want for integration."""
    cands = _sc_build_reps(vy_seed, 0.25, fs)
    after = _sc_rerack_gyro(cands, gyro_mag, fs, 1.5)
    kept = _sc_post_motion(after, vy_seed, gyro_mag, fs, 2.0, 0.7)
    return [(r["chest_idx"], r["lockout_idx"]) for r in kept]


def _match_detected_to_annotated(det_boundaries, ann_reps, t: np.ndarray,
                                 tol_s: float = 0.4):
    """Align detector reps with annotation rep numbers. Returns the
    subset of det_boundaries whose midpoint is within tol_s of an
    annotation's top timestamp, in the same order as ann_reps. Any
    unmatched annotations are skipped (they're tracked in diagnostics)."""
    ann_tops = [r["top_s"] for r in ann_reps]
    out = []
    used_ann = set()
    for ci, li in det_boundaries:
        ref = t[li]  # lockout timestamp
        best_j, best_dt = None, None
        for j, gt in enumerate(ann_tops):
            if j in used_ann:
                continue
            dt = abs(ref - gt)
            if best_dt is None or dt < best_dt:
                best_j, best_dt = j, dt
        if best_j is not None and best_dt <= tol_s:
            used_ann.add(best_j)
            out.append((ci, li, ann_reps[best_j]["num"]))
    out.sort(key=lambda x: x[2])  # order by rep number
    return out


def compute_metrics(csv_path: str, ann_path: Optional[str] = None,
                    method: str = "B",
                    snap: bool = True, use_detector: bool = True):
    """Run one method end-to-end. Returns dict with vy, metrics, diagnostics.

    Integration boundaries come from one of three sources:

        use_detector=True (default):  sign_change_rep_counter's detected
            chest/lockout indices (zero-crossings of a seed vy). These are
            physically correct (v=0 at a zero-crossing) so endpoint
            detrend doesn't distort the signal.

        use_detector=False, snap=True: annotation boundaries, snapped to
            the nearest sign-change within ±150 ms. Falls back to raw if
            the snap would produce an unreasonable duration.

        use_detector=False, snap=False: raw annotation boundaries.

    `snap` is ignored when use_detector=True.

    `ann_path` is optional. When omitted, `use_detector` must be True and
    `snap` must be False — rep numbers are assigned 1..N from the detector's
    order, and the first rep has no eccentric phase (prev_li is None).
    """
    if ann_path is None:
        if not use_detector:
            raise ValueError("ann_path is required when use_detector=False")
        if snap:
            raise ValueError("snap=True requires ann_path")

    df = pd.read_csv(csv_path)
    t, ay_lin, gyro_mag, fs = prepare_signals(df)

    if ann_path is not None:
        anns = parse_annotations(ann_path)
        raw_boundaries = reps_to_index_boundaries(t, anns["reps"])
    else:
        anns = {"initial_lockout_s": None, "reps": [], "rack_s": None}
        raw_boundaries = []

    if use_detector:
        vy_seed = integrate_vy_A(t, ay_lin)
        det_pairs = _detector_boundaries(t, vy_seed, gyro_mag, fs)
        if ann_path is not None:
            matched = _match_detected_to_annotated(det_pairs, anns["reps"], t)
            boundaries = [(ci, li) for ci, li, _ in matched]
            rep_nums = [num for _, _, num in matched]
        else:
            boundaries = [(ci, li) for ci, li in det_pairs]
            rep_nums = list(range(1, len(boundaries) + 1))
    elif snap and method in ("B", "C", "D"):
        vy_seed = integrate_vy_A(t, ay_lin)
        boundaries = snap_boundaries_to_zero_crossings(t, vy_seed, raw_boundaries)
        rep_nums = [r["num"] for r in anns["reps"][:len(boundaries)]]
    else:
        boundaries = raw_boundaries
        rep_nums = [r["num"] for r in anns["reps"][:len(boundaries)]]

    zupt_mask = None
    if method == "A":
        vy = integrate_vy_A(t, ay_lin)
    elif method == "B":
        vy = integrate_vy_B(t, ay_lin, boundaries)
    elif method == "C":
        vy, zupt_mask = integrate_vy_C(t, ay_lin, gyro_mag, boundaries)
    elif method == "D":
        vy, zupt_mask = integrate_vy_D(t, ay_lin, gyro_mag, boundaries)
    else:
        raise ValueError(f"unknown method: {method}")

    reps_out: List[RepMetrics] = []
    prev_li = None
    if anns["initial_lockout_s"] is not None:
        prev_li = int(np.argmin(np.abs(t - anns["initial_lockout_s"])))
    for num, (ci, li) in zip(rep_nums, boundaries):
        reps_out.append(_rep_metrics(num, ci, li, prev_li, t, vy, ay_lin))
        prev_li = li

    return {
        "csv": csv_path,
        "method": method,
        "fs": fs,
        "t": t,
        "vy": vy,
        "ay_lin": ay_lin,
        "gyro_mag": gyro_mag,
        "zupt_mask": zupt_mask,
        "boundaries": boundaries,
        "raw_boundaries": raw_boundaries,
        "annotations": anns,
        "reps": reps_out,
    }


# ────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv")
    p.add_argument("ann")
    p.add_argument("--method", choices=["A", "B", "C", "D"], default="B")
    p.add_argument("--no-snap", action="store_true",
                   help="Disable snap-to-zero-crossing of annotation boundaries")
    p.add_argument("--out", default=None, help="Optional JSON output path")
    args = p.parse_args()

    result = compute_metrics(args.csv, args.ann, args.method,
                             snap=not args.no_snap)
    rows = [asdict(r) for r in result["reps"]]

    print(f"File:   {args.csv}")
    print(f"Method: {args.method}   fs={result['fs']:.1f} Hz   reps={len(rows)}")
    hdr = f"{'#':>3} {'chest_s':>7} {'top_s':>7} {'CD':>5} {'MCV':>6} {'PCV':>6} {'MPV':>6} {'ROM':>6} {'TPV':>5} {'EMV':>6} {'EROM':>6}"
    print(hdr)
    for r in rows:
        print(f"{r['num']:>3} {r['chest_s']:>7.2f} {r['top_s']:>7.2f} "
              f"{r['duration_s']:>5.2f} {r['mcv']:>6.3f} {r['pcv']:>6.3f} "
              f"{r['mpv']:>6.3f} {r['rom_m']:>6.3f} {r['tpv_s']:>5.2f} "
              f"{r['emv']:>6.3f} {r['erom_m']:>6.3f}")

    if args.out:
        with open(args.out, "w") as f:
            json.dump({"csv": args.csv, "method": args.method, "reps": rows}, f, indent=2)
        print(f"Wrote → {args.out}")


if __name__ == "__main__":
    main()
