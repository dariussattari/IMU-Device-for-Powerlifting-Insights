"""
Compare velocity-integration methods across the 8 clean sessions and score
each on physically-grounded error proxies.

Since we don't have a motion-capture ground truth for bar velocity, we
validate by four proxies any correct velocity estimate must satisfy:

    1. endpoint residual — |vy(chest)| and |vy(top)| should be ≈ 0 m/s
       because the bar is momentarily at rest at every turnaround
    2. ROM symmetry    — |∫vy dt| concentric  ≈  |∫vy dt| eccentric
                         (same physical bar travel, opposite direction)
    3. ROM consistency  — CV(ROM) across reps of the same set (same
                         lifter, same exercise → nearly identical travel
                         per rep)
    4. load-velocity monotonicity — within each lifter, mean PCV (and
                         mean MCV) should decrease with load
                         135 → 155 → 175 → 185 lb

Lower = better for (1)-(3). (4) is a boolean/score.

Usage:
    python3 src/velocity/compare_methods.py
    python3 src/velocity/compare_methods.py --out validation/method_scores.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from velocity_metrics import compute_metrics  # noqa: E402

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


def session_scores(result) -> Dict[str, float]:
    t = result["t"]
    vy = result["vy"]
    reps = result["reps"]
    boundaries = result["boundaries"]

    # (1) endpoint residual
    endpoint_resid = []
    for ci, li in boundaries:
        endpoint_resid.append(abs(vy[ci]))
        endpoint_resid.append(abs(vy[li]))
    endpoint_resid_mean = float(np.mean(endpoint_resid)) if endpoint_resid else 0.0

    # (2) ROM symmetry — skip rep 1 because its eccentric covers the
    # unrack path, not a true bar-to-chest descent.
    rom_sym = []
    for r in reps[1:]:
        if r.erom_m > 0 and r.rom_m > 0:
            rom_sym.append(abs(r.rom_m - r.erom_m) / r.rom_m)
    rom_sym_mean = float(np.mean(rom_sym)) if rom_sym else float("nan")

    # (3) ROM consistency — CV across reps
    roms = [r.rom_m for r in reps if r.rom_m > 0]
    rom_cv = float(np.std(roms) / np.mean(roms)) if roms else float("nan")

    # First-rep metrics for load-velocity analysis (fresh, unfatigued)
    first = reps[0] if reps else None

    # (4b) Within-set velocity-loss monotonicity — a robust biomechanical
    # sanity check. In a bench set taken near rep-max, MCV should fall
    # (roughly) monotonically. We score the fraction of adjacent rep
    # pairs where MCV[i+1] ≤ MCV[i].
    pct_decreasing = float("nan")
    if len(reps) >= 2:
        pairs = [(reps[i].mcv, reps[i + 1].mcv)
                 for i in range(len(reps) - 1)]
        pct_decreasing = float(
            np.mean([1.0 if b <= a + 1e-6 else 0.0 for a, b in pairs])
        )

    # First → last MCV drop (should be positive in a taxing set)
    v_loss = (reps[0].mcv - reps[-1].mcv) if len(reps) >= 2 else float("nan")

    return {
        "endpoint_resid_ms": endpoint_resid_mean,   # m/s
        "rom_symmetry_frac": rom_sym_mean,          # fraction |ΔROM|/ROM
        "rom_cv": rom_cv,                           # unitless
        "n_reps": len(reps),
        "first_mcv": float(first.mcv) if first else float("nan"),
        "first_pcv": float(first.pcv) if first else float("nan"),
        "first_mpv": float(first.mpv) if first else float("nan"),
        "mean_mcv": float(np.mean([r.mcv for r in reps])),
        "mean_pcv": float(np.mean([r.pcv for r in reps])),
        "mean_mpv": float(np.mean([r.mpv for r in reps])),
        "mean_rom": float(np.mean([r.rom_m for r in reps])),
        "pct_mcv_decreasing": pct_decreasing,
        "mcv_velocity_loss": v_loss,
    }


def load_velocity_monotonicity(per_session: Dict[str, Dict[str, float]]):
    """Count lifter×metric pairs where FIRST-REP velocity is monotone
    decreasing across 135 → 155 → 175 → 185 lb. First-rep isolates the
    load effect from the fatigue effect of a long set to failure."""
    loads = [135, 155, 175, 185]
    score = {"mcv_pass": 0, "pcv_pass": 0, "mpv_pass": 0, "total": 0}
    for lifter in ["D", "M"]:
        seq_mcv, seq_pcv, seq_mpv = [], [], []
        for load in loads:
            key = next((k for k in per_session if k.startswith(f"{lifter}_{load}_")), None)
            if key is None:
                continue
            s = per_session[key]
            seq_mcv.append(s["first_mcv"])
            seq_pcv.append(s["first_pcv"])
            seq_mpv.append(s["first_mpv"])
        if len(seq_mcv) == len(loads):
            score["total"] += 1
            if all(seq_mcv[i] >= seq_mcv[i + 1] for i in range(len(seq_mcv) - 1)):
                score["mcv_pass"] += 1
            if all(seq_pcv[i] >= seq_pcv[i + 1] for i in range(len(seq_pcv) - 1)):
                score["pcv_pass"] += 1
            if all(seq_mpv[i] >= seq_mpv[i + 1] for i in range(len(seq_mpv) - 1)):
                score["mpv_pass"] += 1
    return score


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dir", default="data_collection")
    p.add_argument("--out", default=None, help="Optional JSON output path")
    args = p.parse_args()

    # Test grid:
    #   {A,B,C,D} × {detector-based boundaries,    annotation+snap,    raw annotation}
    methods = ["A", "B", "C", "D"]
    runs = []
    for m in methods:
        runs.append((m, "det"))     # detector boundaries (recommended)
        runs.append((m, "snap"))    # annotation boundaries + snap-to-zc
        runs.append((m, "raw"))     # raw annotation boundaries

    report: Dict[str, Dict] = {}
    for method, mode in runs:
        label = f"{method}_{mode}"
        per_session: Dict[str, Dict[str, float]] = {}
        for name in CLEAN_SESSIONS:
            csv = os.path.join(args.dir, name + ".csv")
            ann = os.path.join(args.dir, name + "_annotations.csv")
            if mode == "det":
                res = compute_metrics(csv, ann, method=method, use_detector=True)
            elif mode == "snap":
                res = compute_metrics(csv, ann, method=method,
                                      use_detector=False, snap=True)
            else:
                res = compute_metrics(csv, ann, method=method,
                                      use_detector=False, snap=False)
            per_session[name] = session_scores(res)
        lv = load_velocity_monotonicity(per_session)

        # Aggregate scores across sessions
        ep = np.mean([v["endpoint_resid_ms"] for v in per_session.values()])
        sym = np.nanmean([v["rom_symmetry_frac"] for v in per_session.values()])
        cv = np.nanmean([v["rom_cv"] for v in per_session.values()])
        pct_dec = np.nanmean(
            [v["pct_mcv_decreasing"] for v in per_session.values()])
        report[label] = {
            "endpoint_resid_ms": float(ep),
            "rom_symmetry_frac": float(sym),
            "rom_cv": float(cv),
            "pct_mcv_decreasing": float(pct_dec),
            "load_velocity": lv,
            "per_session": per_session,
        }

    # Print summary table
    print(f"{'method':<10} {'endpoint':>10} {'rom_sym':>9} {'rom_cv':>8} "
          f"{'mcv↓':>6}  {'loadv':>8}")
    print("-" * 70)
    for label, r in report.items():
        lv = r["load_velocity"]
        lv_str = f"{lv['mcv_pass']}/{lv['pcv_pass']}/{lv['mpv_pass']}/{lv['total']}"
        print(f"{label:<10} {r['endpoint_resid_ms']:>10.4f} "
              f"{r['rom_symmetry_frac']:>9.3f} {r['rom_cv']:>8.3f} "
              f"{r['pct_mcv_decreasing']:>6.2f}  {lv_str:>8}")

    # Pick the best: low endpoint residual, low symmetry error, low CV,
    # high within-set MCV-decreasing fraction. We drop the load-velocity
    # monotonicity from the composite because these sets are taken to
    # rep-max (lifter paces differently at different loads), not true
    # 1RM trials — so that proxy is noisy here.
    def composite(r):
        return (r["endpoint_resid_ms"]
                + r["rom_symmetry_frac"]
                + r["rom_cv"]
                - 0.5 * r["pct_mcv_decreasing"])

    best = min(report.keys(), key=lambda k: composite(report[k]))
    print()
    print(f"Best composite: {best}   (lower = better endpoint/symmetry/CV, "
          f"higher load-velocity pass count)")

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2)
        print(f"Wrote → {args.out}")


if __name__ == "__main__":
    main()
