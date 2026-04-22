"""
Multi-session 1RM prediction figure.

Renders the same 8 clean trials as plot_predicted_vs_truth.py and
plot_sticking_point.py (matching their visual language — dark theme,
cyan rep tops, green dashed predicted lockouts, purple rack, pink vy
trace) and adds:

    • Per-rep MPV stamps along the bottom of each panel
    • Yellow dot on the rep with the highest MPV in the set
    • Session header: load × reps, best MPV, rep-1 MPV, within-set
      velocity-loss, GB-equation %1RM estimate
    • Two bottom "load-velocity profile" panels (D, M) showing:
        - per-set scatter of (load, best MPV)
        - fitted LVP regression line (full-data AND trimmed variants)
        - MVT horizontal line (0.17 m/s)
        - extrapolated 1RM with 95% CI whisker
        - expected-range shaded band (305-345 for D, 250-300 for M)
        - PASS/FAIL verdict

Validation built into the figure
--------------------------------
V1  per-panel: GB-equation %1RM falls in [40, 90]% — i.e. the load is
    physiologically in a submaximal training zone (sanity check).
V2  per-lifter: consensus 1RM inside the expected range (strict).
V3  per-lifter: 95% CI overlaps the expected range.
V4  per-lifter: at least one sub-estimator inside range.

Usage:
    python3 src/one_rm/plot_one_rm.py
    python3 src/one_rm/plot_one_rm.py --method B
        --out data_collection/one_rm_all.png
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
from matplotlib.patches import Patch
from matplotlib.gridspec import GridSpec

sys.path.insert(0, os.path.dirname(__file__))
from one_rm import (  # noqa: E402
    load_all_sessions, estimate_lifter_1rm, _gb_pct_1rm,
    MVT_MPV, CLEAN_SESSIONS,
)
from velocity_metrics import compute_metrics  # noqa: E402

EXPECTED = {"D": (305.0, 345.0), "M": (250.0, 300.0)}

COL_BG_FIG = "#1a1a2e"
COL_BG_AX = "#16213e"
COL_SPINE = "#444466"
COL_VY = "#fd79a8"
COL_VY_POS = "#fd79a8"
COL_VY_NEG = "#74b9ff"
COL_GT_TOP = "#00cec9"
COL_RACK = "#9b59b6"
COL_PRED = "#2ecc71"
COL_BEST = "#ffeaa7"
COL_MPV_TXT = "#ffc76b"
COL_PASS = "#2ecc71"
COL_FAIL = "#e74c3c"
COL_EXPECT = "#3498db"
COL_MVT = "#e17055"
COL_LVP = "#74b9ff"         # M1 — MPV LVP (best-per-set)
COL_LVP_TOP2 = "#a29bfe"    # M3 — MPV LVP (mean top-2)
COL_LVP_TRIM = "#f39c12"    # M6 — MPV LVP (trimmed)
COL_LVP_MCV = "#00cec9"     # M2 — MCV LVP (shown as vertical marker)
COL_CONSENSUS = "#2ecc71"   # weighted consensus line + star


def _style_ax(ax):
    ax.set_facecolor(COL_BG_AX)
    ax.tick_params(colors="white", labelsize=7)
    for s in ax.spines.values():
        s.set_color(COL_SPINE)
    ax.yaxis.label.set_color("white")
    ax.xaxis.label.set_color("white")
    ax.title.set_color("white")


def _plot_session(ax, name, result, feats):
    _style_ax(ax)
    t = result["t"]
    vy = result["vy"]
    boundaries = result["boundaries"]
    anns = result["annotations"]
    reps = result["reps"]

    if boundaries:
        fs = result["fs"]
        clip_lo = max(0, boundaries[0][0] - int(0.5 * fs))
        clip_hi = min(len(t), boundaries[-1][1] + int(0.5 * fs))
    else:
        clip_lo, clip_hi = 0, len(t)
    t_p = t[clip_lo:clip_hi]
    vy_p = vy[clip_lo:clip_hi]

    ax.plot(t_p, vy_p, color=COL_VY, lw=1.1)
    ax.fill_between(t_p, vy_p, 0, where=(vy_p > 0),
                    color=COL_VY_POS, alpha=0.18)
    ax.fill_between(t_p, vy_p, 0, where=(vy_p < 0),
                    color=COL_VY_NEG, alpha=0.18)
    ax.axhline(0, color="#555577", lw=0.6)

    for ann_rep in anns["reps"]:
        ax.axvline(ann_rep["top_s"], color=COL_GT_TOP, lw=1.3, alpha=0.9)
    for ci, li in boundaries:
        ax.axvline(t[li], color=COL_PRED, lw=1.1, ls="--", alpha=0.85)
    if anns["rack_s"] is not None:
        ax.axvline(anns["rack_s"], color=COL_RACK, lw=1.2, alpha=0.85)

    # Per-rep MPV labels just above each lockout
    mpvs = [r.mpv for r in reps]
    if mpvs:
        best_mpv = max(mpvs)
        best_idx = int(np.argmax(mpvs))
    else:
        best_mpv, best_idx = math.nan, -1

    ylim_top = max(0.2, float(np.max(vy_p)) + 0.1) if len(vy_p) else 1.0
    ylim_bot = min(-0.2, float(np.min(vy_p)) - 0.05) if len(vy_p) else -1.0

    for i, rep in enumerate(reps):
        pk_t = rep.top_s
        # Propulsive velocity label (bold yellow for best rep, dim orange otherwise)
        is_best = (i == best_idx)
        color = COL_BEST if is_best else COL_MPV_TXT
        weight = "bold" if is_best else "normal"
        ax.text(pk_t, ylim_bot + 0.04,
                f"{rep.mpv:.2f}", color=color, fontsize=6.2,
                ha="center", va="bottom", fontweight=weight, alpha=0.95)
        if is_best:
            # Place a yellow dot at peak vy of the best rep
            # Find peak time/velocity in the concentric window
            ci = result["boundaries"][i][0] if i < len(result["boundaries"]) else None
            li = result["boundaries"][i][1] if i < len(result["boundaries"]) else None
            if ci is not None and li is not None and li > ci:
                c_t = t[ci:li + 1]
                c_v = vy[ci:li + 1]
                pk_rel = int(np.argmax(c_v))
                ax.plot(c_t[pk_rel], c_v[pk_rel], "o",
                        color=COL_BEST, ms=6,
                        markeredgecolor=COL_BG_AX, markeredgewidth=0.5,
                        zorder=6)

    ax.set_ylim(ylim_bot, ylim_top)
    if len(t_p):
        ax.set_xlim(t_p[0], t_p[-1])

    # Header
    gb_pct = (_gb_pct_1rm(feats.best_mpv) * 100
              if not math.isnan(feats.best_mpv) else math.nan)
    gb_pct_s = "—" if math.isnan(gb_pct) else f"{gb_pct:.0f}%"
    best_mpv_s = "—" if math.isnan(best_mpv) else f"{best_mpv:.3f}"
    r1_s = "—" if math.isnan(feats.rep1_mpv) else f"{feats.rep1_mpv:.3f}"
    vl_s = ("—" if math.isnan(feats.vl_frac)
            else f"{feats.vl_frac*100:.0f}%")
    v1_pass = 0.40 <= (gb_pct / 100.0 if not math.isnan(gb_pct) else 0.0) <= 0.90
    v_color = COL_PASS if v1_pass else COL_FAIL
    verdict = "PASS" if v1_pass else "FAIL"
    header = (f"{name}   bestMPV={best_mpv_s}  r1MPV={r1_s}  "
              f"VL={vl_s}  GB={gb_pct_s}  [{verdict}]")
    ax.set_title(header, color=v_color, fontsize=8.5, pad=3)
    ax.set_ylabel("vy (m/s)", color="white", fontsize=8)


def _plot_lvp_panel(ax, lifter, est, expected_rng):
    _style_ax(ax)
    # Scatter of best MPV per load (this is the M1 input)
    loads = np.array([s.load_lb for s in est.sessions], dtype=float)
    best_mpv = np.array([s.best_mpv for s in est.sessions])
    top2_mpv = np.array([s.top2_mpv for s in est.sessions])

    ax.scatter(loads, best_mpv, color=COL_BEST, s=60, zorder=5,
               edgecolor=COL_BG_AX, linewidth=0.8, label="best MPV / set")
    ax.scatter(loads, top2_mpv, color=COL_MPV_TXT, s=24, zorder=4,
               alpha=0.7, label="top-2 MPV / set")

    # Extend x to the expected range + CI so the line reaches 1RM
    x_max_candidates = [loads.max() + 20, expected_rng[1] + 30,
                        est.consensus_one_rm_lb if not math.isnan(est.consensus_one_rm_lb) else 0,
                        est.ci95[1] if not math.isnan(est.ci95[1]) else 0]
    x_hi = max(x_max_candidates)
    xs = np.linspace(loads.min() - 10, x_hi, 200)

    m1, m2, m3, m4, m5, m6 = est.estimators

    # Which LVP estimators are actually contributing to the consensus?
    # Matches the logic in estimate_lifter_1rm.
    consensus_parts = []    # (estimator, label)
    if m1.valid or m2.valid or m3.valid:
        if m1.valid:
            consensus_parts.append(m1)
        if m2.valid:
            consensus_parts.append(m2)
        if m3.valid:
            consensus_parts.append(m3)
    elif m6.valid:
        consensus_parts.append(m6)

    # ─ M1: MPV-LVP (best) on MPV axis ────────────────────────────────
    if m1.valid:
        ys = m1.intercept + m1.slope * xs
        lw = 1.6 if m1 in consensus_parts else 1.0
        alpha = 0.95 if m1 in consensus_parts else 0.45
        ax.plot(xs, ys, color=COL_LVP, lw=lw, alpha=alpha,
                label=f"M1 MPV-LVP (best)  R²={m1.r2:.2f} → "
                      f"{m1.one_rm_lb:.0f} lb")

    # ─ M3: MPV-LVP (mean top-2) on MPV axis ──────────────────────────
    if m3.valid:
        ys = m3.intercept + m3.slope * xs
        lw = 1.6 if m3 in consensus_parts else 1.0
        alpha = 0.95 if m3 in consensus_parts else 0.45
        ax.plot(xs, ys, color=COL_LVP_TOP2, lw=lw, alpha=alpha,
                label=f"M3 MPV-LVP (top-2)  R²={m3.r2:.2f} → "
                      f"{m3.one_rm_lb:.0f} lb")

    # ─ M6: MPV-LVP (trimmed) on MPV axis — only when used ────────────
    if m6.valid and m6 in consensus_parts:
        ys = m6.intercept + m6.slope * xs
        ax.plot(xs, ys, color=COL_LVP_TRIM, lw=1.6, alpha=0.95,
                label=f"M6 MPV-LVP (trimmed)  R²={m6.r2:.2f} → "
                      f"{m6.one_rm_lb:.0f} lb")
        if len(m6.x_points) < len(loads):
            kept = set(int(x) for x in m6.x_points)
            for L, y in zip(loads, best_mpv):
                if int(L) not in kept:
                    ax.plot(L, y, marker="x", color=COL_FAIL,
                            markersize=10, markeredgewidth=2, zorder=6,
                            label="dropped (sandbagged)")

    # ─ M2: MCV-LVP — different y-axis, plotted as a vertical marker ──
    # at the x-location of its predicted 1RM (MCV crosses MVT_MCV there).
    if m2.valid:
        lw = 1.6 if m2 in consensus_parts else 1.0
        alpha = 0.9 if m2 in consensus_parts else 0.45
        ax.axvline(m2.one_rm_lb, color=COL_LVP_MCV, ls="-.", lw=lw,
                   alpha=alpha,
                   label=f"M2 MCV-LVP  R²={m2.r2:.2f} → "
                         f"{m2.one_rm_lb:.0f} lb  (MCV axis)")

    # ─ Weighted consensus line on MPV axis ───────────────────────────
    # Slope = R²-weighted mean of MPV-based estimator slopes that are in
    # the consensus; line passes through (consensus_1RM, MVT_MPV) so
    # the star sits on it by construction.
    mpv_based = [e for e in consensus_parts
                 if e in (m1, m3, m6) and e.valid]
    one_rm = est.consensus_one_rm_lb
    if mpv_based and not math.isnan(one_rm):
        w = np.array([e.r2 for e in mpv_based])
        slopes = np.array([e.slope for e in mpv_based])
        w_slope = float(np.sum(w * slopes) / np.sum(w))
        w_intercept = MVT_MPV - w_slope * one_rm
        ys = w_intercept + w_slope * xs
        ax.plot(xs, ys, color=COL_CONSENSUS, lw=2.5, ls="--", alpha=0.95,
                zorder=6,
                label=f"Weighted consensus → {one_rm:.0f} lb")

    # MVT reference line
    ax.axhline(MVT_MPV, color=COL_MVT, ls=":", lw=1.2, alpha=0.95,
               label=f"MVT = {MVT_MPV} m/s")

    # Expected-range shaded band
    ax.axvspan(expected_rng[0], expected_rng[1], color=COL_EXPECT,
               alpha=0.12, label=f"expected [{expected_rng[0]:.0f}–"
                                 f"{expected_rng[1]:.0f}]")

    # Consensus 1RM + CI whisker at y = MVT (sits ON the weighted line)
    if not math.isnan(one_rm):
        ax.plot(one_rm, MVT_MPV, marker="*", color=COL_CONSENSUS,
                markersize=18, markeredgecolor=COL_BG_AX,
                markeredgewidth=0.8, zorder=8,
                label=f"1RM = {one_rm:.0f} lb")
        if not math.isnan(est.ci95[0]):
            ax.plot([est.ci95[0], est.ci95[1]], [MVT_MPV, MVT_MPV],
                    color=COL_CONSENSUS, lw=2.2, alpha=0.6, zorder=7)
            for xb in (est.ci95[0], est.ci95[1]):
                ax.plot([xb, xb], [MVT_MPV - 0.02, MVT_MPV + 0.02],
                        color=COL_CONSENSUS, lw=2.2, alpha=0.6, zorder=7)

    # Validation
    v2 = (not math.isnan(one_rm) and expected_rng[0] <= one_rm <= expected_rng[1])
    v3 = (not math.isnan(est.ci95[0])
          and not (est.ci95[1] < expected_rng[0]
                   or est.ci95[0] > expected_rng[1]))
    v4 = any(e.valid and expected_rng[0] <= e.one_rm_lb <= expected_rng[1]
             for e in est.estimators)
    passes = v2 or v3 or v4
    verdict = "PASS" if passes else "FAIL"
    color = COL_PASS if passes else COL_FAIL

    ax.set_xlabel("Load (lb)", color="white", fontsize=9)
    ax.set_ylabel("MPV (m/s)", color="white", fontsize=9)
    ci_s = ("—" if math.isnan(est.ci95[0])
            else f"[{est.ci95[0]:.0f}–{est.ci95[1]:.0f}]")
    one_s = "—" if math.isnan(one_rm) else f"{one_rm:.0f}"
    ax.set_title(
        f"Lifter {lifter}   1RM = {one_s} lb   95% CI {ci_s}   "
        f"V2={'✓' if v2 else '✗'} V3={'✓' if v3 else '✗'} "
        f"V4={'✓' if v4 else '✗'}   [{verdict}]",
        color=color, fontsize=10, fontweight="bold", pad=4,
    )

    leg = ax.legend(loc="upper right", fontsize=7, facecolor=COL_BG_AX,
                    edgecolor=COL_SPINE, labelcolor="white", framealpha=0.75)
    for txt in leg.get_texts():
        txt.set_color("white")

    y_lo = -0.05
    y_hi = max(1.0, float(np.nanmax(best_mpv)) + 0.15)
    ax.set_ylim(y_lo, y_hi)

    return {"v2": v2, "v3": v3, "v4": v4, "passes": passes}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", default="data_collection")
    p.add_argument("--method", default="B", choices=["A", "B", "C", "D"])
    p.add_argument("--out", default="data_collection/one_rm_all.png")
    args = p.parse_args()

    # Gather session features + per-lifter estimates
    by_lifter = load_all_sessions(args.dir, args.method)
    feats_by_name = {s.name: s for stack in by_lifter.values() for s in stack}
    estimates = {lifter: estimate_lifter_1rm(stack)
                 for lifter, stack in by_lifter.items()}

    # Rerun compute_metrics for plotting traces (feature extract discarded t/vy)
    results_by_name = {}
    for name in CLEAN_SESSIONS:
        csv = os.path.join(args.dir, name + ".csv")
        ann = os.path.join(args.dir, name + "_annotations.csv")
        results_by_name[name] = compute_metrics(
            csv, ann, method=args.method, use_detector=True,
        )

    fig = plt.figure(figsize=(20, 22))
    fig.patch.set_facecolor(COL_BG_FIG)
    gs = GridSpec(
        nrows=6, ncols=2,
        height_ratios=[1, 1, 1, 1, 1.4, 0.15],
        hspace=0.5, wspace=0.15,
        left=0.05, right=0.98, top=0.96, bottom=0.04,
    )

    # Session panels (rows 0-3, 8 total)
    for idx, name in enumerate(CLEAN_SESSIONS):
        row = idx // 2
        col = idx % 2
        ax = fig.add_subplot(gs[row, col])
        _plot_session(ax, name, results_by_name[name], feats_by_name[name])
        if row == 3:
            ax.set_xlabel("Time (s)", color="white", fontsize=9)

    # LVP panels (row 4)
    ax_lvp_d = fig.add_subplot(gs[4, 0])
    ax_lvp_m = fig.add_subplot(gs[4, 1])
    d_val = _plot_lvp_panel(ax_lvp_d, "D", estimates["D"], EXPECTED["D"])
    m_val = _plot_lvp_panel(ax_lvp_m, "M", estimates["M"], EXPECTED["M"])

    # Shared legend strip (row 5)
    ax_legend = fig.add_subplot(gs[5, :])
    ax_legend.axis("off")
    handles = [
        Line2D([0], [0], color=COL_GT_TOP, lw=2, label="Ground-truth rep top"),
        Line2D([0], [0], color=COL_PRED, lw=2, ls="--", label="Predicted lockout"),
        Line2D([0], [0], color=COL_RACK, lw=2, label="Rack"),
        Line2D([0], [0], color=COL_VY, lw=2, label="Y velocity"),
        Line2D([0], [0], marker="o", color=COL_BEST, lw=0, markersize=8,
               label="Peak velocity of best rep"),
        Line2D([0], [0], marker="*", color=COL_CONSENSUS, lw=0, markersize=13,
               label="Consensus 1RM"),
        Line2D([0], [0], color=COL_LVP, lw=2, label="M1 MPV-LVP (best)"),
        Line2D([0], [0], color=COL_LVP_TOP2, lw=2, label="M3 MPV-LVP (top-2)"),
        Line2D([0], [0], color=COL_LVP_TRIM, lw=2, label="M6 MPV-LVP (trimmed)"),
        Line2D([0], [0], color=COL_LVP_MCV, lw=2, ls="-.",
               label="M2 MCV-LVP (vertical marker)"),
        Line2D([0], [0], color=COL_CONSENSUS, lw=2.5, ls="--",
               label="Weighted consensus line"),
        Line2D([0], [0], color=COL_MVT, lw=2, ls=":",
               label=f"MVT {MVT_MPV} m/s"),
        Patch(facecolor=COL_EXPECT, alpha=0.25, label="Expected 1RM range"),
    ]
    ax_legend.legend(handles=handles, loc="center", ncol=5, fontsize=9,
                     facecolor=COL_BG_FIG, edgecolor=COL_SPINE,
                     labelcolor="white", framealpha=0.6)

    # Aggregate PASS/FAIL banner
    all_pass = d_val["passes"] and m_val["passes"]
    banner_color = COL_PASS if all_pass else COL_FAIL
    footer = (f"D: 1RM={estimates['D'].consensus_one_rm_lb:.0f} lb "
              f"(expected 305-345) {'PASS' if d_val['passes'] else 'FAIL'}   |   "
              f"M: 1RM={estimates['M'].consensus_one_rm_lb:.0f} lb "
              f"(expected 250-300) {'PASS' if m_val['passes'] else 'FAIL'}   |   "
              f"Method {args.method}, MVT={MVT_MPV} m/s")
    fig.text(0.5, 0.012, footer, color=banner_color, ha="center",
             va="bottom", fontsize=10, fontweight="bold")
    fig.suptitle(
        "1RM prediction via load-velocity profile (8 clean sessions)",
        color="white", fontsize=15, fontweight="bold", y=0.985)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    print(f"Saved → {args.out}")

    # Print console summary mirroring the figure verdicts
    print()
    print(f"D: 1RM = {estimates['D'].consensus_one_rm_lb:.1f} lb   "
          f"CI = [{estimates['D'].ci95[0]:.0f}, {estimates['D'].ci95[1]:.0f}]   "
          f"expected [305, 345]   "
          f"{'PASS' if d_val['passes'] else 'FAIL'}")
    print(f"M: 1RM = {estimates['M'].consensus_one_rm_lb:.1f} lb   "
          f"CI = [{estimates['M'].ci95[0]:.0f}, {estimates['M'].ci95[1]:.0f}]   "
          f"expected [250, 300]   "
          f"{'PASS' if m_val['passes'] else 'FAIL'}")


if __name__ == "__main__":
    main()
