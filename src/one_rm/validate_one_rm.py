"""
1RM prediction validation harness.

Runs `src/one_rm/one_rm.py` for both lifters (D, M), compares the
consensus estimate (and each sub-estimator) against the known 1RM
ranges, and emits a JSON artefact at validation/one_rm_scores.json.

Expected ranges (provided by the user):
    D   305 – 345 lb
    M   250 – 300 lb

Validation criteria
-------------------
Per lifter:
    V1  consensus 1RM within ±10% of the target range midpoint
        (i.e. 295-355 for D, 247.5-302.5 for M — a ±10% tolerance
        bracket around the midpoint). A looser sanity threshold than
        the strict in-range check, because submaximal efforts can't
        pin the true 1RM tightly.
    V2  consensus 1RM within the stated range (strict)
    V3  95% bootstrap CI overlaps the stated range
    V4  at least one sub-estimator's point estimate lies in the stated
        range (hedge: even if consensus is off, the data contains a
        supporting signal)

Aggregate:
    A1  both lifters satisfy V1
    A2  both lifters satisfy at least one of V2 / V3 / V4

Exit code non-zero if A1 or A2 fails.

Usage:
    python3 src/one_rm/validate_one_rm.py
    python3 src/one_rm/validate_one_rm.py
        --out validation/one_rm_scores.json --method B
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(__file__))
from one_rm import (  # noqa: E402
    load_all_sessions, estimate_lifter_1rm, LifterEstimate,
)

# Expected 1RM ranges (lb) — source: user
EXPECTED = {
    "D": (305.0, 345.0),
    "M": (250.0, 300.0),
}
V1_TOL = 0.10   # ±10% around the midpoint counts as "close enough"


def _midpoint(rng: Tuple[float, float]) -> float:
    return 0.5 * (rng[0] + rng[1])


def _within(value: float, rng: Tuple[float, float]) -> bool:
    if math.isnan(value):
        return False
    return rng[0] <= value <= rng[1]


def _overlap(ci: Tuple[float, float], rng: Tuple[float, float]) -> bool:
    if math.isnan(ci[0]) or math.isnan(ci[1]):
        return False
    return not (ci[1] < rng[0] or ci[0] > rng[1])


def _near_mid(value: float, rng: Tuple[float, float], tol: float = V1_TOL) -> bool:
    mid = _midpoint(rng)
    return abs(value - mid) <= tol * mid if not math.isnan(value) else False


def _check_lifter(lifter: str, est: LifterEstimate) -> Dict:
    rng = EXPECTED[lifter]
    cons = est.consensus_one_rm_lb
    ci = est.ci95

    v1 = _near_mid(cons, rng)
    v2 = _within(cons, rng)
    v3 = _overlap(ci, rng)
    v4 = any(_within(e.one_rm_lb, rng) for e in est.estimators if e.valid)
    best_sub = None
    best_dist = None
    for e in est.estimators:
        if not e.valid:
            continue
        d = abs(e.one_rm_lb - _midpoint(rng))
        if best_dist is None or d < best_dist:
            best_dist = d
            best_sub = e
    return {
        "lifter": lifter,
        "expected_lb": list(rng),
        "consensus_one_rm_lb": cons,
        "ci95": list(ci),
        "method_used": est.method_used,
        "v1_within_10pct": v1,
        "v2_in_range": v2,
        "v3_ci_overlaps_range": v3,
        "v4_any_sub_in_range": v4,
        "passes_lifter": v1 and (v2 or v3 or v4),
        "closest_sub_estimator": (
            None if best_sub is None
            else {"name": best_sub.name,
                  "one_rm_lb": best_sub.one_rm_lb,
                  "r2": best_sub.r2}
        ),
        "sub_estimators": [
            {"name": e.name, "one_rm_lb": e.one_rm_lb, "r2": e.r2,
             "valid": e.valid, "notes": e.notes}
            for e in est.estimators
        ],
        "notes": est.notes,
    }


def run(data_dir: str, method: str) -> Dict:
    by_lifter = load_all_sessions(data_dir, method)
    per = []
    for lifter in sorted(by_lifter):
        est = estimate_lifter_1rm(by_lifter[lifter])
        per.append(_check_lifter(lifter, est))

    a1 = all(p["v1_within_10pct"] for p in per)
    a2 = all(p["v2_in_range"] or p["v3_ci_overlaps_range"] or p["v4_any_sub_in_range"]
             for p in per)
    return {
        "method": method,
        "per_lifter": per,
        "aggregate": {
            "a1_all_near_mid": a1,
            "a2_all_range_supported": a2,
            "overall_pass": bool(a1 and a2),
        },
    }


def _fmt(v):
    return "—" if (v is None or (isinstance(v, float) and math.isnan(v))) else f"{v:.1f}"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", default="data_collection")
    p.add_argument("--method", default="B", choices=["A", "B", "C", "D"])
    p.add_argument("--out", default="validation/one_rm_scores.json")
    args = p.parse_args()

    report = run(args.dir, args.method)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, default=float)

    print(f"Method: {report['method']}    → {args.out}")
    print()
    print(f"{'lifter':<6} {'expected':>14} {'consensus':>10} "
          f"{'95% CI':>16} V1 V2 V3 V4  verdict")
    print("-" * 86)
    for p_ in report["per_lifter"]:
        rng = p_["expected_lb"]
        ci = p_["ci95"]
        ys = lambda b: "✓" if b else "✗"
        ci_s = (f"[{_fmt(ci[0])} – {_fmt(ci[1])}]" if not math.isnan(ci[0])
                else "—")
        print(f"{p_['lifter']:<6} "
              f"[{rng[0]:.0f}–{rng[1]:.0f}]".rjust(14, " ") + f" "
              f"{_fmt(p_['consensus_one_rm_lb']):>10} "
              f"{ci_s:>16}  {ys(p_['v1_within_10pct'])}  "
              f"{ys(p_['v2_in_range'])}  {ys(p_['v3_ci_overlaps_range'])}  "
              f"{ys(p_['v4_any_sub_in_range'])}   "
              f"{'PASS' if p_['passes_lifter'] else 'FAIL'}")
        if p_["closest_sub_estimator"] is not None:
            cs = p_["closest_sub_estimator"]
            r2_s = ("—" if cs["r2"] is None or math.isnan(cs["r2"])
                    else f"{cs['r2']:.2f}")
            print(f"         closest sub: {cs['name']}  "
                  f"= {_fmt(cs['one_rm_lb'])} lb  (R²={r2_s})")
        if p_["notes"]:
            print(f"         notes: {p_['notes']}")

    agg = report["aggregate"]
    print("-" * 86)
    print(f"A1 (both near mid ±{V1_TOL*100:.0f}%): "
          f"{'PASS' if agg['a1_all_near_mid'] else 'FAIL'}")
    print(f"A2 (both range-supported):      "
          f"{'PASS' if agg['a2_all_range_supported'] else 'FAIL'}")
    print()
    print(f"OVERALL: {'PASS' if agg['overall_pass'] else 'FAIL'}")
    sys.exit(0 if agg["overall_pass"] else 1)


if __name__ == "__main__":
    main()
