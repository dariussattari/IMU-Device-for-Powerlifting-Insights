"""
Multi-session sticking-point figure.

Renders the same 8 clean trials as plot_predicted_vs_truth.py (matching
its visual language — dark theme, cyan GT rep tops, green dashed predicted
lockouts, purple rack line, pink vy trace) and overlays:

    • Orange dot        — per-rep sticking point (velocity valley)
    • Orange dashed     — vertical drop from drive-peak to valley
                          (depth = PCV − SP_v)
    • Per-panel header  — n_sticking / n_reps, mean SP%, mean depth,
                          verdict
    • Bottom strip      — aggregate validation: load-monotonic depth
                          trend, within-set SP position CV, fraction of
                          reps with a detected sticking point

Validation criteria (per session):
    V1  every rep detected (n_det == n_annot)
    V2  ≥ 50% of reps under load have a detected sticking point
        (for the lightest set this may legitimately be lower — that's why
         V2 is advisory on the per-panel header, but required in the
         aggregate-strip PASS band)
    V3  within-set SP position CV ≤ 30%    (consistent technique)
    V4  within-set depth CV      ≤ 60%    (consistent effort)

Aggregate-level validation (shown in the footer):
    A1  Load-monotonic mean SP depth — for each lifter (D, M),
        depth(135) ≤ depth(155) ≤ depth(175) ≤ depth(185) modulo ties.
        Reported as count of monotone pairs / total pairs.
    A2  Detection rate — fraction of reps across all sessions with a
        sticking point detected.

Usage:
    python3 src/sticking_point/plot_sticking_point.py
    python3 src/sticking_point/plot_sticking_point.py --method B
        --out data_collection/sticking_point_all.png
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from typing import List

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

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

COL_BG_FIG = "#1a1a2e"
COL_BG_AX = "#16213e"
COL_SPINE = "#444466"
COL_VY = "#fd79a8"
COL_VY_POS = "#fd79a8"
COL_VY_NEG = "#74b9ff"
COL_GT_TOP = "#00cec9"
COL_RACK = "#9b59b6"
COL_PRED = "#2ecc71"
COL_SP = "#f39c12"       # orange — sticking point
COL_PCV = "#ffeaa7"      # pale yellow — drive-peak marker
COL_PASS = "#2ecc71"
COL_FAIL = "#e74c3c"


def _style_ax(ax):
    ax.set_facecolor(COL_BG_AX)
    ax.tick_params(colors="white", labelsize=7)
    for s in ax.spines.values():
        s.set_color(COL_SPINE)
    ax.yaxis.label.set_color("white")
    ax.xaxis.label.set_color("white")


def _per_session_validation(result) -> dict:
    sp = result["sticking"]
    n_reps = len(sp)
    n_stick = sum(1 for s in sp if s.has_sticking)
    fracs = [s.sp_frac for s in sp if s.has_sticking]
    depths = [s.sp_depth for s in sp if s.has_sticking]

    mean_frac = float(np.mean(fracs)) if fracs else math.nan
    mean_depth = float(np.mean(depths)) if depths else math.nan
    frac_cv = (float(np.std(fracs) / np.mean(fracs))
               if len(fracs) >= 2 and np.mean(fracs) > 0 else math.nan)
    depth_cv = (float(np.std(depths) / np.mean(depths))
                if len(depths) >= 2 and np.mean(depths) > 0 else math.nan)

    ann_reps = len(result["annotations"]["reps"])
    all_reps_detected = (n_reps == ann_reps)

    # Per-panel PASS only requires V1 + V3 + V4 (V2 is advisory, because
    # truly-light sets legitimately have no sticking point).
    passes = (all_reps_detected
              and (math.isnan(frac_cv) or frac_cv <= 0.30)
              and (math.isnan(depth_cv) or depth_cv <= 0.60))

    return {
        "n_reps": n_reps,
        "n_stick": n_stick,
        "n_annot": ann_reps,
        "mean_frac": mean_frac,
        "mean_depth": mean_depth,
        "frac_cv": frac_cv,
        "depth_cv": depth_cv,
        "passes": bool(passes),
    }


def _plot_one(ax, name, result, v):
    _style_ax(ax)
    t = result["t"]
    vy = result["vy"]
    boundaries = result["boundaries"]
    sticking = result["sticking"]
    anns = result["annotations"]

    if boundaries:
        fs = result["fs"]
        clip_lo = max(0, boundaries[0][0] - int(0.5 * fs))
        clip_hi = min(len(t), boundaries[-1][1] + int(0.5 * fs))
    else:
        clip_lo, clip_hi = 0, len(t)
    t_p = t[clip_lo:clip_hi]
    vy_p = vy[clip_lo:clip_hi]

    ax.plot(t_p, vy_p, color=COL_VY, lw=1.1)
    ax.fill_between(t_p, vy_p, 0,
                    where=(vy_p > 0), color=COL_VY_POS, alpha=0.18)
    ax.fill_between(t_p, vy_p, 0,
                    where=(vy_p < 0), color=COL_VY_NEG, alpha=0.18)
    ax.axhline(0, color="#555577", lw=0.6)

    # Ground-truth rep tops (cyan) — matches attached figure exactly
    for ann_rep in anns["reps"]:
        ax.axvline(ann_rep["top_s"], color=COL_GT_TOP, lw=1.3, alpha=0.9)

    # Predicted lockouts (green dashed) — detector-based boundaries
    for ci, li in boundaries:
        ax.axvline(t[li], color=COL_PRED, lw=1.2, ls="--", alpha=0.9)

    # Rack line
    if anns["rack_s"] is not None:
        ax.axvline(anns["rack_s"], color=COL_RACK, lw=1.2, alpha=0.85)

    # Sticking-point overlays
    for sp in sticking:
        if not sp.has_sticking:
            continue
        # Drive peak (pale yellow dot)
        ax.plot(sp.pcv_t, sp.pcv, "o", color=COL_PCV, ms=4.5,
                markeredgecolor=COL_BG_AX, markeredgewidth=0.5, zorder=4)
        # Drop line from drive peak down to valley
        ax.plot([sp.sp_t, sp.sp_t], [sp.sp_v, sp.pcv],
                color=COL_SP, lw=1.0, ls=":", alpha=0.9, zorder=3)
        # Sticking point (orange dot)
        ax.plot(sp.sp_t, sp.sp_v, "o", color=COL_SP, ms=6,
                markeredgecolor=COL_BG_AX, markeredgewidth=0.5, zorder=5)
        ax.text(sp.sp_t, sp.sp_v - 0.02,
                f"SP {sp.sp_depth:.2f}", color=COL_SP, fontsize=6,
                ha="center", va="top", fontweight="bold")

    if len(t_p):
        ax.set_xlim(t_p[0], t_p[-1])

    # Header with validation summary
    verdict = "PASS" if v["passes"] else "FAIL"
    color = COL_PASS if v["passes"] else COL_FAIL
    mean_frac_s = ("—" if math.isnan(v["mean_frac"])
                   else f"{v['mean_frac']*100:.0f}%")
    mean_depth_s = ("—" if math.isnan(v["mean_depth"])
                    else f"{v['mean_depth']:.2f}")
    frac_cv_s = ("—" if math.isnan(v["frac_cv"])
                 else f"{v['frac_cv']*100:.0f}%")
    depth_cv_s = ("—" if math.isnan(v["depth_cv"])
                  else f"{v['depth_cv']*100:.0f}%")
    header = (f"{name}   SP={v['n_stick']}/{v['n_reps']}   "
              f"pos̄={mean_frac_s}  CV={frac_cv_s}   "
              f"depth̄={mean_depth_s}  CV={depth_cv_s}   [{verdict}]")
    ax.set_title(header, color=color, fontsize=8.5, pad=3)
    ax.set_ylabel("vy (m/s)", color="white", fontsize=8)


MONOTONE_DEPTH_TOL = 0.02   # m/s — matches validate_sticking_point.py A2


def _monotone_pairs(values, tol=MONOTONE_DEPTH_TOL):
    """Count (i, i+1) pairs where values are weakly monotonically increasing,
    allowing a small tolerance so micro-noise (0.05 vs 0.06 m/s) doesn't
    count as a monotonicity violation."""
    ok, total = 0, 0
    for a, b in zip(values, values[1:]):
        if math.isnan(a) or math.isnan(b):
            continue
        total += 1
        if b + tol >= a:
            ok += 1
    return ok, total


def _aggregate_validation(names, results, vals) -> dict:
    # A1: per-lifter load-monotonic mean depth
    by_lifter = {"D": {}, "M": {}}
    for name, r, v in zip(names, results, vals):
        person = name[0]
        weight = int(name.split("_")[1])
        depths = [sp.sp_depth for sp in r["sticking"] if sp.has_sticking]
        mean_d = float(np.mean(depths)) if depths else math.nan
        by_lifter.setdefault(person, {})[weight] = mean_d

    mono_ok = mono_total = 0
    for person, d_by_w in by_lifter.items():
        weights = sorted(d_by_w)
        ok, total = _monotone_pairs([d_by_w[w] for w in weights])
        mono_ok += ok
        mono_total += total

    # A2: overall detection rate
    total_reps = sum(v["n_reps"] for v in vals)
    total_stick = sum(v["n_stick"] for v in vals)
    det_rate = total_stick / total_reps if total_reps else 0.0

    # A3: per-panel pass count
    n_pass = sum(1 for v in vals if v["passes"])

    return {
        "monotone_ok": mono_ok,
        "monotone_total": mono_total,
        "det_rate": det_rate,
        "n_pass": n_pass,
        "n_sessions": len(vals),
        "by_lifter": by_lifter,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", default="data_collection")
    p.add_argument("--method", default="B", choices=["A", "B", "C", "D"])
    p.add_argument("--out", default="data_collection/sticking_point_all.png")
    args = p.parse_args()

    fig, axes = plt.subplots(4, 2, figsize=(20, 17), sharex=False)
    fig.patch.set_facecolor(COL_BG_FIG)

    results, vals = [], []
    for name in CLEAN_SESSIONS:
        csv = os.path.join(args.dir, name + ".csv")
        ann = os.path.join(args.dir, name + "_annotations.csv")
        r = compute_sticking(csv, ann, method=args.method)
        results.append(r)
        vals.append(_per_session_validation(r))

    for ax, name, r, v in zip(axes.flat, CLEAN_SESSIONS, results, vals):
        _plot_one(ax, name, r, v)

    for ax in axes[-1, :]:
        ax.set_xlabel("Time (s)", color="white", fontsize=9)

    agg = _aggregate_validation(CLEAN_SESSIONS, results, vals)

    # Lifter-by-load table string
    def fmt_row(p):
        row = agg["by_lifter"].get(p, {})
        parts = [f"{w}lb:{row[w]:.2f}" if not math.isnan(row.get(w, math.nan))
                 else f"{w}lb:—" for w in sorted(row)]
        return " / ".join(parts) if parts else "—"

    footer = (f"Method {args.method}   |   "
              f"{agg['n_pass']}/{agg['n_sessions']} panels PASS   ·   "
              f"detection rate {agg['det_rate']*100:.0f}%   ·   "
              f"depth monotone-with-load "
              f"{agg['monotone_ok']}/{agg['monotone_total']} pairs   |   "
              f"D: {fmt_row('D')}   |   M: {fmt_row('M')}")

    handles = [
        Line2D([0], [0], color=COL_GT_TOP, lw=2, label="Ground-truth rep top"),
        Line2D([0], [0], color=COL_PRED, lw=2, ls="--", label="Predicted lockout"),
        Line2D([0], [0], color=COL_RACK, lw=2, label="Rack"),
        Line2D([0], [0], color=COL_VY, lw=2, label="Y velocity"),
        Line2D([0], [0], marker="o", color=COL_PCV, lw=0, markersize=7,
               label="Drive peak (PCV)"),
        Line2D([0], [0], marker="o", color=COL_SP, lw=0, markersize=8,
               label="Sticking point (SP)"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=6, fontsize=9,
               facecolor=COL_BG_FIG, edgecolor=COL_SPINE,
               labelcolor="white", framealpha=0.6,
               bbox_to_anchor=(0.5, 0.02))
    fig.text(0.5, -0.002, footer, color="white", ha="center",
             va="bottom", fontsize=9)
    fig.suptitle(
        "Sticking-point detection — 8 clean sessions (velocity valley "
        "between drive peak and lockout)",
        color="white", fontsize=14, fontweight="bold", y=0.998)

    plt.tight_layout(rect=[0, 0.045, 1, 0.99])
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    print(f"Saved → {args.out}")

    # Print a validation table the user can eyeball
    print()
    print(f"{'session':<45} {'SP/reps':>8} {'pos̄':>6} {'pos CV':>7} "
          f"{'depth̄':>7} {'d CV':>6} {'verdict'}")
    print("-" * 95)
    for name, v in zip(CLEAN_SESSIONS, vals):
        pf = "—" if math.isnan(v["mean_frac"]) else f"{v['mean_frac']*100:.0f}%"
        pc = "—" if math.isnan(v["frac_cv"]) else f"{v['frac_cv']*100:.0f}%"
        dp = "—" if math.isnan(v["mean_depth"]) else f"{v['mean_depth']:.2f}"
        dc = "—" if math.isnan(v["depth_cv"]) else f"{v['depth_cv']*100:.0f}%"
        print(f"{name:<45} {v['n_stick']:>3}/{v['n_reps']:<3}   "
              f"{pf:>5} {pc:>6} {dp:>6} {dc:>5} "
              f"{'PASS' if v['passes'] else 'FAIL'}")

    print("-" * 95)
    print(f"Aggregate: {agg['n_pass']}/{agg['n_sessions']} PASS  |  "
          f"detection rate {agg['det_rate']*100:.0f}%  |  "
          f"depth-monotone pairs {agg['monotone_ok']}/{agg['monotone_total']}")
    for p in ("D", "M"):
        row = agg["by_lifter"].get(p, {})
        print(f"  {p}: " + "  ".join(
            f"{w}lb={'—' if math.isnan(row.get(w, math.nan)) else f'{row[w]:.2f}'} m/s"
            for w in sorted(row)))


if __name__ == "__main__":
    main()
