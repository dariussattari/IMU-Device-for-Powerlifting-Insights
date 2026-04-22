"""
1RM prediction from submaximal load-velocity data.

Given several bench-press sessions at known loads, extrapolate to the
lifter's 1-rep-maximum by fitting an individual load-velocity profile
(LVP) and projecting to a minimum-velocity threshold (MVT). Uses the
per-rep kinematics extracted by src/velocity/velocity_metrics.py and the
per-rep sticking-point features from src/sticking_point/sticking_point.py.

Background (velocity-based training, González-Badillo & Sánchez-Medina):
    The bench-press load-velocity relationship is strongly linear for an
    individual. Fitting a line to (load, velocity) points across several
    loads and extrapolating to the velocity the bar can barely move at
    1RM (the "minimum velocity threshold") recovers 1RM.

    Population MVT values for bench:
        MPV at 1RM ≈ 0.17 m/s       (González-Badillo 2010)
        MCV at 1RM ≈ 0.15 m/s
        PCV at 1RM ≈ 0.45 m/s

    Because these are population averages, per-individual LVP
    calibration generally outperforms them — but only when every set is
    executed at maximal intent. Submaximal sandbagging (common in
    warmup-style training sets) flattens the LVP and inflates the 1RM
    estimate. We therefore combine several estimators and weight by R²:

Estimators implemented:
    M1  MPV-LVP       best-MPV-per-set linear fit → MVT_MPV  (primary)
    M2  MCV-LVP       best-MCV-per-set linear fit → MVT_MCV
    M3  MPV-TOP2      mean of the top-2 MPV per set linear fit → MVT_MPV
                      (reduces rep-1 setup noise)
    M4  GB-pop-eq     González-Badillo population equation applied to
                      the heaviest-set best MPV. Independent of LVP
                      slope — useful as a sanity check when LVP is
                      ill-conditioned (R² low or slope non-negative).
    M5  Velocity-loss within-set velocity-loss percentage in the heaviest
                      set mapped to RIR → %1RM via the Pareja-Blanco /
                      Morán-Navarro table, then 1RM = L / %1RM.
    M6  Trimmed-LVP   best-MPV LVP after dropping the single worst-fit
                      point (robust to one sandbagged set; requires ≥ 4
                      sessions). Applied automatically when M1 is
                      ill-conditioned.

    Consensus = R²-weighted mean of M1-M3/M6 (each must have a negative
    slope and R² ≥ R2_MIN=0.5). If none of the LVP estimators qualify,
    fall back to M4/M5 mean.

Also reports 95% bootstrap confidence intervals for the primary
estimator by resampling the per-set rep pool.

CLI:
    python3 src/one_rm/one_rm.py --lifter D
    python3 src/one_rm/one_rm.py --lifter M --method-details
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Tuple

import numpy as np

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "..", "velocity"))
sys.path.insert(0, os.path.join(_HERE, "..", "sticking_point"))
sys.path.insert(0, os.path.join(_HERE, "..", "rep_counting"))
from velocity_metrics import compute_metrics  # noqa: E402
from sticking_point import compute_sticking  # noqa: E402

# ────────────────────────────────────────────────────────────────────────
# Thresholds (bench-press, literature-derived)
# ────────────────────────────────────────────────────────────────────────
MVT_MPV = 0.17    # m/s — mean propulsive velocity at 1RM (GB 2010)
MVT_MCV = 0.15    # m/s — mean concentric velocity at 1RM
MVT_PCV = 0.45    # m/s — peak concentric velocity at 1RM
R2_MIN = 0.50     # minimum acceptable LVP R² for an estimator to count

# González-Badillo 2011 bench MPV→%1RM population equation:
#   %1RM = 8.4326·MPV² − 73.501·MPV + 112.33
GB_A, GB_B, GB_C = 8.4326, -73.501, 112.33

# Velocity-loss → RIR table for bench (Morán-Navarro et al. 2017, adapted)
# Fractional velocity loss from rep 1 to last rep in a set → estimated
# RIR at end of set. For %1RM inference we combine this with reps-done.
# This table is coarser than MPV-based mapping; we use it as M5.
VL_TO_RIR = [
    (0.05, 8),   # ≤5% VL → ≥8 RIR (very easy, <60% 1RM)
    (0.10, 6),
    (0.15, 5),
    (0.20, 4),
    (0.25, 3),
    (0.30, 2),
    (0.40, 1),
    (0.60, 0),   # ≥60% VL → 0 RIR (true failure)
]

# Reps-at-load percentage (Baechle/Earle "repetition chart"), used with M5.
REPS_TO_PCT_1RM = {
    1: 1.00, 2: 0.955, 3: 0.925, 4: 0.90, 5: 0.875, 6: 0.85,
    7: 0.825, 8: 0.80, 9: 0.775, 10: 0.75, 11: 0.725, 12: 0.70,
}


# ────────────────────────────────────────────────────────────────────────
# Per-session feature extraction
# ────────────────────────────────────────────────────────────────────────
@dataclass
class SessionFeatures:
    name: str
    lifter: str
    load_lb: int
    n_reps_prescribed: int
    n_reps_detected: int
    rep_mpv: List[float]
    rep_mcv: List[float]
    rep_pcv: List[float]
    rep_tpv: List[float]
    rep_sp_depth: List[float]
    rep_sp_frac: List[float]

    # Aggregate statistics used by the estimators
    best_mpv: float         # max across the set
    best_mcv: float
    best_pcv: float
    top2_mpv: float         # mean of two highest MPVs (rep-order agnostic)
    rep1_mpv: float
    last_mpv: float
    vl_frac: float          # (best_mpv − last_mpv) / best_mpv


def _parse_session_name(name: str) -> Tuple[str, int, int]:
    """Return (lifter, load_lb, n_reps_prescribed) from a session filename
    like 'D_185_3_session_20260416_133914'."""
    parts = name.split("_")
    return parts[0], int(parts[1]), int(parts[2])


def extract_session_features(csv_path: str,
                             ann_path: Optional[str] = None,
                             method: str = "B",
                             name: Optional[str] = None,
                             lifter: Optional[str] = None,
                             load_lb: Optional[int] = None,
                             n_reps_prescribed: Optional[int] = None,
                             ) -> SessionFeatures:
    """Extract per-session features for 1RM estimation.

    `lifter`, `load_lb`, and `n_reps_prescribed` override filename parsing
    when supplied. When all three are omitted, the filename must follow
    the `{lifter}_{load}_{reps}_session_*` convention. `ann_path` is
    optional — the detector finds rep boundaries when omitted.
    """
    result = compute_sticking(csv_path, ann_path, method=method)
    reps = result["reps"]
    sticking = result["sticking"]
    nm = name or os.path.basename(csv_path).replace(".csv", "")

    if lifter is None or load_lb is None or n_reps_prescribed is None:
        parsed_lifter, parsed_load, parsed_n_rx = _parse_session_name(nm)
        lifter = lifter if lifter is not None else parsed_lifter
        load_lb = load_lb if load_lb is not None else parsed_load
        n_reps_prescribed = (n_reps_prescribed if n_reps_prescribed is not None
                             else parsed_n_rx)
    load = int(load_lb)
    n_rx = int(n_reps_prescribed)

    mpv = [float(r.mpv) for r in reps]
    mcv = [float(r.mcv) for r in reps]
    pcv = [float(r.pcv) for r in reps]
    tpv = [float(r.tpv_s) for r in reps]
    sp_d = [float(s.sp_depth) for s in sticking]
    sp_f = [float(s.sp_frac) if not math.isnan(s.sp_frac) else math.nan
            for s in sticking]

    if mpv:
        best_mpv = float(np.max(mpv))
        top2_mpv = float(np.mean(sorted(mpv, reverse=True)[:2]))
        rep1_mpv = float(mpv[0])
        last_mpv = float(mpv[-1])
        vl = max(0.0, (best_mpv - last_mpv) / max(best_mpv, 1e-6))
    else:
        best_mpv = top2_mpv = rep1_mpv = last_mpv = math.nan
        vl = math.nan

    return SessionFeatures(
        name=nm,
        lifter=lifter,
        load_lb=load,
        n_reps_prescribed=n_rx,
        n_reps_detected=len(reps),
        rep_mpv=mpv, rep_mcv=mcv, rep_pcv=pcv, rep_tpv=tpv,
        rep_sp_depth=sp_d, rep_sp_frac=sp_f,
        best_mpv=best_mpv,
        best_mcv=float(np.max(mcv)) if mcv else math.nan,
        best_pcv=float(np.max(pcv)) if pcv else math.nan,
        top2_mpv=top2_mpv,
        rep1_mpv=rep1_mpv,
        last_mpv=last_mpv,
        vl_frac=vl,
    )


# ────────────────────────────────────────────────────────────────────────
# Linear-regression helpers
# ────────────────────────────────────────────────────────────────────────
def _ols(x: np.ndarray, y: np.ndarray) -> Tuple[float, float, float]:
    """Least-squares slope, intercept, R². Returns (slope, intercept, R²)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 2 or np.std(x) == 0:
        return math.nan, math.nan, math.nan
    x_bar = x.mean()
    y_bar = y.mean()
    sxx = float(np.sum((x - x_bar) ** 2))
    sxy = float(np.sum((x - x_bar) * (y - y_bar)))
    syy = float(np.sum((y - y_bar) ** 2))
    slope = sxy / sxx
    intercept = y_bar - slope * x_bar
    if syy == 0:
        r2 = 1.0
    else:
        y_hat = intercept + slope * x
        ss_res = float(np.sum((y - y_hat) ** 2))
        r2 = 1.0 - ss_res / syy
    return slope, intercept, r2


def _extrapolate_1rm(slope: float, intercept: float, mvt: float) -> float:
    """Load at which fitted velocity equals MVT."""
    if math.isnan(slope) or slope >= 0:
        return math.nan
    return (intercept - mvt) / (-slope)


# ────────────────────────────────────────────────────────────────────────
# Estimators
# ────────────────────────────────────────────────────────────────────────
@dataclass
class Estimator:
    name: str
    one_rm_lb: float
    slope: float
    intercept: float
    r2: float
    mvt: float
    x_points: List[float]
    y_points: List[float]
    notes: str = ""
    valid: bool = True


def _fit_estimator(label: str, loads: List[int], y: List[float],
                   mvt: float, notes: str = "") -> Estimator:
    slope, intercept, r2 = _ols(np.array(loads), np.array(y))
    one_rm = _extrapolate_1rm(slope, intercept, mvt)
    valid = (not math.isnan(one_rm) and not math.isnan(r2)
             and slope < 0 and r2 >= R2_MIN and 100 < one_rm < 800)
    return Estimator(
        name=label, one_rm_lb=one_rm, slope=slope, intercept=intercept,
        r2=r2, mvt=mvt, x_points=[float(x) for x in loads],
        y_points=[float(v) for v in y], notes=notes, valid=valid,
    )


def _gb_pct_1rm(mpv: float) -> float:
    """González-Badillo 2011 MPV → %1RM for bench press (fractional)."""
    pct = GB_A * mpv ** 2 + GB_B * mpv + GB_C
    return max(0.0, min(1.2, pct / 100.0))


def _vl_to_rir(vl: float) -> float:
    if math.isnan(vl):
        return math.nan
    for thr, rir in VL_TO_RIR:
        if vl <= thr:
            return float(rir)
    return 0.0


def estimate_gb_population(heaviest: SessionFeatures) -> Estimator:
    """M4 — GB 2011 population equation applied to heaviest-set best MPV.

    Best MPV (not rep-1 MPV) because rep 1 often contains a setup/motor-
    learning discount; the maximal rep in the set is a better proxy for
    how fast the bar *can* move at that load for this lifter on this day.
    """
    if math.isnan(heaviest.best_mpv):
        return Estimator("GB-pop (best@heaviest)", math.nan, math.nan,
                         math.nan, math.nan, math.nan, [], [],
                         notes="no MPV available", valid=False)
    pct = _gb_pct_1rm(heaviest.best_mpv)
    one_rm = heaviest.load_lb / pct if pct > 0 else math.nan
    return Estimator(
        name="GB-pop (best@heaviest)",
        one_rm_lb=one_rm, slope=math.nan, intercept=math.nan, r2=math.nan,
        mvt=math.nan,
        x_points=[heaviest.load_lb], y_points=[heaviest.best_mpv],
        notes=f"heaviest={heaviest.load_lb}lb  best MPV={heaviest.best_mpv:.3f}  "
              f"→ {pct*100:.1f}% 1RM",
        valid=not math.isnan(one_rm) and 100 < one_rm < 800,
    )


def estimate_trimmed_lvp(loads: List[int], y: List[float], mvt: float,
                         label: str = "MPV-LVP (trimmed)") -> Estimator:
    """M6 — leave-one-out: try every 3-set subset and pick the one with
    the highest R² that also gives (a) a negative slope, (b) a slope
    magnitude in the bench-typical range [0.0015, 0.010] m/s per lb, and
    (c) an extrapolated 1RM that is physiologically plausible relative
    to the heaviest completed load (between 1.05× and 2.0× of L_max).
    Requires ≥4 input points.

    Leave-one-out with bounds is robust to a single sandbagged set:
    without the slope-magnitude check, the LOO would prefer the subset
    that looks "smoothest" even if that subset is actually the one that
    excludes the most-effortful (heaviest) rep, which would leave the
    remaining points collinear with a shallow slope and an absurd
    extrapolation."""
    if len(loads) < 4:
        return Estimator(label, math.nan, math.nan, math.nan, math.nan, mvt,
                         [], [], notes="need ≥4 sessions", valid=False)
    loads_arr = np.array(loads, dtype=float)
    y_arr = np.array(y, dtype=float)
    l_max = int(np.max(loads_arr))

    min_1rm = 1.05 * l_max       # can't be below heaviest completed
    max_1rm = 2.0 * l_max        # 2x is a generous upper bound
    min_slope_mag = 0.0015       # m/s/lb — below this is sandbagged
    max_slope_mag = 0.010

    best = None
    for drop_idx in range(len(loads_arr)):
        mask = np.ones(len(loads_arr), dtype=bool)
        mask[drop_idx] = False
        lt = loads_arr[mask]
        yt = y_arr[mask]
        s, i, r2 = _ols(lt, yt)
        if math.isnan(s) or s >= 0 or math.isnan(r2):
            continue
        slope_mag = -s
        if not (min_slope_mag <= slope_mag <= max_slope_mag):
            continue
        one_rm = _extrapolate_1rm(s, i, mvt)
        if math.isnan(one_rm) or not (min_1rm <= one_rm <= max_1rm):
            continue
        cand = (r2, drop_idx, s, i, one_rm, lt, yt)
        if best is None or cand[0] > best[0]:
            best = cand

    if best is None:
        return Estimator(label, math.nan, math.nan, math.nan, math.nan, mvt,
                         [], [], notes="no valid trimmed subset", valid=False)
    r2, drop_idx, s2, i2, one_rm, lt, yt = best
    dropped_load = int(loads_arr[drop_idx])
    return Estimator(
        name=label,
        one_rm_lb=one_rm, slope=s2, intercept=i2, r2=r2, mvt=mvt,
        x_points=[float(x) for x in lt],
        y_points=[float(v) for v in yt],
        notes=f"dropped {dropped_load}lb (leave-one-out best R²={r2:.2f})  "
              f"MVT={mvt} m/s",
        valid=(r2 >= R2_MIN),
    )


def estimate_velocity_loss(heaviest: SessionFeatures) -> Estimator:
    """M5 — within-set velocity-loss → RIR → %1RM from Baechle chart.
    reps_equivalent = reps_done + RIR  (estimated reps-to-failure)."""
    if math.isnan(heaviest.vl_frac) or heaviest.n_reps_detected < 2:
        return Estimator("VL-within-set", math.nan, math.nan, math.nan,
                         math.nan, math.nan, [], [],
                         notes="need ≥2 reps", valid=False)
    rir = _vl_to_rir(heaviest.vl_frac)
    reps_eq = heaviest.n_reps_detected + int(round(rir))
    # Clamp to chart
    reps_eq_clamped = max(1, min(12, reps_eq))
    pct = REPS_TO_PCT_1RM[reps_eq_clamped]
    one_rm = heaviest.load_lb / pct
    return Estimator(
        name="VL-within-set",
        one_rm_lb=one_rm, slope=math.nan, intercept=math.nan, r2=math.nan,
        mvt=math.nan,
        x_points=[heaviest.load_lb], y_points=[heaviest.vl_frac],
        notes=(f"VL={heaviest.vl_frac*100:.0f}%  →  ~{rir:.0f} RIR  "
               f"→  reps_eq={reps_eq}  →  {pct*100:.0f}% 1RM"),
        valid=not math.isnan(one_rm) and 100 < one_rm < 800,
    )


# ────────────────────────────────────────────────────────────────────────
# Bootstrap confidence interval
# ────────────────────────────────────────────────────────────────────────
def bootstrap_ci(sessions: List[SessionFeatures], mvt: float,
                 feature: str = "best_mpv",
                 use_trimmed: bool = False,
                 n_boot: int = 2000, seed: int = 17) -> Tuple[float, float]:
    """95% CI for 1RM by resampling within-set reps to produce synthetic
    (load, feature) pairs, then refitting LVP. Returns (lo, hi) in lb.

    When use_trimmed=True, each bootstrap sample is fit via the same
    leave-one-out trimmed estimator the consensus uses — keeps the CI
    consistent with the point estimate when the full LVP is ill-
    conditioned."""
    rng = np.random.default_rng(seed)
    loads = [s.load_lb for s in sessions]
    loads_arr = np.array(loads, dtype=float)
    rep_pools = [np.array(s.rep_mpv, dtype=float) for s in sessions]

    if feature == "best_mpv":
        pick = lambda pool: float(np.max(rng.choice(pool, size=len(pool), replace=True)))
    elif feature == "top2_mpv":
        def pick(pool):
            sample = rng.choice(pool, size=len(pool), replace=True)
            return float(np.mean(np.sort(sample)[-2:]))
    else:
        raise ValueError(feature)

    estimates = []
    for _ in range(n_boot):
        y = [pick(p) if len(p) else math.nan for p in rep_pools]
        if any(math.isnan(v) for v in y):
            continue
        if use_trimmed:
            est = estimate_trimmed_lvp(loads, y, mvt, label="boot")
            if est.valid:
                estimates.append(est.one_rm_lb)
            continue
        slope, intercept, _ = _ols(loads_arr, np.array(y))
        one_rm = _extrapolate_1rm(slope, intercept, mvt)
        if not math.isnan(one_rm) and 0 < one_rm < 1500:
            estimates.append(one_rm)
    if len(estimates) < 20:
        return math.nan, math.nan
    return float(np.percentile(estimates, 2.5)), float(np.percentile(estimates, 97.5))


# ────────────────────────────────────────────────────────────────────────
# Top-level: per-lifter 1RM estimation
# ────────────────────────────────────────────────────────────────────────
@dataclass
class LifterEstimate:
    lifter: str
    sessions: List[SessionFeatures]
    estimators: List[Estimator]
    consensus_one_rm_lb: float
    ci95: Tuple[float, float]
    method_used: str   # "LVP-consensus", "pop+VL", etc.
    notes: str = ""


def estimate_lifter_1rm(sessions: List[SessionFeatures]) -> LifterEstimate:
    """Run all estimators for one lifter's stack of sessions and produce
    a consensus 1RM + 95% bootstrap CI."""
    assert all(s.lifter == sessions[0].lifter for s in sessions)
    lifter = sessions[0].lifter
    loads = [s.load_lb for s in sessions]

    m1 = _fit_estimator("MPV-LVP (best-per-set)",
                        loads, [s.best_mpv for s in sessions], MVT_MPV,
                        notes=f"MVT={MVT_MPV} m/s")
    m2 = _fit_estimator("MCV-LVP (best-per-set)",
                        loads, [s.best_mcv for s in sessions], MVT_MCV,
                        notes=f"MVT={MVT_MCV} m/s")
    m3 = _fit_estimator("MPV-LVP (mean top-2)",
                        loads, [s.top2_mpv for s in sessions], MVT_MPV,
                        notes=f"MVT={MVT_MPV} m/s  (rep-1 setup noise reduced)")

    heaviest = max(sessions, key=lambda s: s.load_lb)
    m4 = estimate_gb_population(heaviest)
    m5 = estimate_velocity_loss(heaviest)
    m6 = estimate_trimmed_lvp(loads, [s.best_mpv for s in sessions], MVT_MPV,
                              label="MPV-LVP (trimmed)")

    estimators = [m1, m2, m3, m4, m5, m6]

    # Consensus: R²-weighted mean of valid LVP estimators. Include the
    # trimmed estimator only when it's valid AND the un-trimmed MPV fit
    # failed — otherwise trimming just nudges an already-good fit.
    lvp_full = [e for e in (m1, m2, m3) if e.valid]
    lvp_use = list(lvp_full)
    if not m1.valid and m6.valid:
        lvp_use.append(m6)
    if lvp_use:
        weights = np.array([e.r2 for e in lvp_use])
        values = np.array([e.one_rm_lb for e in lvp_use])
        consensus = float(np.sum(weights * values) / np.sum(weights))
        method_used = ("LVP-consensus+trimmed" if m6 in lvp_use
                       else "LVP-consensus")
    else:
        fallback = [e for e in (m4, m5) if e.valid]
        if fallback:
            consensus = float(np.mean([e.one_rm_lb for e in fallback]))
            method_used = "pop+VL-fallback"
        else:
            consensus = math.nan
            method_used = "none"

    # 95% CI: bootstrap in a way that matches which estimator the
    # consensus actually relied on. If the full LVP was ill-conditioned
    # and we fell back to trimmed, use the trimmed-LVP bootstrap too.
    ci = bootstrap_ci(sessions, MVT_MPV, feature="best_mpv",
                      use_trimmed=(not m1.valid and m6.valid))

    # If LVP was used but is ill-conditioned-leaning (R² borderline), note
    notes_parts = []
    if m1.valid and m1.r2 < 0.7:
        notes_parts.append(f"MPV-LVP R²={m1.r2:.2f} — moderate confidence")
    if not m1.valid:
        notes_parts.append("MPV-LVP ill-conditioned (likely submax efforts)")

    return LifterEstimate(
        lifter=lifter,
        sessions=sessions,
        estimators=estimators,
        consensus_one_rm_lb=consensus,
        ci95=ci,
        method_used=method_used,
        notes="; ".join(notes_parts),
    )


# ────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────
CLEAN_SESSIONS = [
    "D_135_10_session_20260416_134111",
    "D_155_8_session_20260416_133532",
    "D_175_5_session_20260416_133713",
    "D_185_3_session_20260416_133914",
    "M_135_10_session_20260416_131259",
    "M_155_8_session_20260416_131628",
    "M_175_5_session_20260416_132053",
    "M_185_3_session_20260416_132454",
]


def load_all_sessions(data_dir: str = "data_collection",
                      method: str = "B") -> Dict[str, List[SessionFeatures]]:
    """Load every session in CLEAN_SESSIONS, group by lifter."""
    by_lifter: Dict[str, List[SessionFeatures]] = {}
    for name in CLEAN_SESSIONS:
        csv = os.path.join(data_dir, name + ".csv")
        ann = os.path.join(data_dir, name + "_annotations.csv")
        feats = extract_session_features(csv, ann, method=method, name=name)
        by_lifter.setdefault(feats.lifter, []).append(feats)
    for lst in by_lifter.values():
        lst.sort(key=lambda s: s.load_lb)
    return by_lifter


def _print_estimator(e: Estimator, indent: str = "    "):
    r2_s = "—" if math.isnan(e.r2) else f"{e.r2:.3f}"
    one_s = "—" if math.isnan(e.one_rm_lb) else f"{e.one_rm_lb:6.1f} lb"
    slope_s = "—" if math.isnan(e.slope) else f"{e.slope:+.5f}"
    valid = "✓" if e.valid else "✗"
    print(f"{indent}{valid} {e.name:<28}  1RM={one_s}   R²={r2_s}   slope={slope_s}")
    if e.notes:
        print(f"{indent}   {e.notes}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", default="data_collection")
    p.add_argument("--method", default="B", choices=["A", "B", "C", "D"])
    p.add_argument("--lifter", choices=["D", "M", "all"], default="all")
    p.add_argument("--method-details", action="store_true")
    p.add_argument("--out", default=None, help="Optional JSON output")
    args = p.parse_args()

    by_lifter = load_all_sessions(args.dir, args.method)
    out = {"method": args.method, "lifters": {}}

    for lifter, sessions in sorted(by_lifter.items()):
        if args.lifter != "all" and args.lifter != lifter:
            continue
        est = estimate_lifter_1rm(sessions)
        print(f"\n=== Lifter {lifter} ===")
        print(f"Sessions ({len(sessions)}):")
        for s in sessions:
            sp_n = sum(1 for d in s.rep_sp_depth if d > 0)
            print(f"  {s.load_lb:>4}lb × {s.n_reps_detected}/{s.n_reps_prescribed}  "
                  f"best MPV={s.best_mpv:.3f}  rep1 MPV={s.rep1_mpv:.3f}  "
                  f"VL={s.vl_frac*100:4.1f}%  SP={sp_n}/{s.n_reps_detected}")
        print("Estimators:")
        for e in est.estimators:
            _print_estimator(e)
        consensus_s = ("—" if math.isnan(est.consensus_one_rm_lb)
                       else f"{est.consensus_one_rm_lb:.1f} lb")
        ci_s = ("—" if math.isnan(est.ci95[0])
                else f"[{est.ci95[0]:.0f} – {est.ci95[1]:.0f}] lb")
        print(f"Consensus 1RM: {consensus_s}   95% CI: {ci_s}   "
              f"({est.method_used})")
        if est.notes:
            print(f"  Notes: {est.notes}")

        out["lifters"][lifter] = {
            "consensus_one_rm_lb": est.consensus_one_rm_lb,
            "ci95": list(est.ci95),
            "method_used": est.method_used,
            "estimators": [asdict(e) for e in est.estimators],
            "sessions": [{
                "name": s.name, "load_lb": s.load_lb,
                "n_reps_prescribed": s.n_reps_prescribed,
                "n_reps_detected": s.n_reps_detected,
                "best_mpv": s.best_mpv, "best_mcv": s.best_mcv,
                "best_pcv": s.best_pcv, "top2_mpv": s.top2_mpv,
                "rep1_mpv": s.rep1_mpv, "last_mpv": s.last_mpv,
                "vl_frac": s.vl_frac,
                "rep_mpv": s.rep_mpv, "rep_mcv": s.rep_mcv,
                "rep_pcv": s.rep_pcv, "rep_sp_depth": s.rep_sp_depth,
            } for s in sessions],
            "notes": est.notes,
        }

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(out, f, indent=2, default=float)
        print(f"\nWrote → {args.out}")


if __name__ == "__main__":
    main()
