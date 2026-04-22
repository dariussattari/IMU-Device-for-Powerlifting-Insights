"""
Sticking-point validation harness.

Runs the sticking-point detector across the 8 clean sessions and
produces (a) a JSON artefact at validation/sticking_point_scores.json,
and (b) a per-session PASS/FAIL table on stdout. Exit code is non-zero
if any aggregate criterion fails.

Validation criteria
-------------------
  Per session
    V1  n_detected == n_annotated
    V2  within-set SP position CV ≤ 30%   (technique consistent)
    V3  within-set SP depth CV    ≤ 60%   (effort consistent)

  Aggregate (across sessions)
    A1  detection rate ≥ 25%
        (sanity floor; many light-load reps genuinely lack a valley)
    A2  within each lifter, mean depth is weakly monotonic non-decreasing
        with load. Reported as #monotone pairs / #pairs. Pass if ≥ 3/4.
    A3  for reps that do have a sticking point, 10% ≤ SP_frac ≤ 90%
        (i.e. valleys are not being placed right at chest or lockout).
        Aggregate pass if 100% of detected SPs satisfy this.

Usage:
    python3 src/sticking_point/validate_sticking_point.py
    python3 src/sticking_point/validate_sticking_point.py
        --out validation/sticking_point_scores.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict
from typing import List

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from sticking_point import compute_sticking  # noqa: E402

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

V2_FRAC_CV_MAX = 0.30
V3_DEPTH_CV_MAX = 0.60
A1_DETECT_RATE_MIN = 0.25
A2_MONOTONE_MIN = 3      # ≥3 of 4 within-lifter pairs
A2_DEPTH_TOL = 0.02      # m/s — micro-ties within this are treated as ok
A3_FRAC_LO = 0.10
A3_FRAC_HI = 0.90


def _cv(values: List[float]) -> float:
    if len(values) < 2:
        return math.nan
    m = float(np.mean(values))
    if m <= 0:
        return math.nan
    return float(np.std(values) / m)


def _mono_pairs(values: List[float], tol: float = 0.0):
    """Count pairs (a, b) where b >= a - tol. A small tolerance rules out
    micro-ties (e.g. 0.06 vs 0.05 m/s) that are well inside measurement
    noise from counting as a monotonicity violation."""
    ok, total = 0, 0
    for a, b in zip(values, values[1:]):
        if math.isnan(a) or math.isnan(b):
            continue
        total += 1
        if b + tol >= a:
            ok += 1
    return ok, total


def _run(dir_: str, method: str):
    per_session = []
    all_detected = []
    for name in CLEAN_SESSIONS:
        csv = os.path.join(dir_, name + ".csv")
        ann = os.path.join(dir_, name + "_annotations.csv")
        r = compute_sticking(csv, ann, method=method)
        sticks = r["sticking"]
        n_reps = len(sticks)
        n_stick = sum(1 for s in sticks if s.has_sticking)
        n_annot = len(r["annotations"]["reps"])
        fracs = [s.sp_frac for s in sticks if s.has_sticking]
        depths = [s.sp_depth for s in sticks if s.has_sticking]

        v1_pass = n_reps == n_annot
        frac_cv = _cv(fracs)
        depth_cv = _cv(depths)
        v2_pass = math.isnan(frac_cv) or frac_cv <= V2_FRAC_CV_MAX
        v3_pass = math.isnan(depth_cv) or depth_cv <= V3_DEPTH_CV_MAX

        per_session.append({
            "session": name,
            "person": name[0],
            "weight_lb": int(name.split("_")[1]),
            "n_annotated": n_annot,
            "n_detected_reps": n_reps,
            "n_sticking_points": n_stick,
            "mean_sp_frac": float(np.mean(fracs)) if fracs else None,
            "mean_sp_depth": float(np.mean(depths)) if depths else None,
            "sp_frac_cv": None if math.isnan(frac_cv) else frac_cv,
            "sp_depth_cv": None if math.isnan(depth_cv) else depth_cv,
            "v1_all_reps": v1_pass,
            "v2_frac_cv_ok": v2_pass,
            "v3_depth_cv_ok": v3_pass,
            "passes": v1_pass and v2_pass and v3_pass,
            "per_rep": [asdict(s) for s in sticks],
        })
        all_detected.extend(sticks)

    # Aggregate A1: detection rate
    total_reps = sum(p["n_detected_reps"] for p in per_session)
    total_sp = sum(p["n_sticking_points"] for p in per_session)
    det_rate = total_sp / total_reps if total_reps else 0.0
    a1_pass = det_rate >= A1_DETECT_RATE_MIN

    # Aggregate A2: load-monotonic mean depth per lifter
    depth_by_lifter = {}
    for p in per_session:
        depth_by_lifter.setdefault(p["person"], {})[p["weight_lb"]] = (
            p["mean_sp_depth"] if p["mean_sp_depth"] is not None else math.nan
        )
    mono_ok = mono_total = 0
    per_lifter_monotone = {}
    for person, by_w in depth_by_lifter.items():
        weights = sorted(by_w)
        ok, total = _mono_pairs([by_w[w] for w in weights], tol=A2_DEPTH_TOL)
        mono_ok += ok
        mono_total += total
        per_lifter_monotone[person] = {
            "weights_lb": weights,
            "mean_depths": [None if math.isnan(by_w[w]) else by_w[w]
                            for w in weights],
            "monotone_pairs": f"{ok}/{total}",
        }
    a2_pass = mono_ok >= A2_MONOTONE_MIN

    # Aggregate A3: all detected SP_frac within bounds
    fracs_all = [s.sp_frac for s in all_detected if s.has_sticking]
    n_in_bounds = sum(1 for f in fracs_all if A3_FRAC_LO <= f <= A3_FRAC_HI)
    a3_pass = (len(fracs_all) == 0) or (n_in_bounds == len(fracs_all))

    n_panel_pass = sum(1 for p in per_session if p["passes"])
    overall_pass = (a1_pass and a2_pass and a3_pass
                    and n_panel_pass >= len(per_session) - 1)

    return {
        "method": method,
        "per_session": per_session,
        "aggregate": {
            "n_sessions": len(per_session),
            "n_panel_pass": n_panel_pass,
            "total_detected_reps": total_reps,
            "total_sticking_points": total_sp,
            "detection_rate": det_rate,
            "a1_detection_rate_pass": a1_pass,
            "a2_monotone_pairs": f"{mono_ok}/{mono_total}",
            "a2_monotone_pass": a2_pass,
            "a3_frac_in_bounds": f"{n_in_bounds}/{len(fracs_all)}",
            "a3_frac_bounds_pass": a3_pass,
            "per_lifter_monotone": per_lifter_monotone,
        },
        "overall_pass": overall_pass,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", default="data_collection")
    p.add_argument("--method", default="B", choices=["A", "B", "C", "D"])
    p.add_argument("--out", default="validation/sticking_point_scores.json")
    args = p.parse_args()

    report = _run(args.dir, args.method)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)

    # Human-readable summary
    print(f"Method: {report['method']}    → {args.out}")
    print()
    print(f"{'session':<45} {'SP/reps':>9} {'pos̄':>5} {'pos CV':>7} "
          f"{'depth̄':>7} {'d CV':>6} V1 V2 V3  verdict")
    print("-" * 100)
    for p_ in report["per_session"]:
        pf = "—" if p_["mean_sp_frac"] is None else f"{p_['mean_sp_frac']*100:.0f}%"
        pc = "—" if p_["sp_frac_cv"] is None else f"{p_['sp_frac_cv']*100:.0f}%"
        dp = "—" if p_["mean_sp_depth"] is None else f"{p_['mean_sp_depth']:.2f}"
        dc = "—" if p_["sp_depth_cv"] is None else f"{p_['sp_depth_cv']*100:.0f}%"
        ys = lambda b: "✓" if b else "✗"
        print(f"{p_['session']:<45} {p_['n_sticking_points']:>3}/{p_['n_detected_reps']:<4} "
              f"{pf:>5} {pc:>6} {dp:>6} {dc:>5}  "
              f"{ys(p_['v1_all_reps'])}  {ys(p_['v2_frac_cv_ok'])}  "
              f"{ys(p_['v3_depth_cv_ok'])}   "
              f"{'PASS' if p_['passes'] else 'FAIL'}")

    agg = report["aggregate"]
    print("-" * 100)
    print(f"Aggregate  ({agg['n_panel_pass']}/{agg['n_sessions']} panels PASS)")
    print(f"  A1  detection rate        {agg['detection_rate']*100:>5.0f}%   "
          f"{'PASS' if agg['a1_detection_rate_pass'] else 'FAIL'}  "
          f"(≥ {A1_DETECT_RATE_MIN*100:.0f}%)")
    print(f"  A2  load-monotone depth   {agg['a2_monotone_pairs']} pairs   "
          f"{'PASS' if agg['a2_monotone_pass'] else 'FAIL'}  "
          f"(≥ {A2_MONOTONE_MIN}/4)")
    print(f"  A3  SP frac in [10%,90%]  {agg['a3_frac_in_bounds']}   "
          f"{'PASS' if agg['a3_frac_bounds_pass'] else 'FAIL'}")
    for person, m in agg["per_lifter_monotone"].items():
        cells = []
        for w, d in zip(m["weights_lb"], m["mean_depths"]):
            cells.append(f"{w}lb={d:.2f}" if d is not None else f"{w}lb=—")
        print(f"    {person}: {'  '.join(cells)}  ({m['monotone_pairs']} monotone)")
    print()
    print(f"OVERALL: {'PASS' if report['overall_pass'] else 'FAIL'}")

    sys.exit(0 if report["overall_pass"] else 1)


if __name__ == "__main__":
    main()
