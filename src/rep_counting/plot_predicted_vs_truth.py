"""
Plot predicted reps vs ground-truth annotations for the 8 clean sessions.

Produces one PNG (a 4x2 grid) per run:
  - Y velocity trace
  - Ground-truth rep tops (solid cyan)
  - Predicted rep lockouts (dashed green)
  - Timing error (gt_top - predicted_lockout) printed per rep

Excludes the 3 sessions flagged as having messed-up/miscalibrated data:
  D_135_10_bad, session_20260414_102551, session_20260416_131031.
"""
import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))
from sign_change_rep_counter import (  # noqa
    compute_vy, build_reps, filter_by_rerack_gyro, filter_by_post_motion,
)
from validate_all import parse_ground_truth, TIMING_TOL_S

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

V_HI = 0.25
RERACK_RATIO = 1.5
POST_WINDOW_S = 2.0
POST_MIN_GYRO = 0.7


def run_detector(csv_path):
    df = pd.read_csv(csv_path)
    t, vy, gmag, fs = compute_vy(df)
    cands = build_reps(vy, V_HI, fs)
    after_r = filter_by_rerack_gyro(cands, gmag, fs, RERACK_RATIO)
    kept = filter_by_post_motion(after_r, vy, gmag, fs,
                                 POST_WINDOW_S, POST_MIN_GYRO)
    return t, vy, kept, fs


def plot_one(ax, name, t, vy, kept, gt_reps, rack_s):
    ax.set_facecolor("#16213e")
    ax.plot(t, vy, color="#fd79a8", lw=1.1)
    ax.fill_between(t, vy, 0, where=(vy > 0), color="#fd79a8", alpha=0.15)
    ax.fill_between(t, vy, 0, where=(vy < 0), color="#74b9ff", alpha=0.15)
    ax.axhline(0, color="#555577", lw=0.6)

    # Ground-truth rep tops (cyan solid) — lockout-aligned per the annotator
    for num, gt_t in gt_reps:
        ax.axvline(gt_t, color="#00cec9", lw=1.4, alpha=0.95)
        ax.text(gt_t, ax.get_ylim()[1] * 0.95, f"gt{num}",
                color="#00cec9", fontsize=7, ha="right", va="top", rotation=90)

    # Predicted lockouts (green dashed) + timing-error text
    gt_times = [g for _, g in gt_reps]
    used = set()
    for k, rep in enumerate(kept):
        pred_t = rep["lockout_s"]
        ax.axvline(pred_t, color="#2ecc71", lw=1.3, ls="--", alpha=0.9)
        # nearest unused gt for delta
        best_i, best_dt = None, None
        for i, g in enumerate(gt_times):
            if i in used:
                continue
            dt = pred_t - g
            if best_dt is None or abs(dt) < abs(best_dt):
                best_i, best_dt = i, dt
        if best_i is not None and abs(best_dt) <= TIMING_TOL_S:
            used.add(best_i)
            ax.text(pred_t, ax.get_ylim()[0] * 0.85,
                    f"{best_dt*1000:+.0f}ms",
                    color="#2ecc71", fontsize=6.5, ha="center", va="bottom")

    if rack_s is not None:
        ax.axvline(rack_s, color="#9b59b6", lw=1.2, alpha=0.8)
        ax.text(rack_s, ax.get_ylim()[1] * 0.95, "rack",
                color="#9b59b6", fontsize=7, ha="right", va="top", rotation=90)

    n_gt = len(gt_reps)
    n_pred = len(kept)
    n_match = len(used)
    n_miss = n_gt - n_match
    n_extra = n_pred - n_match
    verdict = "PASS" if (n_miss == 0 and n_extra == 0) else "FAIL"
    color = "#2ecc71" if verdict == "PASS" else "#e74c3c"
    ax.set_title(
        f"{name}   gt={n_gt}  pred={n_pred}  match={n_match}  "
        f"miss={n_miss}  extra={n_extra}  [{verdict}]",
        color=color, fontsize=9, pad=3,
    )
    ax.tick_params(colors="white", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#444466")
    ax.set_ylabel("vy (m/s)", color="white", fontsize=8)


def main():
    data_dir = "data_collection"
    fig, axes = plt.subplots(4, 2, figsize=(18, 14), sharex=False)
    fig.patch.set_facecolor("#1a1a2e")

    for ax_flat, name in zip(axes.flat, CLEAN_SESSIONS):
        csv = os.path.join(data_dir, name + ".csv")
        ann = os.path.join(data_dir, name + "_annotations.csv")
        t, vy, kept, fs = run_detector(csv)
        gt_reps, rack_s = parse_ground_truth(ann)
        plot_one(ax_flat, name, t, vy, kept, gt_reps, rack_s)
        # Zoom x-axis to the active portion (first rep → rack or last pred)
        if gt_reps:
            t_start = gt_reps[0][1] - 3.0
            t_end_candidates = [gt_reps[-1][1]]
            if rack_s is not None:
                t_end_candidates.append(rack_s)
            if kept:
                t_end_candidates.append(kept[-1]["lockout_s"])
            t_end = max(t_end_candidates) + 3.0
            ax_flat.set_xlim(max(0, t_start), t_end)

    for ax in axes[-1, :]:
        ax.set_xlabel("Time (s)", color="white", fontsize=9)

    # Legend
    from matplotlib.lines import Line2D
    handles = [
        Line2D([0], [0], color="#00cec9", lw=2, label="Ground-truth rep top"),
        Line2D([0], [0], color="#2ecc71", lw=2, ls="--",
               label="Predicted lockout"),
        Line2D([0], [0], color="#9b59b6", lw=2, label="Rack"),
        Line2D([0], [0], color="#fd79a8", lw=2, label="Y velocity"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=10,
               facecolor="#1a1a2e", edgecolor="#444466", labelcolor="white",
               framealpha=0.6, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle("Predicted reps vs. ground-truth annotations (8 clean sessions)",
                 color="white", fontsize=14, fontweight="bold", y=0.995)

    plt.tight_layout(rect=[0, 0.02, 1, 0.99])
    out = "data_collection/predicted_vs_truth.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Saved → {out}")


if __name__ == "__main__":
    main()
