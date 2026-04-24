"""
Render the 8-trial velocity-metrics figure.

Produces a 4×2 grid — one panel per clean session — showing:
    • Y-velocity trace (pink, concentric shaded +, eccentric shaded −)
    • Ground-truth chest (red dashed) and rep-top (cyan) lines from the
      annotation file
    • Rack line (purple)
    • Detector-based concentric window bracketed in green
    • Per-rep annotation block: MCV, PCV, MPV, ROM
    • Per-panel header: #reps, ROM CV, %MCV-decreasing, endpoint residual
      (all four of which double as validation checks)

Validation strip (bottom of figure):
    - Aggregate endpoint residual (should be ≈ 0 m/s by construction)
    - Mean ROM CV across reps (bar travel consistent ⇒ low number)
    - Mean ROM symmetry error (concentric ROM ≈ eccentric ROM ⇒ low)
    - Fraction of sessions where MCV decreases monotonically within set
    - Fraction of chest/top events within 150 ms of an annotator click

The 8 sessions match plot_predicted_vs_truth.py.

Usage:
    python3 src/velocity/plot_velocity_metrics.py
    python3 src/velocity/plot_velocity_metrics.py --method B --out <png>
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

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

# Colour palette matches plot_predicted_vs_truth.py for visual consistency
COL_BG_FIG = "#1a1a2e"
COL_BG_AX = "#16213e"
COL_SPINE = "#444466"
COL_VY = "#fd79a8"
COL_VY_POS = "#fd79a8"
COL_VY_NEG = "#74b9ff"
COL_GT_CHEST = "#e74c3c"
COL_GT_TOP = "#00cec9"
COL_RACK = "#9b59b6"
COL_DET_OK = "#2ecc71"
COL_METRIC = "#ffe66d"
COL_PASS = "#2ecc71"
COL_FAIL = "#e74c3c"


def _style_ax(ax):
    ax.set_facecolor(COL_BG_AX)
    ax.tick_params(colors="white", labelsize=7)
    for s in ax.spines.values():
        s.set_color(COL_SPINE)
    ax.yaxis.label.set_color("white")
    ax.xaxis.label.set_color("white")


def _validate_session(result, tol_s: float = 0.15) -> dict:
    """Per-session validation block. Numbers the panel header summarises."""
    t = result["t"]
    vy = result["vy"]
    reps = result["reps"]
    boundaries = result["boundaries"]
    anns = result["annotations"]

    # (a) endpoint residual
    ep = []
    for ci, li in boundaries:
        ep.append(abs(float(vy[ci])))
        ep.append(abs(float(vy[li])))
    endpoint = float(np.mean(ep)) if ep else 0.0

    # (b) ROM coefficient of variation
    roms = [r.rom_m for r in reps if r.rom_m > 0]
    rom_cv = float(np.std(roms) / np.mean(roms)) if roms else float("nan")

    # (c) ROM symmetry (skip rep 1, which is unrack-descent)
    sym = [abs(r.rom_m - r.erom_m) / r.rom_m
           for r in reps[1:] if r.rom_m > 0 and r.erom_m > 0]
    rom_sym = float(np.mean(sym)) if sym else float("nan")

    # (d) timing accuracy — how close are our boundaries to the annotator's
    # clicks? Detector boundaries should land near annotations even though
    # they're independently-computed zero-crossings.
    timing_errs = []
    ann_tops = [a["top_s"] for a in anns["reps"]]
    ann_chests = [a["chest_s"] for a in anns["reps"]]
    for (ci, li), rep in zip(boundaries, reps):
        t_top = float(t[li])
        t_chest = float(t[ci])
        # Match by rep number
        gt = next((a for a in anns["reps"] if a["num"] == rep.num), None)
        if gt is not None:
            timing_errs.append(abs(t_top - gt["top_s"]))
            timing_errs.append(abs(t_chest - gt["chest_s"]))
    timing_within = (float(np.mean([e <= tol_s for e in timing_errs]))
                     if timing_errs else float("nan"))
    timing_mean = float(np.mean(timing_errs)) if timing_errs else float("nan")

    # (e) within-set MCV-decreasing fraction
    pct_dec = float("nan")
    if len(reps) >= 2:
        pairs = [(reps[i].mcv, reps[i + 1].mcv) for i in range(len(reps) - 1)]
        pct_dec = float(np.mean([1.0 if b <= a + 1e-6 else 0.0 for a, b in pairs]))

    # (f) first-rep vs last-rep MCV drop (velocity loss)
    v_loss = (reps[0].mcv - reps[-1].mcv) if len(reps) >= 2 else float("nan")

    # Pass/fail criteria (conservative)
    n_reps_match = len(reps) == len(anns["reps"])
    passes = (
        n_reps_match
        and endpoint <= 0.05
        and (np.isnan(rom_cv) or rom_cv <= 0.25)
        and (np.isnan(timing_within) or timing_within >= 0.80)
    )

    return {
        "endpoint": endpoint,
        "rom_cv": rom_cv,
        "rom_sym": rom_sym,
        "timing_mean": timing_mean,
        "timing_within_tol": timing_within,
        "pct_mcv_decreasing": pct_dec,
        "velocity_loss": v_loss,
        "n_reps_match": n_reps_match,
        "n_detected": len(reps),
        "n_annotated": len(anns["reps"]),
        "passes": bool(passes),
    }


def _plot_one(ax, name, result, v_block):
    t = result["t"]
    vy = result["vy"]
    reps = result["reps"]
    boundaries = result["boundaries"]
    anns = result["annotations"]

    _style_ax(ax)
    # Method B's raw integrator drifts hugely BEFORE the first rep and
    # AFTER the last (no endpoint anchors there). Clip the plotted signal
    # to [rep_0.chest - 0.5s, last_rep.lockout + 0.5s] so that drift
    # tail doesn't blow up the y-axis.
    if boundaries:
        fs = result["fs"]
        clip_lo = max(0, boundaries[0][0] - int(0.5 * fs))
        clip_hi = min(len(t), boundaries[-1][1] + int(0.5 * fs))
    else:
        clip_lo, clip_hi = 0, len(t)
    t_plot = t[clip_lo:clip_hi]
    vy_plot = vy[clip_lo:clip_hi]

    ax.plot(t_plot, vy_plot, color=COL_VY, lw=1.1)
    ax.fill_between(t_plot, vy_plot, 0,
                    where=(vy_plot > 0), color=COL_VY_POS, alpha=0.18)
    ax.fill_between(t_plot, vy_plot, 0,
                    where=(vy_plot < 0), color=COL_VY_NEG, alpha=0.18)
    ax.axhline(0, color="#555577", lw=0.6)

    # Ground-truth chest (red dashed) and rep tops (cyan solid)
    for ann_rep in anns["reps"]:
        ax.axvline(ann_rep["chest_s"], color=COL_GT_CHEST, ls=":",
                   lw=0.9, alpha=0.7)
    for ann_rep in anns["reps"]:
        ax.axvline(ann_rep["top_s"], color=COL_GT_TOP, lw=1.3, alpha=0.9)

    if anns["rack_s"] is not None:
        ax.axvline(anns["rack_s"], color=COL_RACK, lw=1.2, alpha=0.85)

    # Detector-based concentric windows: green bracket
    for (ci, li), rep in zip(boundaries, reps):
        ax.axvspan(t[ci], t[li], color=COL_DET_OK, alpha=0.10, zorder=0)
        ax.axvline(t[ci], color=COL_DET_OK, lw=1.0, alpha=0.9)
        ax.axvline(t[li], color=COL_DET_OK, lw=1.0, ls="--", alpha=0.9)

    # Give the y-axis just enough headroom for the 4-line metric block.
    # Use the clipped vy range so pre/post-rep drift (Method B) doesn't
    # dominate the y scale.
    y_max = max(vy_plot.max(), max((r.pcv for r in reps), default=0.0))
    y_min = min(vy_plot.min(), 0.0)
    span = max(y_max - y_min, 1e-3)
    ax.set_ylim(y_min - 0.05 * span, y_max + 0.28 * span)

    # Per-rep metric annotations — placed just above the concentric peak
    # of each rep so the reader can match metric-block ↔ rep visually.
    for (ci, li), rep in zip(boundaries, reps):
        mid = 0.5 * (t[ci] + t[li])
        block = (f"MCV {rep.mcv:.2f}\n"
                 f"PCV {rep.pcv:.2f}\n"
                 f"MPV {rep.mpv:.2f}\n"
                 f"{rep.rom_m * 100:.0f}cm")
        ax.text(mid, rep.pcv + 0.02 * span, block, color=COL_METRIC,
                fontsize=6.0, ha="center", va="bottom",
                linespacing=0.95, fontweight="bold")

    # Zoom x-axis to the clipped rep region
    if len(t_plot) > 0:
        ax.set_xlim(t_plot[0], t_plot[-1])

    # Header summarising the validation block
    v = v_block
    verdict = "PASS" if v["passes"] else "FAIL"
    color = COL_PASS if v["passes"] else COL_FAIL
    header = (f"{name}  |  n={v['n_detected']}/{v['n_annotated']}  "
              f"ROM CV={v['rom_cv']*100:.1f}%  "
              f"|Δt|={v['timing_mean']*1000:.0f}ms  "
              f"endpt={v['endpoint']*1000:.0f}mm/s  "
              f"vLoss={v['velocity_loss']:+.2f}m/s  [{verdict}]")
    ax.set_title(header, color=color, fontsize=9, pad=4)
    ax.set_ylabel("vy (m/s)", color="white", fontsize=8)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", default="data_collection")
    p.add_argument("--method", default="B", choices=["A", "B", "C", "D"],
                   help="Integration method (default B = per-rep detrend; "
                        "the compare_methods.py composite winner)")
    p.add_argument("--out", default="data_collection/velocity_metrics.png")
    args = p.parse_args()

    fig, axes = plt.subplots(4, 2, figsize=(20, 17), sharex=False)
    fig.patch.set_facecolor(COL_BG_FIG)

    # Compute and validate each session
    results: List[dict] = []
    validations: List[dict] = []
    for name in CLEAN_SESSIONS:
        csv = os.path.join(args.dir, name + ".csv")
        ann = os.path.join(args.dir, name + "_annotations.csv")
        res = compute_metrics(csv, ann, method=args.method, use_detector=True)
        results.append(res)
        validations.append(_validate_session(res))

    for ax, name, res, val in zip(axes.flat, CLEAN_SESSIONS, results, validations):
        _plot_one(ax, name, res, val)

    for ax in axes[-1, :]:
        ax.set_xlabel("Time (s)", color="white", fontsize=9)

    # Aggregate validation bar (footer)
    n_pass = sum(1 for v in validations if v["passes"])
    agg_endpoint = np.mean([v["endpoint"] for v in validations])
    agg_rom_cv = np.nanmean([v["rom_cv"] for v in validations])
    agg_rom_sym = np.nanmean([v["rom_sym"] for v in validations])
    agg_timing = np.nanmean([v["timing_mean"] for v in validations])
    agg_within = np.nanmean([v["timing_within_tol"] for v in validations])
    agg_mcv_dec = np.nanmean([v["pct_mcv_decreasing"] for v in validations])
    footer = (f"Method {args.method}  |  "
              f"{n_pass}/{len(validations)} sessions pass   "
              f"·   endpoint residual {agg_endpoint*1000:.1f} mm/s   "
              f"·   ROM CV {agg_rom_cv*100:.1f}%   "
              f"·   ROM symmetry err {agg_rom_sym*100:.1f}%   "
              f"·   timing |Δt| {agg_timing*1000:.0f} ms   "
              f"(≤150 ms: {agg_within*100:.0f}%)   "
              f"·   MCV↓ {agg_mcv_dec*100:.0f}%")

    # Legend
    handles = [
        Line2D([0], [0], color=COL_VY, lw=2, label="Y velocity"),
        Line2D([0], [0], color=COL_GT_CHEST, lw=2, ls=":",
               label="GT chest (annot.)"),
        Line2D([0], [0], color=COL_GT_TOP, lw=2, label="GT rep top (annot.)"),
        Line2D([0], [0], color=COL_DET_OK, lw=2,
               label="Detected concentric window"),
        Line2D([0], [0], color=COL_RACK, lw=2, label="Rack"),
        Line2D([0], [0], color=COL_METRIC, lw=0, marker="s", markersize=7,
               label="Per-rep MCV / PCV / MPV / ROM"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=6, fontsize=9,
               facecolor=COL_BG_FIG, edgecolor=COL_SPINE, labelcolor="white",
               framealpha=0.6, bbox_to_anchor=(0.5, 0.02))
    fig.text(0.5, -0.002, footer, color="white", ha="center",
             va="bottom", fontsize=9)
    fig.suptitle(
        f"Per-rep velocity metrics — 8 clean sessions (Method {args.method}, "
        f"detector-based boundaries)",
        color="white", fontsize=14, fontweight="bold", y=0.998)

    plt.tight_layout(rect=[0, 0.045, 1, 0.99])
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    print(f"Saved → {args.out}")

    # Also print the validation table for the user
    print()
    print(f"{'session':<55} {'n':>6} {'ROM CV':>7} {'endpt':>7} "
          f"{'|Δt|':>6} {'MCV↓':>5} {'verdict'}")
    print("-" * 100)
    for name, v in zip(CLEAN_SESSIONS, validations):
        print(f"{name:<55} {v['n_detected']}/{v['n_annotated']:<3} "
              f"{v['rom_cv']*100:>6.1f}% {v['endpoint']*1000:>5.1f}mm/s "
              f"{v['timing_mean']*1000:>4.0f}ms "
              f"{v['pct_mcv_decreasing']*100:>4.0f}% "
              f"{'PASS' if v['passes'] else 'FAIL'}")
    print(f"{'AGGREGATE':<55} {sum(v['n_detected'] for v in validations)}/"
          f"{sum(v['n_annotated'] for v in validations)}   "
          f"{agg_rom_cv*100:>4.1f}% {agg_endpoint*1000:>5.1f}mm/s "
          f"{agg_timing*1000:>4.0f}ms "
          f"{agg_mcv_dec*100:>4.0f}% "
          f"{n_pass}/{len(validations)} PASS")


if __name__ == "__main__":
    main()
